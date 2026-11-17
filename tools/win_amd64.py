#!/usr/bin/env python3
"""Windows/amd64 patch sites for `agy`.

The macOS patcher resolves ARM64 instruction anchors inside a Mach-O image.
Windows ships the same Go program as a PE32+ image compiled for amd64, so the
symbols, prompt templates, and patch intent are identical while every byte
encoding differs. This module owns the amd64 half:

* Go `pclntab` lookup through the PE section table (same symbol names as Mach-O).
* A small x86-64 assembler for the two hand-written thunks, so every branch is
  computed instead of pasted.
* Exact stock-byte guards. A site that no reviewed release produced fails closed;
  `site_shapes_windows.json` records the reviewed bytes and the text-section size.

Only the core long-conversation sites are ported: context-window selection for
the Gemini 4 family, the 256K checkpoint ceiling, and the 64K USER_INPUT clamps.
The TUI/CoT sites remain macOS-only until their amd64 shapes are reviewed.
"""

from __future__ import annotations

import json
import pathlib
import struct
from typing import NamedTuple

from tools import prompt_templates
from tools.binfmt import PEImage

REPO = pathlib.Path(__file__).resolve().parent.parent
SHAPES_PATH = REPO / "site_shapes_windows.json"

SUPPORTED_VERSIONS = ("1.5.9",)
CAVE_SIZE = 0xC0
GOPCLN_MAGIC_120 = 0xFFFFFFF1

# Full Go symbol names are identical on both platforms; key them by the suffix the
# patcher uses elsewhere.
TARGET_SYMBOLS = {
    "ContextWindow": "google3/third_party/jetski/cli/store/store.(*Store).ContextWindow",
    "ContextWindowChoice": "google3/third_party/jetski/cli/store/store.(*Store).ContextWindowChoice",
    "offersContextWindow": "google3/third_party/jetski/cli/model/model.SelectorModel.offersContextWindow",
    "GetCheckpointConfig": "google3/third_party/jetski/cortex/utils/utils.GetCheckpointConfig",
    "applyFeatureProviderCheckpointOverrideConfig": (
        "google3/third_party/jetski/cortex/config/config.applyFeatureProviderCheckpointOverrideConfig"
    ),
    "getMaxTokensForStep": (
        "google3/third_party/jetski/cortex/chatconverters/chatconverters.(*TrajectoryChatConverter).getMaxTokensForStep"
    ),
    "stepToMessage": "google3/third_party/oneharness/internal/core/serializers/serializers.DefaultSerializer.stepToMessage",
}

# The reviewed stock bytes live only in site_shapes_windows.json. These are the
# exact site keys the resolver consumes; a missing or malformed entry fails closed.
SITE_CW_CHOICE = "store.(*Store).ContextWindow -> (*Store).ContextWindowChoice"
SITE_CW_MISS = "store.(*Store).ContextWindow -> whitelist miss enters Gemini 4 matcher"
SITE_OCW_RETURN_TRUE = "model.SelectorModel.offersContextWindow -> return true"
SITE_OCW_MISS = "model.SelectorModel.offersContextWindow -> whitelist miss enters Gemini 4 matcher"
SITE_CHECKPOINT_CEILING = "utils.GetCheckpointConfig -> remove 256K (0x3e800) ceiling"
SITE_CHECKPOINT_ZERO = "config.applyFeatureProviderCheckpointOverrideConfig -> zero expCp.MaxTokenLimit"
SITE_USER_INPUT_JE = "chatconverters.(*TrajectoryChatConverter).getMaxTokensForStep -> disable 64K USER_INPUT clamp"
SITE_USER_INPUT_JNE = (
    "chatconverters.(*TrajectoryChatConverter).getMaxTokensForStep -> disable 64K USER_INPUT clamp (fallthrough)"
)
SITE_STEP_USER_INPUT = "serializers.DefaultSerializer.stepToMessage -> route STEP_TYPE_USER_INPUT (0xe) to unlimited branch"

STOCK_SITE_NAMES = (
    SITE_CW_CHOICE,
    SITE_CW_MISS,
    SITE_OCW_RETURN_TRUE,
    SITE_OCW_MISS,
    SITE_CHECKPOINT_CEILING,
    SITE_CHECKPOINT_ZERO,
    SITE_USER_INPUT_JE,
    SITE_USER_INPUT_JNE,
    SITE_STEP_USER_INPUT,
)

PATCH = {
    "GetCheckpointConfig": {"ceiling": "89d6909090"},  # mov esi, edx; nops
    "getMaxTokensForStep": {"je": "742b", "jne": "eb26"},  # both limited kinds -> default return
    "stepToMessage": {"user_input": "eb54"},  # USER_INPUT -> the unlimited branch
}


