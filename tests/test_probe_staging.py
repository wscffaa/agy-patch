"""Offline tests for rehearsal staging guards and caller-owned work directories.

No test runs a binary, starts a shell, or opens a socket: version detection and the
update-check subprocess are replaced with offline fakes.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from tools import probe_agy


class StageGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        detection = mock.patch.object(probe_agy.patch_agy, "detect_binary_version", return_value="1.5.9")
        detection.start()
        self.addCleanup(detection.stop)

    @property
    def staged(self) -> pathlib.Path:
        return self.root / probe_agy._staged_binary_name()

    def test_windows_staged_name_is_agy_exe(self) -> None:
        with mock.patch.object(probe_agy.os, "name", "nt"):
            self.assertEqual(probe_agy._staged_binary_name(), "agy.exe")

    def test_source_that_is_the_staged_binary_is_never_deleted(self) -> None:
        sentinel = b"clean-source-sentinel"
        source = self.staged
        source.write_bytes(sentinel)
        with self.assertRaisesRegex(RuntimeError, "source itself"):
            probe_agy._stage(source, self.root)
        self.assertTrue(source.is_file())
        self.assertEqual(source.read_bytes(), sentinel)

    def test_hardlink_to_the_source_is_rejected_before_unlinking(self) -> None:
        sentinel = b"linked-source-sentinel"
        source = self.root / "stock.bin"
        source.write_bytes(sentinel)
        try:
            os.link(source, self.staged)
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks are unavailable on this filesystem")
        with self.assertRaisesRegex(RuntimeError, "link to the source"):
            probe_agy._stage(source, self.root)
        self.assertEqual(source.read_bytes(), sentinel)
        self.assertEqual(self.staged.read_bytes(), sentinel)

    def test_rerun_from_this_stages_backup_preserves_the_orig(self) -> None:
        sentinel = b"clean-backup-sentinel"
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        backup.write_bytes(sentinel)
        before = backup.stat()
        binary, returned_backup, version = probe_agy._stage(backup, self.root)
        after = backup.stat()
        self.assertEqual(binary, self.staged)
        self.assertEqual(returned_backup, backup)
        self.assertEqual(version, "1.5.9")
        self.assertEqual(backup.read_bytes(), sentinel)
        self.assertEqual(after.st_ino, before.st_ino)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(binary.read_bytes(), sentinel)

    def test_rerun_accepts_a_previous_stage_hardlinked_to_its_backup(self) -> None:
        sentinel = b"unapplied-stage-sentinel"
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        backup.write_bytes(sentinel)
        try:
            os.link(backup, self.staged)
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks are unavailable on this filesystem")
        binary, returned_backup, _version = probe_agy._stage(backup, self.root)
        self.assertEqual(returned_backup, backup)
        self.assertEqual(backup.read_bytes(), sentinel)
        self.assertEqual(binary.read_bytes(), sentinel)
        self.assertFalse(os.path.samefile(binary, backup))

    def test_symlink_alias_is_rejected_even_for_a_backup_named_source(self) -> None:
        sentinel = b"symlinked-source-sentinel"
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        backup.write_bytes(sentinel)
        try:
            os.symlink(backup, self.staged)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable without extra privileges")
        with self.assertRaisesRegex(RuntimeError, "link to the source"):
            probe_agy._stage(backup, self.root)
        self.assertEqual(backup.read_bytes(), sentinel)
        self.assertTrue(self.staged.is_symlink())

    def test_dangling_backup_symlink_is_rejected_without_creating_its_target(self) -> None:
        source = self.root / "stock.bin"
        source.write_bytes(b"clean-binary-sentinel")
        external = self.root / "external-target.bin"
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        try:
            os.symlink(external, backup)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable without extra privileges")
        self.assertFalse(backup.exists())  # a dangling link is invisible to Path.exists()
        with self.assertRaisesRegex(RuntimeError, "backup .* is a symlink"):
            probe_agy._stage(source, self.root)
        self.assertFalse(external.exists())
        self.assertTrue(backup.is_symlink())

    def test_matching_retained_backup_is_reused_without_a_rewrite(self) -> None:
        sentinel = b"retained-clean-backup"
        source = self.root / "stock.bin"
        source.write_bytes(sentinel)
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        backup.write_bytes(sentinel)
        before = backup.stat()
        _binary, returned_backup, _version = probe_agy._stage(source, self.root)
        after = backup.stat()
        self.assertEqual(returned_backup, backup)
        self.assertEqual(backup.read_bytes(), sentinel)
        self.assertEqual(after.st_ino, before.st_ino)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)

    def test_differing_retained_backup_is_not_overwritten(self) -> None:
        source = self.root / "stock.bin"
        source.write_bytes(b"new clean binary")
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        backup.write_bytes(b"retained older clean backup")
        with self.assertRaisesRegex(RuntimeError, "retained clean backup"):
            probe_agy._stage(source, self.root)
        self.assertEqual(backup.read_bytes(), b"retained older clean backup")

    def test_backup_aliased_to_the_source_is_rejected(self) -> None:
        sentinel = b"aliased-backup-sentinel"
        source = self.root / "stock.bin"
        source.write_bytes(sentinel)
        backup = self.staged.with_name(self.staged.name + ".v1.5.9.orig")
        try:
            os.link(source, backup)
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks are unavailable on this filesystem")
        with self.assertRaisesRegex(RuntimeError, "backup .* is a link to the source"):
            probe_agy._stage(source, self.root)
        self.assertEqual(source.read_bytes(), sentinel)
        self.assertEqual(backup.read_bytes(), sentinel)


class WorkdirOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    @staticmethod
    def _up_to_date(*_args: object, **_kwargs: object) -> mock.Mock:
        return mock.Mock(returncode=0, stdout="installed 1.5.9, latest 1.5.9\n", stderr="")

    def _old_binary(self) -> pathlib.Path:
        old = self.root / "agy.v1.5.9.orig"
        old.write_bytes(b"MZ")
        return old

    def test_caller_supplied_dir_survives_an_up_to_date_check(self) -> None:
        for rehearse in (probe_agy.rehearse, probe_agy.rehearse_windows):
            with self.subTest(rehearse.__name__):
                caller = self.root / f"caller-{rehearse.__name__}"
                caller.mkdir()
                marker = caller / "keep.txt"
                marker.write_text("caller-owned")
                old = self.root / f"old-{rehearse.__name__}"
                old.write_bytes(b"MZ")
                args = (None, old, caller, True) if rehearse is probe_agy.rehearse else (None, old, caller)
                with mock.patch.object(probe_agy.subprocess, "run", side_effect=self._up_to_date):
                    status = rehearse(*args)
                self.assertEqual(status, 0)
                self.assertTrue(marker.is_file())
                self.assertEqual(marker.read_text(), "caller-owned")

    def test_freshly_owned_temp_dir_is_removed_on_up_to_date(self) -> None:
        owned = self.root / "owned-workdir"
        owned.mkdir()
        marker = owned / "temporary"
        marker.write_text("ours")
        with (
            mock.patch.object(probe_agy.tempfile, "mkdtemp", return_value=str(owned)),
            mock.patch.object(probe_agy.subprocess, "run", side_effect=self._up_to_date),
        ):
            status = probe_agy.rehearse(None, self._old_binary(), None, True)
        self.assertEqual(status, 0)
        self.assertFalse(owned.exists())


if __name__ == "__main__":
    unittest.main()
