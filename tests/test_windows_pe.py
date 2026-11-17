"""Offline tests for the PE/amd64 layer: address translation, assembler, and shape guard."""

from __future__ import annotations

import json
import os
import pathlib
import struct
import tempfile
import unittest
from unittest import mock

from tools import win_amd64
from tools.binfmt import PEImage


def synthetic_pe() -> bytes:
    """A minimal PE32+ with .text at RVA 0x1000 and .rdata at RVA 0x2000."""
    image = bytearray(0x600)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x40)
    image[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", image, 0x44, 0x8664, 2, 0, 0, 0, 240, 0x22)
    optional = 0x58
    struct.pack_into("<H", image, optional, 0x20B)
    struct.pack_into("<Q", image, optional + 24, 0x140000000)
    struct.pack_into("<I", image, optional + 32, 0x1000)  # section alignment
    struct.pack_into("<I", image, optional + 36, 0x200)  # file alignment
    struct.pack_into("<I", image, optional + 56, 0x3000)  # size of image
    struct.pack_into("<I", image, optional + 60, 0x200)  # size of headers
    sections = optional + 240
    struct.pack_into("<8sIIII", image, sections, b".text", 0x200, 0x1000, 0x200, 0x200)
    struct.pack_into("<8sIIII", image, sections + 40, b".rdata", 0x200, 0x2000, 0x200, 0x400)
    image[0x200:0x210] = bytes(range(16))
    image[0x400:0x408] = b"template"
    return bytes(image)


def reviewed_synthetic_pe(sites: dict[str, str]) -> bytes:
    """A small PE with a Go pclntab and the reviewed bytes at every resolver site.

    It is only large enough to exercise `resolve_patch_sites`' guard path; the
    patched instructions are not executed or treated as behaviorally verified.
    """
    text_ptr, text_va = 0x200, 0x1000
    text_vsize, text_raw_size = 0x1F00, 0x2000
    rdata_ptr, rdata_va, rdata_size = 0x2200, 0x3000, 0x15000
    image = bytearray(rdata_ptr + rdata_size)
    image[0:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x40)
    image[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", image, 0x44, 0x8664, 2, 0, 0, 0, 240, 0x22)
    optional = 0x58
    struct.pack_into("<H", image, optional, 0x20B)
    struct.pack_into("<Q", image, optional + 24, 0x140000000)
    struct.pack_into("<I", image, optional + 32, 0x1000)  # section alignment
    struct.pack_into("<I", image, optional + 36, 0x200)  # file alignment
    struct.pack_into("<I", image, optional + 56, rdata_va + rdata_size)  # size of image
    struct.pack_into("<I", image, optional + 60, 0x200)  # size of headers
    sections = optional + 240
    struct.pack_into("<8sIIII", image, sections, b".text", text_vsize, text_va, text_raw_size, text_ptr)
    struct.pack_into("<8sIIII", image, sections + 40, b".rdata", rdata_size, rdata_va, rdata_size, rdata_ptr)

    placements = (
        (win_amd64.SITE_CW_CHOICE, 0x100, 0x125),
        (win_amd64.SITE_CW_MISS, 0x100, 0xC9),
        (win_amd64.SITE_OCW_RETURN_TRUE, 0x400, 0x8B),
        (win_amd64.SITE_OCW_MISS, 0x400, 0x1CE),
        (win_amd64.SITE_CHECKPOINT_CEILING, 0x800, 0x128),
        (win_amd64.SITE_CHECKPOINT_ZERO, 0x1000, 0x100),
        (win_amd64.SITE_USER_INPUT_JE, 0x1400, 0x43),
        (win_amd64.SITE_USER_INPUT_JNE, 0x1400, 0x48),
        (win_amd64.SITE_STEP_USER_INPUT, 0x1800, 0x2A3),
    )
    for name, function_offset, site_offset in placements:
        stock = bytes.fromhex(sites[name])
        start = text_ptr + function_offset + site_offset
        image[start : start + len(stock)] = stock

    cave = text_ptr + text_raw_size - win_amd64.CAVE_SIZE
    image[cave : text_ptr + text_raw_size] = b"\xcc" * win_amd64.CAVE_SIZE

    nfunc = 10_001
    pcln = rdata_ptr + 0x100
    functab = pcln + 0x200
    names_at = functab + nfunc * 8
    image[pcln : pcln + 8] = struct.pack("<I", win_amd64.GOPCLN_MAGIC_120) + b"\x00\x00\x01\x08"
    struct.pack_into("<Q", image, pcln + 8, nfunc)
    struct.pack_into("<Q", image, pcln + 16, 1)
    struct.pack_into("<Q", image, pcln + 32, names_at - pcln)
    struct.pack_into("<Q", image, pcln + 64, functab - pcln)

    order = (
        ("ContextWindow", 0x100),
        ("ContextWindowChoice", 0x300),
        ("offersContextWindow", 0x400),
        ("GetCheckpointConfig", 0x800),
        ("applyFeatureProviderCheckpointOverrideConfig", 0x1000),
        ("getMaxTokensForStep", 0x1400),
        ("stepToMessage", 0x1800),
    )
    names = bytearray()
    name_rel: dict[str, int] = {}
    for key in [key for key, _ in order] + ["filler"]:
        name_rel[key] = len(names)
        symbol = win_amd64.TARGET_SYMBOLS.get(key)
        names += (symbol.encode() if symbol else b"filler") + b"\0"
    image[names_at : names_at + len(names)] = names
    records_at = (names_at + len(names) + 3) & ~3
    for index, (key, entry_offset) in enumerate(order):
        record = records_at + index * 8
        struct.pack_into("<i", image, record + 4, name_rel[key])
        struct.pack_into("<II", image, functab + index * 8, entry_offset, record - functab)
    filler_record = records_at + len(order) * 8
    struct.pack_into("<i", image, filler_record + 4, name_rel["filler"])
    for index in range(len(order), nfunc):
        struct.pack_into("<II", image, functab + index * 8, 0x1F00, filler_record - functab)
    return bytes(image)


class PEImageTests(unittest.TestCase):
    def test_address_translation(self) -> None:
        image = PEImage(synthetic_pe())
        self.assertEqual(image.image_base, 0x140000000)
        self.assertEqual(image.text.name, ".text")
        self.assertEqual(image.offset_of(0x140001000), 0x200)
        self.assertEqual(image.offset_of(0x14000100F), 0x20F)
        self.assertEqual(image.va_of(0x200), 0x140001000)
        self.assertEqual(image.va_of(0x400), 0x140002000)

    def test_rejects_an_address_outside_every_section(self) -> None:
        image = PEImage(synthetic_pe())
        with self.assertRaises(ValueError):
            image.offset_of(0x150000000)


class AsmTests(unittest.TestCase):
    def test_call_and_jump_displacements(self) -> None:
        asm = win_amd64.Asm(0x1000)
        asm.mov_rax_rsp(0x108)
        asm.call_va(0x2000)
        asm.leave()
        asm.ret()
        code = asm.finish()
        self.assertEqual(code[:8], bytes.fromhex("488b842408010000"))
        self.assertEqual(code[8], 0xE8)
        self.assertEqual(struct.unpack_from("<i", code, 9)[0], 0x2000 - (0x1000 + 13))
        self.assertEqual(code[13:], b"\xc9\xc3")

    def test_short_branch_to_label(self) -> None:
        asm = win_amd64.Asm(0x1000)
        asm.jz("miss")
        asm.ret()
        asm.label("miss")
        asm.ret()
        self.assertEqual(asm.finish(), b"\x74\x01\xc3\xc3")

    def test_cave_is_inside_the_reviewed_padding(self) -> None:
        spec = win_amd64._load_shapes("1.5.9")
        self.assertEqual(spec["text_vsize"], 0x40F62E6)
        self.assertEqual(spec["text_raw_size"], 0x40F6400)
        self.assertGreaterEqual(spec["text_raw_size"] - spec["text_vsize"], win_amd64.CAVE_SIZE)


class ShapeGuardTests(unittest.TestCase):
    def test_reviewed_shapes_are_hex(self) -> None:
        spec = win_amd64._load_shapes("1.5.9")
        self.assertIn("store.(*Store).ContextWindow -> (*Store).ContextWindowChoice", spec["sites"])
        for name, shape in spec["sites"].items():
            self.assertTrue(bytes.fromhex(shape), name)

    def test_every_resolver_site_has_reviewed_bytes(self) -> None:
        spec = win_amd64._load_shapes("1.5.9")
        self.assertEqual(set(spec["sites"]), set(win_amd64.STOCK_SITE_NAMES))

    def test_unknown_version_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            win_amd64._load_shapes("0.0.0")


class ManifestAuthorityTests(unittest.TestCase):
    """The JSON sites, not a duplicate table, decide which stock bytes resolve."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        reviewed = json.loads(win_amd64.SHAPES_PATH.read_text())["v1.5.9"]
        self.reviewed: dict[str, str] = dict(reviewed["sites"])
        self.pe = reviewed_synthetic_pe(self.reviewed)

    def _manifest(self, sites: dict[str, str]) -> pathlib.Path:
        path = self.root / "site_shapes_windows.json"
        path.write_text(
            json.dumps(
                {
                    "v1.5.9": {
                        "text_vsize": 0x1F00,
                        "text_raw_size": 0x2000,
                        "sites": sites,
                    }
                }
            )
        )
        return path

    def _resolve(self, manifest: pathlib.Path) -> tuple:
        with (
            mock.patch.object(win_amd64, "SHAPES_PATH", manifest),
            mock.patch.object(win_amd64.prompt_templates, "resolve_overrides", return_value=()),
        ):
            return win_amd64.resolve_patch_sites(self.pe, "1.5.9", strict=True)

    def test_resolver_consumes_the_manifest_bytes(self) -> None:
        sites = self._resolve(self._manifest(self.reviewed))
        self.assertEqual(len(sites), 2 + len(win_amd64.STOCK_SITE_NAMES))

    def test_mutated_reviewed_byte_is_rejected_by_the_resolver(self) -> None:
        mutated = dict(self.reviewed)
        stock = bytearray.fromhex(mutated[win_amd64.SITE_CW_CHOICE])
        stock[0] ^= 0xFF
        mutated[win_amd64.SITE_CW_CHOICE] = stock.hex()
        with self.assertRaisesRegex(RuntimeError, "stock bytes changed"):
            self._resolve(self._manifest(mutated))

    def test_missing_site_fails_closed(self) -> None:
        missing = dict(self.reviewed)
        del missing[win_amd64.SITE_CHECKPOINT_CEILING]
        with self.assertRaisesRegex(RuntimeError, "missing reviewed stock bytes"):
            self._resolve(self._manifest(missing))

    def test_malformed_site_fails_closed(self) -> None:
        malformed = dict(self.reviewed)
        malformed[win_amd64.SITE_STEP_USER_INPUT] = "zz"
        with self.assertRaisesRegex(RuntimeError, "malformed reviewed stock bytes"):
            self._resolve(self._manifest(malformed))


class LiveBinaryTests(unittest.TestCase):
    """Runs only when AGY_WINDOWS_BINARY points at a real windows/amd64 agy v1.5.9."""

    def test_resolves_every_reviewed_site(self) -> None:
        path = os.environ.get("AGY_WINDOWS_BINARY")
        if not path:
            self.skipTest("set AGY_WINDOWS_BINARY to the downloaded windows/amd64 agy.exe")
        data = pathlib.Path(path).read_bytes()
        sites = win_amd64.resolve_patch_sites(data, "1.5.9", strict=True)
        self.assertGreaterEqual(len(sites), 11)
        self.assertTrue(any(s.domain == "context-window" for s in sites))
        self.assertTrue(any(s.domain == "prompt" for s in sites))


if __name__ == "__main__":
    unittest.main()