class Site(NamedTuple):
    domain: str
    name: str
    va: int
    offset: int
    original: bytes | None
    patched: bytes


class Asm:
    """The handful of x86-64 instructions the thunks need, with label fixups."""

    def __init__(self, base_va: int):
        self.base_va = base_va
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self._fixups: list[tuple[str, int, int, str | int]] = []

    def label(self, name: str) -> None:
        self.labels[name] = len(self.buf)

    def raw(self, data: bytes) -> None:
        self.buf += data

    def mov_rax_rsp(self, disp: int) -> None:
        self.raw(b"\x48\x8b\x84\x24" + struct.pack("<i", disp))

    def mov_rbx_rsp(self, disp: int) -> None:
        self.raw(b"\x48\x8b\x9c\x24" + struct.pack("<i", disp))

    def mov_rax_minus_one(self) -> None:
        self.raw(b"\x48\xc7\xc0\xff\xff\xff\xff")

    def mov_eax(self, value: int) -> None:
        self.raw(b"\xb8" + struct.pack("<I", value))

    def mov_esi_edx(self) -> None:
        self.raw(b"\x89\xd6")

    def mov_dword_rbx_imm32(self, disp: int, value: int) -> None:
        if not -128 <= disp <= 127:
            raise ValueError("disp8 only")
        self.raw(b"\xc7\x43" + bytes([disp & 0xFF]) + struct.pack("<I", value))

    def xor_eax_eax(self) -> None:
        self.raw(b"\x31\xc0")

    def test_al_al(self) -> None:
        self.raw(b"\x84\xc0")

    def cmp_rbx_imm8(self, value: int) -> None:
        self.raw(b"\x48\x83\xfb" + bytes([value & 0xFF]))

    def cmp_dword_rax_imm32(self, value: int) -> None:
        self.raw(b"\x81\x38" + struct.pack("<I", value))

    def cmp_dword_rax_disp_imm32(self, disp: int, value: int) -> None:
        if not -128 <= disp <= 127:
            raise ValueError("disp8 only")
        self.raw(b"\x81\x78" + bytes([disp & 0xFF]) + struct.pack("<I", value))

    def cmp_byte_rax_disp_imm8(self, disp: int, value: int) -> None:
        if not -128 <= disp <= 127:
            raise ValueError("disp8 only")
        self.raw(b"\x80\x78" + bytes([disp & 0xFF]) + bytes([value & 0xFF]))

    def ret(self) -> None:
        self.raw(b"\xc3")

    def leave(self) -> None:
        self.raw(b"\xc9")

    def _rel32(self, kind: str, target: str | int) -> None:
        pos = len(self.buf)
        self.buf += b"\x00\x00\x00\x00"
        self._fixups.append((kind, pos, 4, target))

    def _rel8(self, kind: str, target: str | int) -> None:
        pos = len(self.buf)
        self.buf += b"\x00"
        self._fixups.append((kind, pos, 1, target))

    def call(self, label: str) -> None:
        self.raw(b"\xe8")
        self._rel32("rel32_label", label)

    def jmp(self, label: str) -> None:
        self.raw(b"\xe9")
        self._rel32("rel32_label", label)

    def jz(self, label: str) -> None:
        self.raw(b"\x74")
        self._rel8("rel8_label", label)

    def jb(self, label: str) -> None:
        self.raw(b"\x72")
        self._rel8("rel8_label", label)

    def jne(self, label: str) -> None:
        self.raw(b"\x75")
        self._rel8("rel8_label", label)

    def call_va(self, target: int) -> None:
        self.raw(b"\xe8")
        self._rel32("rel32_va", target)

    def jmp_va(self, target: int) -> None:
        self.raw(b"\xe9")
        self._rel32("rel32_va", target)

    def finish(self) -> bytes:
        for kind, pos, size, target in self._fixups:
            next_pos = pos + size
            if kind.endswith("_label"):
                target_pos = self.labels[str(target)]
                rel = target_pos - next_pos
            else:
                rel = int(target) - (self.base_va + next_pos)
            if size == 1:
                if not -128 <= rel <= 127:
                    raise ValueError(f"short branch out of range: {rel}")
                self.buf[pos] = rel & 0xFF
            else:
                struct.pack_into("<i", self.buf, pos, rel)
        return bytes(self.buf)


