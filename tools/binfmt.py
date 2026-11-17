#!/usr/bin/env python3
"""Address translation for the two container formats `agy` ships in.

Mach-O maps every section at `VM_BASE + file offset`, so its translation is a
constant. PE maps a file offset to an RVA through the section table and adds the
image base; Go's `pclntab` and `embed.FS` both store absolute VAs, so the two
directions are not symmetric. Every caller that used to write `VM_BASE + offset`
goes through an image here instead.

The classes read the headers once and never mutate the input; the patcher owns
writes.
"""

from __future__ import annotations

import struct
from typing import NamedTuple, Protocol

MACHO_MAGIC_64 = 0xFEEDFACF
MACHO_VM_BASE = 0x100000000

PE_MAGIC = b"PE\0\0"
PE32_MAGIC = 0x10B
PE32_PLUS_MAGIC = 0x20B


class Section(NamedTuple):
    name: str
    header_offset: int
    va: int
    vsize: int
    raw_ptr: int
    raw_size: int


class BinaryImage(Protocol):
    """A loaded image: file offset <-> virtual address in both directions."""

    data: bytes | bytearray

    def offset_of(self, va: int) -> int: ...

    def va_of(self, offset: int) -> int: ...


class MachOImage:
    """`agy`'s Mach-O is mapped at `VM_BASE + file offset`; no section table is needed."""

    def __init__(self, data: bytes | bytearray):
        self.data = data
        if struct.unpack_from("<I", data, 0)[0] != MACHO_MAGIC_64:
            raise RuntimeError("not a 64-bit Mach-O image")

    def offset_of(self, va: int) -> int:
        offset = va - MACHO_VM_BASE
        if not 0 <= offset < len(self.data):
            raise ValueError(f"{va:#x} is outside the image")
        return offset

    def va_of(self, offset: int) -> int:
        if not 0 <= offset < len(self.data):
            raise ValueError(f"file offset {offset:#x} is outside the image")
        return MACHO_VM_BASE + offset


class PEImage:
    """A PE32/PE32+ image with section-table address translation."""

    def __init__(self, data: bytes | bytearray):
        self.data = data
        if data[:2] != b"MZ":
            raise RuntimeError("not a PE image (missing MZ header)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] != PE_MAGIC:
            raise RuntimeError("not a PE image (missing PE signature)")
        self.pe_offset = pe
        self.machine, section_count = struct.unpack_from("<HH", data, pe + 4)
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        self.optional_offset = optional
        self.optional_magic = struct.unpack_from("<H", data, optional)[0]
        if self.optional_magic == PE32_PLUS_MAGIC:
            self.image_base = struct.unpack_from("<Q", data, optional + 24)[0]
            self.data_directory_offset = optional + 112
            self.checksum_offset = optional + 64
            self.dll_characteristics_offset = optional + 70
        elif self.optional_magic == PE32_MAGIC:
            self.image_base = struct.unpack_from("<I", data, optional + 28)[0]
            self.data_directory_offset = optional + 96
            self.checksum_offset = optional + 64
            self.dll_characteristics_offset = optional + 70
        else:
            raise RuntimeError(f"unsupported PE optional-header magic {self.optional_magic:#x}")

        self.sections: list[Section] = []
        section_offset = optional + optional_size
        for index in range(section_count):
            header = section_offset + index * 40
            name = bytes(data[header : header + 8]).rstrip(b"\0").decode("ascii", "replace")
            vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, header + 8)
            self.sections.append(Section(name, header, va, vsize, raw_ptr, raw_size))

        text = self.section(".text")
        if text is None:
            raise RuntimeError("PE image has no .text section")
        self.text = text

    def section(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    def offset_of(self, va: int) -> int:
        rva = va - self.image_base
        for section in self.sections:
            if section.va <= rva < section.va + max(section.vsize, section.raw_size):
                delta = rva - section.va
                if delta >= section.raw_size:
                    raise ValueError(f"{va:#x} lies in the zero-filled tail of {section.name}")
                return section.raw_ptr + delta
        raise ValueError(f"{va:#x} is outside every PE section")

    def va_of(self, offset: int) -> int:
        for section in self.sections:
            if section.raw_ptr <= offset < section.raw_ptr + section.raw_size:
                return self.image_base + section.va + (offset - section.raw_ptr)
        raise ValueError(f"file offset {offset:#x} is outside every PE section")


def detect_image(data: bytes | bytearray) -> MachOImage | PEImage:
    """Pick the container from its first bytes; both `agy` builds are little-endian 64-bit."""
    if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == MACHO_MAGIC_64:
        return MachOImage(data)
    if data[:2] == b"MZ":
        return PEImage(data)
    raise RuntimeError("unrecognized agy binary format (expected 64-bit Mach-O or PE)")


def is_pe(data: bytes | bytearray) -> bool:
    return data[:2] == b"MZ"
