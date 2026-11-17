#!/usr/bin/env python3
"""Locate agy's embedded system prompt templates and reconcile them with `templates/`.

Each `embed.FS` file entry stores the name and contents as Go strings:
(name VA, name len, data VA, data len). The name string's VA plus its length is
a unique 16-byte key into the entry table, which yields the template's bytes.

`templates/v<version>/system_prompts/` mirrors every system prompt template of that
agy release and is the desired state: a file identical to Google's stays untouched,
an empty file drops its section, and any other file is written into the template's
slot, padded with a Go comment. The version comes from the binary itself, so a
release without its own directory is refused rather than patched with stale text.

`templates/v<version>/stock/` holds Google's originals for that release, byte for byte.
Patching from a clean backup stops unless every binary template equals its stock/ copy,
and `prompt_overrides.json` must give a `reason` for every file that differs from stock.

Run directly to print one template, or dump every embedded template:
    python3 tools/prompt_templates.py identity.tmpl [--binary ~/.local/bin/agy.v1.5.3.orig]
    python3 tools/prompt_templates.py --dump $TMPDIR/templates --binary ~/.local/bin/agy.v1.5.3.orig
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
from typing import NamedTuple

# `python tools/prompt_templates.py` puts only tools/ on sys.path; `python -I`
# puts neither tools/ nor the repository there. Add the repository explicitly so
# the script works both ways and as `tools.prompt_templates` after a normal import.
REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.binfmt import PEImage, detect_image

VM_BASE = 0x100000000  # Mach-O compatibility alias; address translation goes through detect_image()
TEMPLATE_ROOT = b"google3/third_party/jetski/prompt/template_provider/templates/"
TEMPLATE_DIR = TEMPLATE_ROOT + b"system_prompts/"
TEMPLATES_ROOT = REPO / "templates"  # one v<version>/ directory per agy release


class TemplateSlot(NamedTuple):
    name: str
    offset: int
    content: bytes


class Override(NamedTuple):
    name: str     # relative to system_prompts/, e.g. "helpers/async_termination_rule.tmpl"
    action: str   # "blank", "replace", or "restore" (live slot drifted from stock)
    slot: TemplateSlot
    patched: bytes
    original: bytes | None  # stock bytes; None when the slot is not stock, so only the backup can revert


def find_template(data: bytes | bytearray, name: str, image=None) -> TemplateSlot:
    image = image or detect_image(data)
    path = TEMPLATE_DIR + name.encode()
    entries = []
    pos = data.find(path)
    while pos != -1:
        entry = data.find(struct.pack("<QQ", image.va_of(pos), len(path)))
        if entry != -1:
            entries.append(entry)
        pos = data.find(path, pos + 1)
    if len(entries) != 1:
        raise RuntimeError(f"Expected one embed.FS entry for {name}, found {len(entries)}")
    data_va, data_len = struct.unpack_from("<QQ", data, entries[0] + 16)
    offset = image.offset_of(data_va)
    content = bytes(data[offset : offset + data_len])
    if b"\x00" in content:
        raise RuntimeError(f"embed.FS entry for {name} does not point at template text")
    return TemplateSlot(name, offset, content)


def iter_templates(data: bytes | bytearray, image=None) -> list[TemplateSlot]:
    """Every file in the template `embed.FS`, walked outward from identity.tmpl's 48-byte entry."""
    image = image or detect_image(data)
    anchor = find_template(data, "identity.tmpl", image)
    anchor_name = TEMPLATE_DIR + b"identity.tmpl"
    first = data.find(
        struct.pack("<QQQ", image.va_of(data.find(anchor_name)), len(anchor_name), image.va_of(anchor.offset))
    )
    slots = []
    for step in (-48, 48):
        entry = first if step > 0 else first - 48
        while True:
            name_va, name_len, data_va, data_len = struct.unpack_from("<QQQQ", data, entry)
            if not 0 < name_len < 512:
                break
            try:
                name_offset = image.offset_of(name_va)
            except ValueError:
                break
            name = bytes(data[name_offset : name_offset + name_len])
            if not name.startswith(TEMPLATE_ROOT):
                break
            if data_len:
                data_offset = image.offset_of(data_va)
                content = bytes(data[data_offset : data_offset + data_len])
                slots.append(TemplateSlot(name[len(TEMPLATE_ROOT):].decode(), data_offset, content))
            entry += step
    return sorted(slots)


def comment_padding(length: int) -> bytes:
    """`length` bytes that render to nothing; spaces when too short for a Go comment."""
    if length < 12:
        return b" " * length
    return b"{{- /*" + b" " * (length - 12) + b"*/ -}}"