def _load_shapes(version: str) -> dict:
    if version not in SUPPORTED_VERSIONS:
        raise RuntimeError(
            f"Windows/amd64 patches are pinned to agy v{'/v'.join(SUPPORTED_VERSIONS)}; "
            f"got v{version}. Rehearse the release and review site_shapes_windows.json first."
        )
    try:
        raw = SHAPES_PATH.read_text()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"cannot read {SHAPES_PATH.name}: {exc}") from exc
    try:
        shapes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{SHAPES_PATH.name} is not valid JSON: {exc}") from exc
    if not isinstance(shapes, dict):
        raise RuntimeError(f"{SHAPES_PATH.name} must hold an object keyed by release")
    spec = next((shapes[key] for key in (version, f"v{version}") if key in shapes), None)
    if spec is None:
        raise RuntimeError(f"{SHAPES_PATH.name} has no reviewed shapes for v{version}")
    if not isinstance(spec, dict):
        raise RuntimeError(f"{SHAPES_PATH.name} entry for v{version} is not an object")
    for field in ("text_vsize", "text_raw_size"):
        value = spec.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"{SHAPES_PATH.name} has no valid {field} for v{version}")
    if spec["text_raw_size"] - CAVE_SIZE < spec["text_vsize"]:
        raise RuntimeError(
            f"{SHAPES_PATH.name}: v{version} .text raw size leaves less than the {CAVE_SIZE:#x}-byte cave"
        )
    sites = spec.get("sites")
    if not isinstance(sites, dict):
        raise RuntimeError(f"{SHAPES_PATH.name} has no reviewed sites for v{version}")
    for name in STOCK_SITE_NAMES:
        value = sites.get(name)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"{SHAPES_PATH.name} is missing reviewed stock bytes for {name} (v{version})")
        try:
            stock = bytes.fromhex(value)
        except ValueError as exc:
            raise RuntimeError(f"{SHAPES_PATH.name} has malformed reviewed stock bytes for {name}: {value!r}") from exc
        if not stock:
            raise RuntimeError(f"{SHAPES_PATH.name} has empty reviewed stock bytes for {name} (v{version})")
    return spec


def _stock(spec: dict, name: str) -> bytes:
    """The reviewed stock bytes for one site; `_load_shapes` has already validated them."""
    return bytes.fromhex(spec["sites"][name])


def _locate_pclntab(image: PEImage) -> tuple[int, int, int, int]:
    """Return (functab, funcnametab, nfunc, text_start_va)."""
    magic = struct.pack("<I", GOPCLN_MAGIC_120) + b"\x00\x00\x01\x08"
    data = image.data
    pos = data.find(magic)
    candidates = []
    while pos != -1:
        if pos + 72 <= len(data):
            nfunc = struct.unpack_from("<Q", data, pos + 8)[0]
            nfiles = struct.unpack_from("<Q", data, pos + 16)[0]
            funcname_rel = struct.unpack_from("<Q", data, pos + 32)[0]
            functab_rel = struct.unpack_from("<Q", data, pos + 64)[0]
            if 10_000 < nfunc < 2_000_000 and nfiles < 1_000_000 and funcname_rel and functab_rel:
                candidates.append((pos, nfunc, pos + funcname_rel, pos + functab_rel))
        pos = data.find(magic, pos + 1)
    if len(candidates) != 1:
        raise RuntimeError(f"expected one Go pclntab, found {len(candidates)}")
    pcln, nfunc, funcnametab, functab = candidates[0]
    text_start = image.image_base + image.text.va
    return functab, funcnametab, nfunc, text_start


def locate_functions(image: PEImage) -> dict[str, tuple[int, int]]:
    """Map the target symbols to (file_start, file_end) through the PE section table."""
    functab, funcnametab, nfunc, text_start = _locate_pclntab(image)
    data = image.data
    reverse = {name.encode(): key for key, name in TARGET_SYMBOLS.items()}
    found: dict[str, tuple[int, int]] = {}
    for index in range(nfunc):
        entry_off, fdata = struct.unpack_from("<II", data, functab + index * 8)
        name_rel = struct.unpack_from("<i", data, functab + fdata + 4)[0]
        name_start = funcnametab + name_rel
        name_end = data.find(b"\x00", name_start)
        key = reverse.get(bytes(data[name_start:name_end]))
        if key is None:
            continue
        next_off = struct.unpack_from("<I", data, functab + (index + 1) * 8)[0]
        try:
            end = image.offset_of(text_start + next_off)
        except ValueError:
            end = image.text.raw_ptr + image.text.raw_size
        found[key] = (image.offset_of(text_start + entry_off), end)
    missing = set(TARGET_SYMBOLS) - set(found)
    if missing:
        raise RuntimeError(f"missing target Go symbols in PE image: {sorted(missing)}")
    return found