def fill_slot(name: str, text: bytes, slot_length: int) -> bytes:
    """`text` padded to exactly `slot_length` bytes; empty text blanks the slot."""
    if len(text) > slot_length:
        raise RuntimeError(f"{name}: replacement is {len(text)}B but the slot holds {slot_length}B")
    if not text and slot_length < 12:
        raise RuntimeError(f"{name}: slot too small to blank ({slot_length}B)")
    return text + comment_padding(slot_length - len(text))


def version_dir(version: str) -> pathlib.Path:
    path = TEMPLATES_ROOT / f"v{version}"
    if not path.is_dir():
        raise RuntimeError(
            f"No templates/v{version}/ for agy v{version}. Create it: dump the new stock templates "
            f"(tools/prompt_templates.py --dump templates/v{version}/stock --binary <new .orig>), copy the previous "
            f"version's system_prompts/ and prompt_overrides.json, and review each changed file against stock/."
        )
    return path


def resolve_overrides(data: bytes | bytearray, version: str, strict: bool = False, image=None) -> list[Override]:
    """The slots that `templates/v<version>/system_prompts/` changes from `stock/`.

    `strict` (patching from a clean backup) demands every slot equal its `stock/` copy.
    Otherwise (inspecting a live binary) a slot that is neither stock nor patched is
    reported with `original=None`, which shows up as an unknown site state.

    The checked-in stock/ and system_prompts/ trees may use LF or CRLF (Git
    autocrlf on Windows rewrites them), while each binary embeds one of the two.
    Normalize both sides to the slot's own newline before comparing and filling.
    """
    image = image or detect_image(data)

    def normalize(blob: bytes, newline: bytes) -> bytes:
        return blob.replace(b"\r\n", b"\n").replace(b"\n", newline)

    root = version_dir(version)
    desired_dir, stock_dir = root / "system_prompts", root / "stock/system_prompts"
    manifest = root / "prompt_overrides.json"
    reasons = json.loads(manifest.read_text()).get("templates", {}) if manifest.exists() else {}
    files = sorted(p.relative_to(desired_dir).as_posix() for p in desired_dir.rglob("*.tmpl"))
    stock_files = sorted(p.relative_to(stock_dir).as_posix() for p in stock_dir.rglob("*.tmpl"))
    if files != stock_files:
        raise RuntimeError(f"{desired_dir} and {stock_dir} list different templates: {sorted(set(files) ^ set(stock_files))}")

    overrides, changed = [], set()
    for name in files:
        slot = find_template(data, name, image)
        newline = b"\r\n" if b"\r\n" in slot.content else b"\n"
        desired = normalize((desired_dir / name).read_bytes(), newline)
        stock = normalize((stock_dir / name).read_bytes(), newline)
        if strict and slot.content != stock:
            raise RuntimeError(
                f"{name}: the binary's template differs from {stock_dir / name}. This stock/ copy is not from this "
                f"binary; re-dump stock/ from the matching .orig and review system_prompts/{name} against it."
            )
        if desired == stock:
            if slot.content != stock:  # live slot drifted from stock; only the backup restores it
                overrides.append(Override(name, "restore", slot, stock, None))
            continue
        changed.add(name)
        patched = fill_slot(name, desired.rstrip(b"\r\n"), len(slot.content))
        action = "blank" if not desired.strip() else "replace"
        overrides.append(Override(name, action, slot, patched, stock if slot.content == stock else None))

    if missing := sorted(n for n in changed if not reasons.get(n, {}).get("reason")):
        raise RuntimeError(f"Changed templates need a `reason` in {manifest}: {missing}")
    if stale := sorted(set(reasons) - changed):
        raise RuntimeError(f"{manifest} gives reasons for templates that match stock: {stale}")
    return overrides


def main() -> int:
    ap = argparse.ArgumentParser(description="Print or dump the templates embedded in an agy binary.")
    ap.add_argument("name", nargs="?", help="System prompt template to print, e.g. identity.tmpl")
    ap.add_argument("--dump", type=pathlib.Path, metavar="DIR", help="Write every embedded template under DIR")
    default_binary = pathlib.Path.home() / ".local/bin/agy"
    if os.name == "nt":
        default_binary = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "agy/bin/agy.exe"
    ap.add_argument("--binary", type=pathlib.Path, default=default_binary)
    args = ap.parse_args()
    data = args.binary.read_bytes()
    if args.dump:
        for slot in iter_templates(data):
            dest = args.dump / slot.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(slot.content)
            print(f"{len(slot.content):6,}  {slot.name}")
    elif args.name:
        print(find_template(data, args.name).content.decode())
    else:
        ap.error("give a template name or --dump DIR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