def _checked(actual: bytes, stock: bytes, patched: bytes, name: str, strict: bool) -> None:
    if strict:
        if actual != stock:
            raise RuntimeError(f"{name}: stock bytes changed ({actual.hex()} != {stock.hex()}); review this release")
        return
    if actual not in (stock, patched):
        raise RuntimeError(f"{name}: bytes are neither reviewed stock nor this patch ({actual.hex()})")



def build_cave(cave_va: int, va_of: dict[str, int]) -> tuple[bytes, dict[str, int]]:
    """Assemble the shared Gemini 4 matcher plus one thunk per call site."""
    asm = Asm(cave_va)
    asm.label("helper")
    asm.cmp_rbx_imm8(9)
    asm.jb("false")
    asm.cmp_dword_rax_imm32(0x696D6547)  # "Gemi"
    asm.jne("false")
    asm.cmp_dword_rax_disp_imm32(4, 0x3420696E)  # "ni 4" (bytes 4..7)
    asm.jne("false")
    asm.cmp_byte_rax_disp_imm8(8, 0x20)  # " "
    asm.jne("false")
    asm.mov_eax(1)
    asm.ret()
    asm.label("false")
    asm.xor_eax_eax()
    asm.ret()

    asm.label("cw")
    asm.mov_rax_rsp(0xE8)
    asm.mov_rbx_rsp(0x28)
    asm.call("helper")
    asm.test_al_al()
    asm.jz("cw_miss")
    asm.xor_eax_eax()
    asm.jmp_va(va_of["ContextWindow"] + 0xD0)
    asm.label("cw_miss")
    asm.mov_rax_minus_one()
    asm.jmp_va(va_of["ContextWindow"] + 0x112)

    asm.label("ocw")
    asm.mov_rax_rsp(0x3DD8)
    asm.mov_rbx_rsp(0x3DC0)
    asm.call("helper")
    asm.test_al_al()
    asm.jz("ocw_miss")
    asm.mov_eax(1)
    asm.jmp_va(va_of["offersContextWindow"] + 0xB7)
    asm.label("ocw_miss")
    asm.xor_eax_eax()
    asm.jmp_va(va_of["offersContextWindow"] + 0xB7)

    asm.label("checkpoint")
    asm.mov_rbx_rsp(0x48)
    asm.mov_dword_rbx_imm32(0xC, 0)
    asm.ret()
    return asm.finish(), dict(asm.labels)


def resolve_patch_sites(data: bytes | bytearray, version: str, strict: bool = False) -> tuple[Site, ...]:
    """Resolve every reviewed Windows/amd64 site; raise instead of guessing."""
    spec = _load_shapes(version)
    image = PEImage(data)
    if image.machine != 0x8664:
        raise RuntimeError(f"expected an AMD64 PE image, got machine {image.machine:#x}")
    if image.text.raw_size != spec["text_raw_size"]:
        raise RuntimeError(
            f"PE .text raw size changed ({image.text.raw_size:#x} != {spec['text_raw_size']:#x}); review this release"
        )
    if image.text.raw_size - CAVE_SIZE < spec["text_vsize"]:
        raise RuntimeError("PE .text padding is too small for the amd64 patch cave")
    funcs = locate_functions(image)
    va_of = {key: image.va_of(start) for key, (start, _end) in funcs.items()}

    # The .text virtual size is extended over the raw padding so the loader copies
    # the cave bytes. A clean image holds the reviewed size; a patched one holds raw_size.
    vsize_offset = image.text.header_offset + 8
    vsize_actual = bytes(data[vsize_offset : vsize_offset + 4])
    vsize_stock = struct.pack("<I", spec["text_vsize"])
    vsize_patched = struct.pack("<I", image.text.raw_size)
    _checked(vsize_actual, vsize_stock, vsize_patched, "PE .text virtual size", strict)

    cave_va = image.image_base + image.text.va + (image.text.raw_size - CAVE_SIZE)
    cave_offset = image.text.raw_ptr + image.text.raw_size - CAVE_SIZE
    cave_actual = bytes(data[cave_offset : cave_offset + CAVE_SIZE])
    cave_stock = b"\xcc" * CAVE_SIZE
    cave_bytes, labels = build_cave(cave_va, va_of)
    if len(cave_bytes) > CAVE_SIZE:
        raise RuntimeError(f"amd64 cave is {len(cave_bytes)} bytes; CAVE_SIZE is {CAVE_SIZE}")
    cave_patched = cave_bytes + b"\xcc" * (CAVE_SIZE - len(cave_bytes))
    _checked(cave_actual, cave_stock, cave_patched, "PE .text amd64 cave", strict)

    def site(domain: str, name: str, va: int, stock: bytes, patched: bytes) -> Site:
        if len(patched) > len(stock):
            raise RuntimeError(f"{name}: patch is {len(patched)}B but stock is {len(stock)}B")
        patched = patched + b"\x90" * (len(stock) - len(patched))
        offset = image.offset_of(va)
        actual = bytes(data[offset : offset + len(stock)])
        _checked(actual, stock, patched, name, strict)
        return Site(domain, name, va, offset, stock, patched)

    cw_va = va_of["ContextWindow"]
    ocw_va = va_of["offersContextWindow"]
    cp_va = va_of["GetCheckpointConfig"]
    ap_va = va_of["applyFeatureProviderCheckpointOverrideConfig"]
    gm_va = va_of["getMaxTokensForStep"]
    st_va = va_of["stepToMessage"]

    choice = Asm(cw_va + 0x125)
    choice.mov_rax_rsp(0x108)
    choice.call_va(va_of["ContextWindowChoice"])
    choice.leave()
    choice.ret()

    cw_miss = Asm(cw_va + 0xC9)
    cw_miss.jmp_va(cave_va + labels["cw"])

    ocw_true = Asm(ocw_va + 0x8B)
    ocw_true.mov_eax(1)
    ocw_true.jmp_va(ocw_va + 0xB7)

    ocw_miss = Asm(ocw_va + 0x1CE)
    ocw_miss.jmp_va(cave_va + labels["ocw"])

    checkpoint = Asm(ap_va + 0x100)
    checkpoint.call_va(cave_va + labels["checkpoint"])

    sites = [
        Site(
            "pe",
            "PE .text virtual size -> cover the executable patch cave",
            image.image_base + image.text.va + spec["text_vsize"],
            vsize_offset,
            vsize_stock,
            vsize_patched,
        ),
        Site("pe", "PE .text padding -> amd64 patch cave", cave_va, cave_offset, cave_stock, cave_patched),
        site(
            "context-window",
            SITE_CW_CHOICE,
            cw_va + 0x125,
            _stock(spec, SITE_CW_CHOICE),
            choice.finish(),
        ),
        site(
            "context-window",
            SITE_CW_MISS,
            cw_va + 0xC9,
            _stock(spec, SITE_CW_MISS),
            cw_miss.finish(),
        ),
        site(
            "context-window",
            SITE_OCW_RETURN_TRUE,
            ocw_va + 0x8B,
            _stock(spec, SITE_OCW_RETURN_TRUE),
            ocw_true.finish(),
        ),
        site(
            "context-window",
            SITE_OCW_MISS,
            ocw_va + 0x1CE,
            _stock(spec, SITE_OCW_MISS),
            ocw_miss.finish(),
        ),
        site(
            "context-window",
            SITE_CHECKPOINT_CEILING,
            cp_va + 0x128,
            _stock(spec, SITE_CHECKPOINT_CEILING),
            bytes.fromhex(PATCH["GetCheckpointConfig"]["ceiling"]),
        ),
        site(
            "context-window",
            SITE_CHECKPOINT_ZERO,
            ap_va + 0x100,
            _stock(spec, SITE_CHECKPOINT_ZERO),
            checkpoint.finish(),
        ),
        site(
            "context-window",
            SITE_USER_INPUT_JE,
            gm_va + 0x43,
            _stock(spec, SITE_USER_INPUT_JE),
            bytes.fromhex(PATCH["getMaxTokensForStep"]["je"]),
        ),
        site(
            "context-window",
            SITE_USER_INPUT_JNE,
            gm_va + 0x48,
            _stock(spec, SITE_USER_INPUT_JNE),
            bytes.fromhex(PATCH["getMaxTokensForStep"]["jne"]),
        ),
        site(
            "context-window",
            SITE_STEP_USER_INPUT,
            st_va + 0x2A3,
            _stock(spec, SITE_STEP_USER_INPUT),
            bytes.fromhex(PATCH["stepToMessage"]["user_input"]),
        ),
    ]

    for override in prompt_templates.resolve_overrides(data, version, strict=strict, image=image):
        sites.append(
            Site(
                "prompt",
                f"{override.action} system_prompts/{override.name}",
                image.va_of(override.slot.offset),
                override.slot.offset,
                override.original,
                override.patched,
            )
        )
    return tuple(sites)
