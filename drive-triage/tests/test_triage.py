"""End-to-end and unit tests over synthetic fixture drives.

Run from the drive-triage directory:
    python -m unittest discover -s tests -v
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from triage import cli
from triage.util import (
    CLASSIFY_COLUMNS, HASH_COLUMNS, INVENTORY_COLUMNS, MANIFEST_COLUMNS,
    guard_output_dirs, read_csv_rows,
)
from triage.classify import (
    detect_boxes, parse_date_from_name, propose_record_name,
)
from triage.volumes import default_in_scope
import fixtures


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(list(argv))
    return rc, buf.getvalue()


def rows_by_path(csv_path, columns):
    return {r["path"]: r for r in read_csv_rows(csv_path, columns)}


class PipelineTest(unittest.TestCase):
    """Build fixtures once, run the whole pipeline once, assert everything."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="triage-test-")
        cls.e = os.path.join(cls.base, "driveE")
        cls.f = os.path.join(cls.base, "driveF")
        cls.d = os.path.join(cls.base, "driveD")
        cls.out = os.path.join(cls.base, "out")
        cls.logs = os.path.join(cls.base, "logs")
        fixtures.build_drive_e(cls.e)
        fixtures.build_drive_f(cls.f)
        cls.dref_path, cls.dref_sha = fixtures.build_d_reference(
            cls.d, os.path.join(cls.base, "d-inventory.csv"))
        cls.common = ["--drive", cls.e, "--drive", cls.f,
                      "--output-dir", cls.out, "--log-dir", cls.logs,
                      "--d-reference", os.path.join(cls.base,
                                                    "d-inventory.csv")]
        for cmd in ("inventory", "hash", "classify", "report"):
            rc, _ = run_cli(cmd, *cls.common)
            assert rc == 0, f"{cmd} failed"
        cls.ce = rows_by_path(
            os.path.join(cls.out, "classify", "classify-driveE.csv"),
            CLASSIFY_COLUMNS)
        cls.cf = rows_by_path(
            os.path.join(cls.out, "classify", "classify-driveF.csv"),
            CLASSIFY_COLUMNS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def epath(self, rel):
        return os.path.join(self.e, *rel.split("/"))

    def fpath(self, rel):
        return os.path.join(self.f, *rel.split("/"))

    def erow(self, rel):
        row = self.ce.get(self.epath(rel))
        self.assertIsNotNone(row, f"no classify row for {rel}")
        return row

    # -- phase 1 ------------------------------------------------------------

    def test_inventory_complete_and_marked_done(self):
        inv = rows_by_path(
            os.path.join(self.out, "inventory", "inventory-driveE.csv"),
            INVENTORY_COLUMNS)
        disk_count = sum(len(fs) for _, _, fs in os.walk(self.e))
        self.assertEqual(len(inv), disk_count)
        self.assertTrue(os.path.exists(
            os.path.join(self.out, "inventory", "inventory-driveE.done")))

    def test_unique_size_file_never_hashed(self):
        for slug in ("driveE", "driveF"):
            p = os.path.join(self.out, "hashes", f"prefix-{slug}.csv")
            for row in read_csv_rows(p, HASH_COLUMNS):
                self.assertNotIn("sentinel.bin", row["path"])

    def test_same_size_different_prefix_not_fully_hashed(self):
        fulls = []
        for slug in ("driveE", "driveF"):
            p = os.path.join(self.out, "hashes", f"full-{slug}.csv")
            if os.path.exists(p):
                fulls.extend(r["path"] for r in read_csv_rows(p, HASH_COLUMNS))
        joined = "\n".join(fulls)
        self.assertNotIn("bigA.bin", joined)
        self.assertNotIn("bigB.bin", joined)
        # but the engineered pair DID make it through the prefix stage
        pre = rows_by_path(
            os.path.join(self.out, "hashes", "prefix-driveE.csv"),
            HASH_COLUMNS)
        self.assertIn(self.epath("pair/bigA.bin"), pre)

    # -- dupes --------------------------------------------------------------

    def test_exact_dupe_of_d(self):
        row = self.erow("stuff/dref.bin")
        self.assertEqual(row["class"], "EXACT_DUPE_OF_D")
        self.assertIn("dref.bin", row["dupe_of"])

    def test_within_drive_dupe_one_keeper(self):
        a = self.erow("stuff/dup1.bin")
        b = self.erow("stuff/copies/dup1 copy.bin")
        classes = sorted([a["class"], b["class"]])
        self.assertIn("DUPE_EXTERNAL", classes)
        self.assertNotEqual(a["class"], b["class"],
                            "exactly one copy must be the keeper")
        keeper = a if b["class"] == "DUPE_EXTERNAL" else b
        self.assertIn("elected keeper", keeper["evidence"])

    def test_cross_drive_dupe(self):
        e = self.erow("stuff/xdup.bin")
        f = self.cf.get(self.fpath("transfer/xdup.bin"))
        self.assertIsNotNone(f)
        classes = sorted([e["class"], f["class"]])
        self.assertIn("DUPE_EXTERNAL", classes)
        self.assertNotEqual(e["class"], f["class"])

    # -- media --------------------------------------------------------------

    def test_active_client_media_goes_fastwork(self):
        row = self.erow("Shoots/2023 Acme Rebrand/RAW/A001.CR2")
        self.assertEqual(row["class"], "MEDIA")
        self.assertEqual(row["nas_tier"], "fastwork")
        self.assertTrue(row["proposed_path"].startswith(
            "2023 Acme Rebrand\\01_RAW"), row["proposed_path"])

    def test_export_maps_to_deliverables(self):
        row = self.erow("Shoots/2023 Acme Rebrand/Exports/final_v2.mp4")
        self.assertEqual(row["nas_tier"], "fastwork")
        self.assertIn("04_DELIVERABLES", row["proposed_path"])

    def test_personal_shoot_not_year_filed(self):
        row = self.erow("Family/Vacation 2019/IMG_1001.JPG")
        self.assertEqual(row["class"], "MEDIA")
        self.assertEqual(row["subclass"], "personal-shoot")
        self.assertTrue(row["proposed_path"].startswith(
            "Media\\Personal Shoots\\Vacation 2019"), row["proposed_path"])
        self.assertEqual(row["nas_tier"], "hdd-mirror")

    def test_legacy_media_year_filed_on_mirror(self):
        row = self.cf.get(self.fpath("2020 Beach Shoot/clip.mov"))
        self.assertEqual(row["class"], "MEDIA")
        self.assertEqual(row["nas_tier"], "hdd-mirror")
        self.assertTrue(row["proposed_path"].startswith("Media\\2020\\"),
                        row["proposed_path"])

    # -- records ------------------------------------------------------------

    def test_invoice_renamed_to_convention(self):
        row = self.erow("paperwork/invoice_2023-04-15_acme_$1200.pdf")
        self.assertEqual(row["class"], "RECORDS")
        self.assertIn("Records\\Business\\Invoices", row["proposed_path"])
        self.assertTrue(row["proposed_name"].startswith("2023-04-15  "),
                        row["proposed_name"])
        self.assertIn("$1200", row["proposed_name"])
        self.assertTrue(row["proposed_name"].endswith(".pdf"))

    def test_scanned_receipt_is_record_not_media(self):
        row = self.erow("paperwork/scan receipt 20220301.jpg")
        self.assertEqual(row["class"], "RECORDS")
        self.assertIn("Expenses", row["proposed_path"])
        self.assertTrue(row["proposed_name"].startswith("2022-03-01"))

    def test_uncategorized_doc_goes_to_inbox_low_confidence(self):
        row = self.erow("docs/randomnotes.txt")
        self.assertEqual(row["class"], "RECORDS")
        self.assertIn("_Inbox", row["proposed_path"])
        self.assertEqual(row["confidence"], "low")

    # -- archive boxes ------------------------------------------------------

    def test_backup_box_intact_with_sole_survivor(self):
        row = self.erow("OldLaptopBackup/Users/jason/Documents/letter.doc")
        self.assertEqual(row["class"], "ARCHIVE_BOX")
        self.assertIn("sole-surviving", row["evidence"])
        self.assertTrue(row["proposed_path"].startswith("Archive\\"))
        self.assertEqual(row["nas_tier"], "hdd-mirror")

    def test_appdata_inside_box_never_silently_junked(self):
        row = self.erow("OldLaptopBackup/Users/jason/AppData/Local/junk.dat")
        self.assertEqual(row["class"], "ARCHIVE_BOX")
        self.assertIn("sole survivor", row["evidence"])

    def test_version_store_detected_as_box(self):
        row = self.erow(
            "SomeFolder/History/report (2019_03_22 18_30_00 UTC).docx")
        self.assertEqual(row["class"], "ARCHIVE_BOX")

    # -- junk ---------------------------------------------------------------

    def test_junk_patterns_with_evidence(self):
        cases = {
            "Downloads/setup_v1.2.3_x64.exe": "installer",
            "cache/tempfile.tmp": "temp",
            "photos-misc/Thumbs.db": "os-litter",
            "empty.txt": "zero-byte",
        }
        for rel, kind in cases.items():
            row = self.erow(rel)
            self.assertEqual(row["class"], "JUNK", rel)
            self.assertEqual(row["subclass"], kind, rel)
            self.assertTrue(row["evidence"], f"junk needs evidence: {rel}")

    # -- review-driven regressions ------------------------------------------

    def test_keeper_of_dupe_group_never_junked(self):
        cache_copy = self.erow("cache/dupJ.bin")
        kept_copy = self.erow("keep/dupJ.bin")
        self.assertEqual(cache_copy["class"], "DUPE_EXTERNAL")
        self.assertNotIn(kept_copy["class"], ("JUNK", "DUPE_EXTERNAL"))
        self.assertIn("keeper", kept_copy["evidence"])

    def test_os_metadata_is_junk_not_unknown(self):
        for rel in (".Spotlight-V100/Store-V2/ABC/0.indexHead",
                    ".Spotlight-V100/VolumeConfiguration.plist",
                    ".fseventsd/00000000018a4e52"):
            row = self.erow(rel)
            self.assertEqual(row["class"], "JUNK", rel)
            self.assertEqual(row["subclass"], "os-metadata", rel)
        row = self.erow(".dropbox.device")
        self.assertEqual(row["class"], "JUNK")

    def test_box_straddling_dupe_flagged_for_review_not_deleted(self):
        box_copy = self.erow("OldLaptopBackup/Pers/00010.MTS")
        self.assertEqual(box_copy["class"], "ARCHIVE_BOX")
        self.assertIn("DUPE-OUTSIDE-BOX", box_copy["evidence"])
        self.assertIn("Pers", box_copy["dupe_of"])
        # the pair appears in the manual-review CSV
        review = list(read_csv_rows(
            os.path.join(self.out, "manifests",
                         "box-straddle-review-driveE.csv"),
            ["box_name", "box_copy", "outside_copy", "size", "evidence"]))
        self.assertTrue(any("00010.MTS" in r["box_copy"] and
                            "00010.MTS" in r["outside_copy"] for r in review))
        # and the report names it
        with open(os.path.join(self.out, "reports", "report-driveE.md"),
                  encoding="utf-8") as fh:
            self.assertIn("MANUAL REVIEW", fh.read())

    def test_media_in_temp_dir_not_junk(self):
        row = self.erow("temp/real_footage.mov")
        self.assertEqual(row["class"], "MEDIA")

    def test_personnel_not_personal(self):
        row = self.erow("Shoots/2022 Personnel Training/video.mp4")
        self.assertEqual(row["class"], "MEDIA")
        self.assertNotEqual(row["subclass"], "personal-shoot")

    def test_fastwork_same_names_do_not_collide(self):
        a = self.erow("Shoots/2023 Acme Rebrand/RAW/card1/A002.CR2")
        b = self.erow("Shoots/2023 Acme Rebrand/RAW/card2/A002.CR2")
        self.assertNotEqual(a["proposed_path"], b["proposed_path"])
        self.assertTrue(a["proposed_path"].startswith(
            "2023 Acme Rebrand\\01_RAW"), a["proposed_path"])

    def test_copy_number_files_do_not_create_box(self):
        row = self.erow("Stuff2/History/photo (1).jpg")
        self.assertNotEqual(row["class"], "ARCHIVE_BOX")

    def test_box_path_does_not_duplicate_box_level(self):
        row = self.erow("OldLaptopBackup/Users/jason/Documents/letter.doc")
        self.assertEqual(row["proposed_path"],
                         "Archive\\OldLaptopBackup\\Users\\jason\\Documents")

    def test_loose_root_file_classified(self):
        row = self.erow("LooseClip.mov")
        self.assertEqual(row["class"], "MEDIA")
        self.assertEqual(row["confidence"], "low")

    def test_manifest_actions_match_class(self):
        expected = {"MEDIA": "copy", "RECORDS": "copy", "ARCHIVE_BOX": "copy",
                    "UNKNOWN": "hold", "JUNK": "delete-candidate",
                    "EXACT_DUPE_OF_D": "delete-candidate",
                    "DUPE_EXTERNAL": "delete-candidate"}
        for r in read_csv_rows(
                os.path.join(self.out, "manifests", "manifest-driveE.csv"),
                MANIFEST_COLUMNS):
            self.assertEqual(r["action"], expected[r["class"]], r["class"])

    # -- unknown / repos ----------------------------------------------------

    def test_git_repo_grouped_unknown(self):
        for rel in ("code/myproj/src/main.py", "code/myproj/.git/config"):
            row = self.erow(rel)
            self.assertEqual(row["class"], "UNKNOWN", rel)
            self.assertEqual(row["subclass"], "git-repo", rel)

    def test_unrecognized_extension_unknown(self):
        row = self.erow("weird/data.xyz")
        self.assertEqual(row["class"], "UNKNOWN")

    # -- deliverables -------------------------------------------------------

    def test_reports_exist(self):
        for name in ("report-driveE.md", "report-driveF.md",
                     "master-plan.md", "decision-list.md"):
            p = os.path.join(self.out, "reports", name)
            self.assertTrue(os.path.exists(p), name)
            self.assertGreater(os.path.getsize(p), 100, name)

    def test_manifest_covers_every_classified_file(self):
        for slug, classified in (("driveE", self.ce), ("driveF", self.cf)):
            man = {r["source_path"]: r for r in read_csv_rows(
                os.path.join(self.out, "manifests", f"manifest-{slug}.csv"),
                MANIFEST_COLUMNS)}
            self.assertEqual(set(man), set(classified))
            for r in man.values():
                self.assertIn(r["action"],
                              ("copy", "hold", "delete-candidate"))

    def test_decision_list_contains_ambiguities(self):
        with open(os.path.join(self.out, "reports", "decision-list.md"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("git-repo", text)
        self.assertIn("- **D1**", text)

    def test_nothing_written_to_scanned_drives(self):
        for root, builder in ((self.e, fixtures.build_drive_e),
                              (self.f, fixtures.build_drive_f)):
            with tempfile.TemporaryDirectory() as ref:
                builder(ref)
                actual = {os.path.relpath(os.path.join(dp, f), root)
                          for dp, _, fs in os.walk(root) for f in fs}
                expect = {os.path.relpath(os.path.join(dp, f), ref)
                          for dp, _, fs in os.walk(ref) for f in fs}
                self.assertEqual(actual, expect,
                                 f"triage modified scanned drive {root}")


class ResumeTest(unittest.TestCase):
    def test_inventory_resumes_to_identical_set(self):
        with tempfile.TemporaryDirectory() as base:
            e = os.path.join(base, "driveE")
            fixtures.build_drive_e(e)
            out1, out2 = os.path.join(base, "o1"), os.path.join(base, "o2")
            logs = os.path.join(base, "logs")
            # interrupted run: 5 files at a time until done
            for _ in range(40):
                run_cli("inventory", "--drive", e, "--output-dir", out1,
                        "--log-dir", logs, "--max-files", "5")
                if os.path.exists(os.path.join(
                        out1, "inventory", "inventory-driveE.done")):
                    break
            # simulate a torn final line from a crash mid-append
            csv1 = os.path.join(out1, "inventory", "inventory-driveE.csv")
            with open(csv1, "a", encoding="utf-8") as fh:
                fh.write("half,a,row")
            run_cli("inventory", "--drive", e, "--output-dir", out1,
                    "--log-dir", logs)
            # clean one-shot run for comparison
            run_cli("inventory", "--drive", e, "--output-dir", out2,
                    "--log-dir", logs)
            s1 = set(rows_by_path(csv1, INVENTORY_COLUMNS))
            s2 = set(rows_by_path(
                os.path.join(out2, "inventory", "inventory-driveE.csv"),
                INVENTORY_COLUMNS))
            self.assertEqual(s1, s2)


class UnreadableDirTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0,
                     "needs POSIX chmod as non-root")
    def test_permission_denied_dir_recorded_and_scan_completes(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "driveP")
            os.makedirs(os.path.join(root, "locked"))
            with open(os.path.join(root, "ok.txt"), "wb") as fh:
                fh.write(b"readable")
            with open(os.path.join(root, "locked", "hidden.txt"), "wb") as fh:
                fh.write(b"unreadable")
            os.chmod(os.path.join(root, "locked"), 0o000)
            out = os.path.join(base, "out")
            try:
                run_cli("inventory", "--drive", root, "--output-dir", out,
                        "--log-dir", os.path.join(base, "logs"))
                # completes despite the locked dir
                self.assertTrue(os.path.exists(os.path.join(
                    out, "inventory", "inventory-driveP.done")))
                rows = rows_by_path(
                    os.path.join(out, "inventory", "inventory-driveP.csv"),
                    INVENTORY_COLUMNS)
                locked = rows.get(os.path.join(root, "locked"))
                self.assertIsNotNone(locked, "locked dir must be recorded")
                self.assertIn("access denied", locked["error"])
            finally:
                os.chmod(os.path.join(root, "locked"), 0o700)


class CircuitBreakerTest(unittest.TestCase):
    def test_permission_errors_never_trip_breaker(self):
        from triage.hashing import _CircuitBreaker
        b = _CircuitBreaker("F:\\", "prefix-hash")
        for _ in range(500):  # far past the trip threshold
            b.failure(PermissionError(13, "Access is denied"))
        self.assertEqual(b.denied, 500)
        self.assertEqual(b.consecutive, 0)

    def test_device_errors_still_trip_breaker(self):
        from triage.hashing import _CircuitBreaker
        b = _CircuitBreaker("F:\\", "prefix-hash")
        with self.assertRaises(SystemExit):
            for _ in range(100):
                b.failure(OSError(5, "I/O error"))


class RefreshTest(unittest.TestCase):
    """A completed inventory is append-only, so deletions are invisible
    until --refresh re-walks the file list."""

    def test_refresh_drops_deleted_files_and_their_hashes(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "driveR")
            out = os.path.join(base, "out")
            logs = os.path.join(base, "logs")
            os.makedirs(root)
            # two identical files so both get hashed, plus a third
            payload = b"identical payload " * 5000
            for rel in ("keep.bin", "gone.bin"):
                with open(os.path.join(root, rel), "wb") as fh:
                    fh.write(payload)
            common = ["--drive", root, "--output-dir", out, "--log-dir", logs]
            for cmd in ("inventory", "hash"):
                run_cli(cmd, *common)
            inv = os.path.join(out, "inventory", "inventory-driveR.csv")
            self.assertEqual(len(rows_by_path(inv, INVENTORY_COLUMNS)), 2)

            os.remove(os.path.join(root, "gone.bin"))

            # without --refresh the deletion is not noticed
            run_cli("inventory", *common)
            self.assertEqual(len(rows_by_path(inv, INVENTORY_COLUMNS)), 2)

            # with --refresh it is, and the stale hash row goes too
            run_cli("inventory", "--refresh", *common)
            after = rows_by_path(inv, INVENTORY_COLUMNS)
            self.assertEqual(len(after), 1)
            self.assertIn(os.path.join(root, "keep.bin"), after)
            run_cli("hash", "--refresh", *common)
            hashed = list(read_csv_rows(
                os.path.join(out, "hashes", "prefix-driveR.csv"),
                HASH_COLUMNS))
            self.assertTrue(all("gone.bin" not in r["path"] for r in hashed))
            self.assertTrue(any("keep.bin" in r["path"] for r in hashed))


class UnreadableDirToleranceTest(unittest.TestCase):
    """A NAS #recycle folder that errors on enumeration must not block the
    whole share from completing - but a share that has actually gone away
    still must."""

    def _run_with_failing_scandir(self, base, root, fails, err):
        import logging
        from triage import inventory
        real = os.scandir

        def fake(path):
            if any(f in str(path) for f in fails):
                raise err
            return real(path)

        cfg = {"output_dir": os.path.join(base, "out"),
               "follow_symlinks": False}
        log = logging.getLogger("udt")
        log.addHandler(logging.NullHandler())
        real_sleep = inventory.time.sleep
        os.scandir = fake
        inventory.time.sleep = lambda _s: None   # skip retry backoff
        try:
            return inventory.run_inventory(cfg, root, log)
        finally:
            os.scandir = real
            inventory.time.sleep = real_sleep

    def test_one_bad_directory_still_completes(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "share")
            os.makedirs(os.path.join(root, "#recycle"))
            os.makedirs(os.path.join(root, "2024"))
            with open(os.path.join(root, "2024", "photo.jpg"), "wb") as fh:
                fh.write(b"jpeg")
            self._run_with_failing_scandir(
                base, root, ["#recycle"],
                OSError(59, "An unexpected network error occurred"))
            done = os.path.join(base, "out", "inventory",
                                "inventory-share.done")
            self.assertTrue(os.path.exists(done),
                            "one bad folder must not block completion")
            rows = rows_by_path(
                os.path.join(base, "out", "inventory", "inventory-share.csv"),
                INVENTORY_COLUMNS)
            self.assertIn(os.path.join(root, "2024", "photo.jpg"), rows)
            bad = rows.get(os.path.join(root, "#recycle"))
            self.assertIsNotNone(bad, "bad folder must be recorded")
            self.assertIn("NOT scanned", bad["error"])

    def test_widespread_failure_still_aborts(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "share2")
            for i in range(40):
                os.makedirs(os.path.join(root, f"dir{i}"))
            with self.assertRaises(SystemExit) as ctx:
                self._run_with_failing_scandir(
                    base, root, ["dir"],
                    OSError(59, "An unexpected network error occurred"))
            self.assertIn("disconnected", str(ctx.exception))


class DRefWithoutHashesTest(unittest.TestCase):
    def test_probable_dupe_flagged_and_hash_request_written(self):
        with tempfile.TemporaryDirectory() as base:
            e = os.path.join(base, "driveE")
            d = os.path.join(base, "driveD")
            out = os.path.join(base, "out")
            logs = os.path.join(base, "logs")
            fixtures.build_drive_e(e)
            ref = os.path.join(base, "d-nohash.csv")
            fixtures.build_d_reference(d, ref, with_hashes=False)
            common = ["--drive", e, "--output-dir", out, "--log-dir", logs,
                      "--d-reference", ref]
            for cmd in ("inventory", "hash", "classify"):
                rc, _ = run_cli(cmd, *common)
                self.assertEqual(rc, 0)
            rows = rows_by_path(
                os.path.join(out, "classify", "classify-driveE.csv"),
                CLASSIFY_COLUMNS)
            row = rows[os.path.join(e, "stuff", "dref.bin")]
            self.assertNotEqual(row["class"], "EXACT_DUPE_OF_D")
            self.assertIn("PROBABLE dupe of D:", row["evidence"])
            self.assertEqual(row["confidence"], "low")
            self.assertTrue(os.path.exists(
                os.path.join(out, "d-hash-request.csv")))


class DRefHeaderStyleTest(unittest.TestCase):
    def test_pascalcase_headers_recognized(self):
        """PowerShell-exported inventories use PascalCase with no separators
        (FullName/SizeBytes); these must map to path/size like snake_case."""
        import logging
        from triage.dupes import DReference
        for header in ("FullName,SizeBytes", "full_name,size_bytes",
                       "Full Name,Size Bytes", "PATH,LENGTH"):
            with tempfile.TemporaryDirectory() as base:
                p = os.path.join(base, "d.csv")
                with open(p, "w", newline="", encoding="utf-8") as fh:
                    fh.write(header + "\n")
                    fh.write("D:\\Data\\a.jpg,102400\n")
                ref = DReference.load(p, logging.getLogger("t"))
                self.assertEqual(ref.row_count, 1, header)
                self.assertTrue(ref.has_size(102400), header)


class GuardTest(unittest.TestCase):
    def test_output_inside_scan_root_refused(self):
        with self.assertRaises(SystemExit):
            guard_output_dirs({
                "scan_roots": ["/mnt/ext1"],
                "output_dir": "/mnt/ext1/triage-out",
                "log_dir": "/tmp/logs",
            })

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks here")
    def test_symlink_alias_of_scan_root_refused(self):
        # an aliased spelling of the scan root must not slip past the guard
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "realroot")
            os.makedirs(root)
            alias = os.path.join(base, "alias")
            os.symlink(root, alias)
            with self.assertRaises(SystemExit):
                guard_output_dirs({
                    "scan_roots": [root],
                    "output_dir": os.path.join(alias, "out"),
                    "log_dir": os.path.join(base, "logs"),
                })

    def test_nothing_created_when_guard_fires(self):
        # guard failure must abort BEFORE any dir/log is created anywhere
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "driveX")
            os.makedirs(root)
            bad_out = os.path.join(root, "triage-out")
            with self.assertRaises(SystemExit):
                cli.main(["inventory", "--drive", root,
                          "--output-dir", bad_out,
                          "--log-dir", os.path.join(root, "logs")])
            self.assertEqual(os.listdir(root), [],
                             "guard fired but something was written to the "
                             "scanned drive")

    def test_overlapping_scan_roots_refused(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "driveZ")
            sub = os.path.join(root, "sub")
            os.makedirs(sub)
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["inventory", "--drive", root, "--drive", sub,
                          "--output-dir", os.path.join(base, "out"),
                          "--log-dir", os.path.join(base, "logs")])
            self.assertIn("overlap", str(ctx.exception))

    def test_c_and_d_refused_as_drive_args(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["inventory", "--drive", "D:\\",
                          "--output-dir", os.path.join(base, "out"),
                          "--log-dir", os.path.join(base, "logs")])
            self.assertIn("excluded", str(ctx.exception))

    def test_torn_tail_repaired_not_glued(self):
        from triage.util import CsvAppender
        with tempfile.TemporaryDirectory() as base:
            p = os.path.join(base, "t.csv")
            cols = ["path", "size", "error"]
            with CsvAppender(p, cols) as w:
                w.write({"path": "a", "size": "1", "error": ""})
            with open(p, "a", encoding="utf-8", newline="") as fh:
                fh.write("half,2")  # crash mid-row: no trailing newline
            with CsvAppender(p, cols) as w:
                w.write({"path": "b", "size": "3", "error": ""})
            rows = list(read_csv_rows(p, cols))
            paths = [r["path"] for r in rows]
            self.assertEqual(paths, ["a", "b"])  # torn row dropped, not glued

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks here")
    def test_symlinked_dir_not_traversed(self):
        with tempfile.TemporaryDirectory() as base:
            outside = os.path.join(base, "outside")
            os.makedirs(outside)
            with open(os.path.join(outside, "secret.txt"), "wb") as fh:
                fh.write(b"outside data")
            root = os.path.join(base, "driveY")
            os.makedirs(root)
            with open(os.path.join(root, "inside.txt"), "wb") as fh:
                fh.write(b"inside data")
            os.symlink(outside, os.path.join(root, "link"))
            out = os.path.join(base, "out")
            run_cli("inventory", "--drive", root, "--output-dir", out,
                    "--log-dir", os.path.join(base, "logs"))
            inv = rows_by_path(
                os.path.join(out, "inventory",
                             f"inventory-{os.path.basename(root)}.csv"),
                INVENTORY_COLUMNS)
            self.assertEqual(len(inv), 1)
            self.assertNotIn("secret", "".join(inv))

    def test_c_and_d_refused_in_scope(self):
        from triage.volumes import load_approved_scope
        with tempfile.TemporaryDirectory() as base:
            p = os.path.join(base, "scope.json")
            import json
            with open(p, "w") as fh:
                json.dump({"volumes": [
                    {"letter": "D:", "in_scope": True}]}, fh)
            with self.assertRaises(SystemExit):
                load_approved_scope(p)


class UncTargetTest(unittest.TestCase):
    def test_normalize_keeps_unc_and_expands_bare_letter(self):
        from triage.util import is_unc, normalize_root
        self.assertTrue(is_unc(r"\\100.76.11.114\fastwork"))
        self.assertFalse(is_unc(r"\\100.76.11.114"))
        self.assertFalse(is_unc("E:\\"))
        self.assertEqual(normalize_root(r"\\100.76.11.114\fastwork\ "),
                         r"\\100.76.11.114\fastwork")
        self.assertEqual(normalize_root(r'"\\100.76.11.114\video"'),
                         r"\\100.76.11.114\video")

    def test_slug_is_share_name(self):
        from triage.util import drive_slug
        for share in ("fastwork", "video", "data", "photos", "backups"):
            self.assertEqual(
                drive_slug(rf"\\100.76.11.114\{share}"), share)

    def test_incomplete_unc_refused(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["probe", "--drive", r"\\100.76.11.114",
                          "--output-dir", os.path.join(base, "out"),
                          "--log-dir", os.path.join(base, "logs")])
            self.assertIn("server", str(ctx.exception))

    def test_unreachable_target_fails_loudly(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["inventory", "--drive",
                          r"\\10.255.255.1\nosuchshare",
                          "--output-dir", os.path.join(base, "out"),
                          "--log-dir", os.path.join(base, "logs")])
            msg = str(ctx.exception)
            self.assertIn("cannot reach", msg)
            self.assertIn("Administrator session", msg)


class SystemBoxTest(unittest.TestCase):
    def test_profile_layout_at_drive_root_boxed_media_untouched(self):
        with tempfile.TemporaryDirectory() as base:
            g = os.path.join(base, "driveG")
            fixtures._w(g, "Users/jason/Documents/old.doc", b"doc", fixtures.OLD)
            fixtures._w(g, "Windows/System32/kernel32.dll", b"dll",
                        fixtures.OLD)
            fixtures._w(g, "Media/2020/Shoot/x.mp4", b"vid", fixtures.OLD)
            rows = [{"path": os.path.join(dp, f),
                     "ext": os.path.splitext(f)[1].lstrip(".").lower()}
                    for dp, _, fs in os.walk(g) for f in fs]
            import logging
            box = detect_boxes(g, rows, logging.getLogger("t"))
            self.assertTrue(box.boxes)
            self.assertIsNotNone(box.lookup(["Users", "jason", "Documents",
                                            "old.doc"]))
            self.assertIsNone(box.lookup(["Media", "2020", "Shoot", "x.mp4"]))


class UnitTest(unittest.TestCase):
    def test_date_parsing(self):
        self.assertEqual(parse_date_from_name("inv 2023-04-15 acme")[0],
                         "2023-04-15")
        self.assertEqual(parse_date_from_name("scan 20220301")[0],
                         "2022-03-01")
        self.assertEqual(parse_date_from_name("receipt 4-7-2021")[0],
                         "2021-04-07")
        self.assertIsNone(parse_date_from_name("no date here")[0])

    def test_record_name_proposal(self):
        name = propose_record_name(
            "invoice_2023-04-15_acme_$1200.pdf", "pdf", "2023-04-15",
            "Acme Corp", ["paperwork", "invoice_2023-04-15_acme_$1200.pdf"])
        self.assertTrue(name.startswith("2023-04-15  "))
        self.assertIn("Acme Corp", name)
        self.assertIn("$1200", name)
        self.assertNotIn("_", name.split("$")[0])

    def test_default_scope_exclusions(self):
        self.assertFalse(default_in_scope(
            {"letter": "C:", "drive_type": "Fixed", "bus": "NVMe"}))
        self.assertFalse(default_in_scope(
            {"letter": "D:", "drive_type": "Fixed", "bus": "SATA"}))
        self.assertFalse(default_in_scope(
            {"letter": "Z:", "drive_type": "Network", "bus": ""}))
        self.assertTrue(default_in_scope(
            {"letter": "E:", "drive_type": "Fixed", "bus": "USB"}))


class DupeGroupScaleTest(unittest.TestCase):
    """Layered backups routinely produce groups with tens of thousands of
    identical copies. Building a per-member counterpart list for those is
    quadratic and once pegged a real scan at 100% CPU for over an hour."""

    def test_huge_group_is_linear_not_quadratic(self):
        import time
        from triage.dupes import DReference, resolve_dupe_groups

        def build(n):
            files = [{"path": f"/d/f{i}.dat", "size": 8, "mtime": "t",
                      "full": "a" * 64} for i in range(n)]
            start = time.perf_counter()
            resolve_dupe_groups(files, DReference.empty())
            return time.perf_counter() - start

        build(2000)                       # warm up
        small, large = build(4000), build(16000)
        # 4x the members must not cost anywhere near 16x the time
        self.assertLess(large, max(small * 8, 0.5),
                        f"resolve_dupe_groups looks quadratic: "
                        f"4000 took {small:.3f}s, 16000 took {large:.3f}s")

    def test_counterparts_exclude_self_and_are_capped(self):
        from triage.dupes import DReference, resolve_dupe_groups
        from triage.util import norm_key
        files = [{"path": f"/d/c{i}.dat", "size": 8, "mtime": "t",
                  "full": "b" * 64} for i in range(80)]
        _, _, _, groups = resolve_dupe_groups(files, DReference.empty())
        cps = groups.counterparts(norm_key("/d/c0.dat"))
        self.assertNotIn("/d/c0.dat", cps)
        self.assertEqual(len(cps), 25)
        self.assertEqual(groups.counterparts(norm_key("/d/absent.dat")), [])


class CrossDriveTest(unittest.TestCase):
    """Several physical drives were all mounted as F:, so the comparison
    must key on content hash and attribute copies by run-folder name."""

    def _mkrun(self, ws, name, files):
        from triage.util import CsvAppender
        inv = os.path.join(ws, name, "inventory", "inventory-F.csv")
        with CsvAppender(inv, INVENTORY_COLUMNS) as w:
            for p, s, _ in files:
                w.write({"path": p, "size": s, "ext": "mp4", "error": "",
                         "created_utc": "2020-01-01T00:00:00Z",
                         "modified_utc": "2020-01-01T00:00:00Z"})
        with open(os.path.join(ws, name, "inventory", "inventory-F.done"),
                  "w") as fh:
            fh.write("complete\n")
        with CsvAppender(os.path.join(ws, name, "hashes", "full-F.csv"),
                         HASH_COLUMNS) as w:
            for p, s, sha in files:
                if sha:
                    w.write({"path": p, "size": s, "prefix_sha256": sha,
                             "full_sha256": sha, "error": "",
                             "modified_utc": "2020-01-01T00:00:00Z"})

    def test_finds_dupes_across_drives_sharing_a_letter(self):
        import hashlib
        import logging
        from triage import crossdrive
        shared = hashlib.sha256(b"shared").hexdigest()
        solo = hashlib.sha256(b"solo").hexdigest()
        with tempfile.TemporaryDirectory() as ws:
            # identical path strings on two different physical drives
            self._mkrun(ws, "DriveOne", [
                (r"F:\Videos\clip.mp4", 5_000_000_000, shared),
                (r"F:\Videos\solo.mp4", 900_000_000, solo),
                (r"F:\gap.mp4", 123_456_789, None),
            ])
            self._mkrun(ws, "DriveTwo", [
                (r"F:\Backup\clip.mp4", 5_000_000_000, shared),
                (r"F:\twin.mp4", 123_456_789, None),
            ])
            log = logging.getLogger("cdtest")
            log.addHandler(logging.NullHandler())
            res = crossdrive.analyze(ws, log)
            self.assertEqual(res["groups"], 1)
            self.assertEqual(res["reclaimable"], 5_000_000_000)
            # the size-unique-per-drive pair is reported as uncompared
            self.assertEqual(res["gap_files"], 2)
            rows = list(read_csv_rows(res["groups_csv"],
                                      ["sha256", "size", "copies",
                                       "drives", "paths"]))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["drives"], "DriveOne | DriveTwo")
            self.assertIn("[DriveOne] F:\\Videos\\clip.mp4", rows[0]["paths"])
            self.assertIn("[DriveTwo] F:\\Backup\\clip.mp4", rows[0]["paths"])
            # the file present on only one drive is not reported
            self.assertNotIn(solo, rows[0]["sha256"])

    def test_refuses_with_fewer_than_two_runs(self):
        import logging
        from triage import crossdrive
        with tempfile.TemporaryDirectory() as ws:
            self._mkrun(ws, "OnlyOne", [(r"F:\a.mp4", 10, None)])
            log = logging.getLogger("cdtest2")
            log.addHandler(logging.NullHandler())
            with self.assertRaises(SystemExit):
                crossdrive.analyze(ws, log)


class SecurityTest(unittest.TestCase):
    PKG = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "triage")
    FORBIDDEN = ("socket", "urllib", "http", "requests", "ftplib", "smtplib",
                 "telnetlib", "xmlrpc", "webbrowser", "ctypes", "shutil")

    def _sources(self):
        for fn in os.listdir(self.PKG):
            if fn.endswith(".py"):
                with open(os.path.join(self.PKG, fn),
                          encoding="utf-8") as fh:
                    yield fn, fh.read()

    def test_no_network_or_bulk_fs_imports(self):
        import re
        for fn, src in self._sources():
            for mod in self.FORBIDDEN:
                pat = re.compile(
                    rf"^\s*(import {mod}\b|from {mod}\b)", re.M)
                self.assertIsNone(
                    pat.search(src),
                    f"{fn} imports forbidden module {mod}")

    def test_subprocess_only_in_volumes(self):
        for fn, src in self._sources():
            if "subprocess" in src:
                self.assertEqual(fn, "volumes.py",
                                 f"subprocess use found in {fn}")

    def test_no_delete_or_rename_of_scanned_paths(self):
        # os.remove/os.replace are permitted only on regenerated outputs.
        # each: removing one of the tool's OWN regenerated output files
        # (inventory.py: 1 loop clearing its own csv + done marker on
        # --refresh, never a scanned path)
        allowed = {"classify.py": 1, "report.py": 1, "util.py": 1,
                   "crossdrive.py": 1, "inventory.py": 1}
        for fn, src in self._sources():
            removes = src.count("os.remove(") + src.count("os.rename(") \
                + src.count("os.unlink(")
            self.assertLessEqual(
                removes, allowed.get(fn, 0),
                f"{fn} contains unexpected delete/rename calls")



class HashGapsTest(unittest.TestCase):
    """`hashgaps` closes the cross-drive coverage gap by hashing ONLY the
    files no per-drive run ever hashed - and refuses to touch a drive it
    cannot prove is the one that was scanned. Several drives in the real
    fleet were all mounted as F:, so hashing another disk's bytes under this
    drive's paths would corrupt the duplicate set and could justify a wrong
    delete. That refusal is the important assertion here."""

    def _write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _mkrun(self, ws, name, slug, anchors, gaps):
        """anchors: real files recorded WITH hashes (prove volume identity).
        gaps: real files recorded in the inventory but never hashed."""
        import hashlib
        from triage.util import CsvAppender, iso_utc, PREFIX_BYTES
        inv = os.path.join(ws, name, "inventory", f"inventory-{slug}.csv")
        with CsvAppender(inv, INVENTORY_COLUMNS) as w:
            for p in anchors + gaps:
                st = os.stat(p)
                w.write({"path": p, "size": st.st_size, "ext": "bin",
                         "error": "", "created_utc": iso_utc(st.st_mtime),
                         "modified_utc": iso_utc(st.st_mtime)})
        with open(os.path.join(ws, name, "inventory",
                               f"inventory-{slug}.done"), "w") as fh:
            fh.write("complete\n")
        with CsvAppender(os.path.join(ws, name, "hashes",
                                      f"prefix-{slug}.csv"),
                         HASH_COLUMNS) as w:
            for p in anchors:
                st = os.stat(p)
                with open(p, "rb") as fh:
                    blob = fh.read()
                pre = hashlib.sha256(blob[:PREFIX_BYTES]).hexdigest()
                w.write({"path": p, "size": st.st_size,
                         "modified_utc": iso_utc(st.st_mtime),
                         "prefix_sha256": pre,
                         "full_sha256": hashlib.sha256(blob).hexdigest(),
                         "error": ""})

    def _fixture(self, root):
        """Two 'drives' whose only shared content is a pair of files that
        were size-unique on each drive, so neither run ever hashed them."""
        ws = os.path.join(root, "ws")
        d1, d2 = os.path.join(root, "vol1"), os.path.join(root, "vol2")
        # anchors: distinct sizes per drive, so they are not gaps themselves.
        # At least _VERIFY_MIN_MATCHES of them must be re-readable and
        # identical before any drive is touched.
        anchors1 = [self._write(os.path.join(d1, f"a{i}.bin"),
                                bytes([65 + i]) * (100 + i))
                    for i in range(8)]
        anchors2 = [self._write(os.path.join(d2, f"b{i}.bin"),
                                bytes([97 + i]) * (900 + i))
                    for i in range(8)]
        # the gap pair: byte-identical, same size, one copy on each drive
        # > PREFIX_BYTES, so closing the gap genuinely requires
        # the second (full-hash) stage, not just the prefix pass
        twin = b"TWIN-CONTENT" * 10000
        g1 = self._write(os.path.join(d1, "deep", "twin.bin"), twin)
        g2 = self._write(os.path.join(d2, "other", "copy.bin"), twin)
        self._mkrun(ws, "DriveOne", "A", anchors1, [g1])
        self._mkrun(ws, "DriveTwo", "B", anchors2, [g2])
        return ws, d1, d2, g1, g2

    def _log(self):
        import logging
        log = logging.getLogger("hgtest")
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return log

    def test_closes_the_gap_end_to_end(self):
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, _, _, g1, g2 = self._fixture(root)
            first = crossdrive.analyze(ws, log)
            self.assertEqual(first["groups"], 0)      # nothing comparable yet
            self.assertEqual(first["gap_files"], 2)   # both twins uncompared

            res = hashgaps.run(ws, log)
            self.assertEqual(res["skipped"], [])
            self.assertEqual(res["full_hashed"], 2)

            second = crossdrive.analyze(ws, log)
            self.assertEqual(second["groups"], 1)
            self.assertEqual(second["gap_files"], 0)
            with open(second["groups_csv"], encoding="utf-8") as fh:
                paths = fh.read()
            self.assertIn(os.path.basename(g1), paths)
            self.assertIn(os.path.basename(g2), paths)

    def test_refuses_a_drive_whose_content_changed_under_it(self):
        """The wrong-volume case: same paths, different bytes. Nothing may
        be hashed for that drive - a false duplicate here is unrecoverable."""
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, d1, _, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            # another disk is now mounted where DriveOne was: identical
            # sizes, different content
            for i in range(4):   # half the sample now holds other bytes
                p = os.path.join(d1, f"a{i}.bin")
                self._write(p, bytes(os.stat(p).st_size))

            res = hashgaps.run(ws, log)
            skipped = dict(res["skipped"])
            self.assertIn("DriveOne", skipped)
            self.assertIn("DIFFERENT CONTENT", skipped["DriveOne"])
            self.assertNotIn("DriveOne", [n for n, _, _ in res["processed"]])
            # and nothing was recorded for it
            self.assertFalse(os.path.exists(
                os.path.join(ws, "DriveOne", "hashes", "full-A.csv")))

    def test_skips_a_drive_that_is_not_attached(self):
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, d1, _, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            shutil.rmtree(d1)
            res = hashgaps.run(ws, log)
            skipped = dict(res["skipped"])
            self.assertIn("DriveOne", skipped)
            self.assertIn("not attached", skipped["DriveOne"])
            # the attached drive is still processed
            self.assertIn("DriveTwo", [n for n, _, _ in res["processed"]])

    def test_scanned_files_are_not_modified(self):
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, d1, d2, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)

            def snapshot():
                out = {}
                for base in (d1, d2):
                    for dirpath, _, names in os.walk(base):
                        for n in names:
                            fp = os.path.join(dirpath, n)
                            st = os.stat(fp)
                            with open(fp, "rb") as fh:
                                out[fp] = (st.st_size, int(st.st_mtime),
                                           fh.read())
                return out

            before = snapshot()
            hashgaps.run(ws, log)
            self.assertEqual(before, snapshot())

    # -- the wrong-volume defence, attacked --------------------------------

    def test_refuses_a_sibling_drive_that_shares_only_a_few_files(self):
        """The realistic wrong-volume case: six externals all mount as F:,
        and one is a partial backup of another, so it carries SOME of the
        same files. Matching on the files it happens to share must not
        authorise hashing everything else on it as this drive's content."""
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, d1, _, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            # a different disk is at F:. It carries 3 of DriveOne's 8 anchor
            # files byte-for-byte (it is a partial backup) and nothing else.
            for i in range(3, 8):
                os.remove(os.path.join(d1, f"a{i}.bin"))
            os.remove(os.path.join(d1, "deep", "twin.bin"))
            res = hashgaps.run(ws, log)
            skipped = dict(res["skipped"])
            self.assertIn("DriveOne", skipped)
            self.assertIn("only 3 of 8", skipped["DriveOne"])
            self.assertNotIn("DriveOne", [n for n, _, _ in res["processed"]])

    def test_refuses_a_run_with_too_few_hashes_to_verify(self):
        """No content evidence means no hashing. Size+mtime is not evidence:
        a clone or a timestamp-preserving copy reproduces both exactly."""
        from triage import hashgaps
        from triage.util import CsvAppender, iso_utc
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, "vol")
            f = self._write(os.path.join(d, "only.bin"), b"x" * 4096)
            rd = os.path.join(root, "ws", "Solo")
            st = os.stat(f)
            with CsvAppender(os.path.join(rd, "inventory",
                                          "inventory-Z.csv"),
                             INVENTORY_COLUMNS) as w:
                w.write({"path": f, "size": st.st_size, "ext": "bin",
                         "error": "", "created_utc": iso_utc(st.st_mtime),
                         "modified_utc": iso_utc(st.st_mtime)})
            ok, why = hashgaps.verify_volume(rd, "Z", self._log())
            self.assertFalse(ok)
            self.assertIn("too few", why)

    def test_multi_target_run_folder_verifies_each_volume_separately(self):
        """A run folder holding two targets names two DIFFERENT physical
        volumes. Proving one is mounted says nothing about the other."""
        from triage import hashgaps
        with tempfile.TemporaryDirectory() as root:
            ws = os.path.join(root, "ws")
            dE, dF = os.path.join(root, "volE"), os.path.join(root, "volF")
            ae = [self._write(os.path.join(dE, f"e{i}.bin"),
                              bytes([70 + i]) * (500 + i)) for i in range(4)]
            af = [self._write(os.path.join(dF, f"f{i}.bin"),
                              bytes([80 + i]) * (700 + i)) for i in range(4)]
            ge = self._write(os.path.join(dE, "ge.bin"), b"E" * 70000)
            gf = self._write(os.path.join(dF, "gf.bin"), b"F" * 70000)
            self._mkrun(ws, "BOTH", "E", ae, [ge])
            self._mkrun(ws, "BOTH", "F", af, [gf])
            self.assertEqual(hashgaps.run_slugs(os.path.join(ws, "BOTH")),
                             ["E", "F"])
            # swap the F: volume for something else entirely
            for p in af:
                self._write(p, bytes(os.stat(p).st_size))
            rd = os.path.join(ws, "BOTH")
            self.assertTrue(hashgaps.verify_volume(rd, "E", self._log())[0])
            okF, whyF = hashgaps.verify_volume(rd, "F", self._log())
            self.assertFalse(okF)
            self.assertIn("DIFFERENT CONTENT", whyF)
            # and each volume's gap paths are routed to its own slug
            split = hashgaps.split_by_slug(rd, ["E", "F"], [ge, gf],
                                           self._log())
            self.assertEqual(split["E"], [ge])
            self.assertEqual(split["F"], [gf])

    def test_reports_a_gap_drive_whose_run_folder_is_missing(self):
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, _, _, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            os.rename(os.path.join(ws, "DriveOne"),
                      os.path.join(ws, "DriveOne-moved"))
            res = hashgaps.run(ws, log)
            skipped = dict(res["skipped"])
            self.assertIn("DriveOne", skipped)
            self.assertIn("no run folder", skipped["DriveOne"])

    def test_deleted_gap_files_do_not_look_like_a_dead_drive(self):
        """The gap list is a snapshot; files deleted since then are normal.
        Treating them as device failures would abort the drive."""
        from triage import hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, "vol")
            live = self._write(os.path.join(d, "live.bin"), b"L" * 70000)
            gone = [os.path.join(d, f"gone{i}.bin") for i in range(60)]
            rd = os.path.join(root, "ws", "D")
            breaker = hashgaps._GapBreaker("D", "prefix hashing")
            n = hashgaps._prefix_gaps(rd, "A", gone + [live], log, breaker)
            self.assertEqual(n, 1)          # the surviving file was hashed
            self.assertEqual(breaker.vanished, 60)
            self.assertEqual(breaker.errors, 0)

    def test_full_pass_skips_a_file_that_changed_since_the_prefix_pass(self):
        from triage import hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, "vol")
            f = self._write(os.path.join(d, "moving.bin"), b"A" * 70000)
            rd = os.path.join(root, "ws", "D")
            breaker = hashgaps._GapBreaker("D", "prefix hashing")
            hashgaps._prefix_gaps(rd, "A", [f], log, breaker)
            rows = list(hashgaps._load_hashed(
                hashgaps.hash_csvs(rd, "A")[0]).values())
            self._write(f, b"B" * 90000)     # different size and content
            n = hashgaps._full_gaps(rd, "A", rows, log,
                                    hashgaps._GapBreaker("D", "full hashing"))
            self.assertEqual(n, 0)

    def test_gap_count_converges_for_files_proven_unique(self):
        """Same size, different content: after one gap pass the 64KB
        prefixes prove no twin can exist, so the files must drop off the
        gap list instead of being reported forever."""
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws = os.path.join(root, "ws")
            d1, d2 = os.path.join(root, "v1"), os.path.join(root, "v2")
            a1 = [self._write(os.path.join(d1, f"a{i}.bin"),
                              bytes([65 + i]) * (100 + i)) for i in range(8)]
            a2 = [self._write(os.path.join(d2, f"b{i}.bin"),
                              bytes([97 + i]) * (900 + i)) for i in range(8)]
            # equal size, different bytes -> look like gap candidates, but
            # are not duplicates and never will be
            n1 = self._write(os.path.join(d1, "n1.bin"), b"X" * 160000)
            n2 = self._write(os.path.join(d2, "n2.bin"), b"Y" * 160000)
            self._mkrun(ws, "One", "A", a1, [n1])
            self._mkrun(ws, "Two", "B", a2, [n2])

            self.assertEqual(crossdrive.analyze(ws, log)["gap_files"], 2)
            res = hashgaps.run(ws, log)
            self.assertEqual(res["full_hashed"], 0)   # nothing worth reading
            self.assertEqual(res["pending"], [])
            after = crossdrive.analyze(ws, log)
            self.assertEqual(after["gap_files"], 0)
            self.assertEqual(after["groups"], 0)

    def test_converges_for_drives_that_cannot_be_attached_together(self):
        """Six externals all mount as F:, so two of them are never present
        at once. The twin pair must still be found, and the summary must say
        which drive still owes a whole-file hash rather than going quiet."""
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, d1, d2, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            # pass 1: only DriveOne is plugged in
            r1 = hashgaps.run(ws, log, only=["DriveOne"])
            self.assertEqual(r1["full_hashed"], 0)
            # pass 2: swap to DriveTwo - now the prefixes match across drives
            r2 = hashgaps.run(ws, log, only=["DriveTwo"])
            self.assertEqual(r2["full_hashed"], 1)
            self.assertEqual([lbl for lbl, _ in r2["pending"]], ["DriveOne"])
            # pass 3: DriveOne back on, and it is told exactly that
            r3 = hashgaps.run(ws, log, only=["DriveOne"])
            self.assertEqual(r3["full_hashed"], 1)
            self.assertEqual(r3["pending"], [])
            final = crossdrive.analyze(ws, log)
            self.assertEqual(final["groups"], 1)
            self.assertEqual(final["gap_files"], 0)

    def test_failed_full_hash_is_not_reported_as_a_unique_prefix(self):
        """A whole-file read that failed must be named as a read failure -
        calling it 'prefix matched nothing' hides a failing disk."""
        from triage import crossdrive
        from triage.util import CsvAppender
        with tempfile.TemporaryDirectory() as root:
            rd = os.path.join(root, "run")
            with CsvAppender(os.path.join(rd, "hashes", "prefix-A.csv"),
                             HASH_COLUMNS) as w:
                w.write({"path": r"F:\v.mov", "size": "5000",
                         "modified_utc": "2020-01-01T00:00:00Z",
                         "prefix_sha256": "ab" * 32, "full_sha256": "",
                         "error": ""})
            with CsvAppender(os.path.join(rd, "hashes", "full-A.csv"),
                             HASH_COLUMNS) as w:
                w.write({"path": r"F:\v.mov", "size": "5000",
                         "modified_utc": "2020-01-01T00:00:00Z",
                         "prefix_sha256": "ab" * 32, "full_sha256": "",
                         "error": "[Errno 5] I/O error"})
            state = crossdrive.prefix_status(rd)
            _size, _pre, failure = state[list(state)[0]]
            self.assertIn("whole-file read failed", failure)

    def test_recorded_volume_label_mismatch_is_refused_by_name(self):
        """`inventory` stamps the volume label+size next to each inventory.
        When Windows says a different volume is at that letter, say so by
        name rather than inferring it from sampled files."""
        from triage import hashgaps
        from triage.util import atomic_write_json
        with tempfile.TemporaryDirectory() as root:
            rd = os.path.join(root, "run")
            os.makedirs(os.path.join(rd, "inventory"))
            atomic_write_json(
                os.path.join(rd, "inventory", "inventory-F.meta.json"),
                {"label": "T7-SHIELD", "size": 2000398934016})
            sigs = {"F:": {"label": "WD_PASSPORT", "size": 4000787030016}}
            why = hashgaps.recorded_volume_mismatch(rd, "F", sigs)
            self.assertIn("different volume", why)
            self.assertIn("T7-SHIELD", why)
            self.assertIn("WD_PASSPORT", why)
            ok, reason = hashgaps.verify_volume(rd, "F", self._log(),
                                                signatures=sigs)
            self.assertFalse(ok)
            self.assertEqual(reason, why)
            # same volume still mounted -> this gate says nothing
            same = {"F:": {"label": "T7-SHIELD", "size": 2000398934016}}
            self.assertIsNone(
                hashgaps.recorded_volume_mismatch(rd, "F", same))

    def test_only_flag_limits_to_named_runs(self):
        from triage import crossdrive, hashgaps
        log = self._log()
        with tempfile.TemporaryDirectory() as root:
            ws, _, _, _, _ = self._fixture(root)
            crossdrive.analyze(ws, log)
            res = hashgaps.run(ws, log, only=["DriveTwo"])
            self.assertEqual([n for n, _, _ in res["processed"]], ["DriveTwo"])
            # with only one drive prefix-hashed, its twin has no counterpart
            # yet in the global census, so nothing is full-hashed
            self.assertEqual(res["full_hashed"], 0)

    def test_requires_the_gap_list_to_exist(self):
        from triage import hashgaps
        with tempfile.TemporaryDirectory() as root:
            ws, _, _, _, _ = self._fixture(root)
            with self.assertRaises(SystemExit) as ctx:
                hashgaps.run(ws, self._log())
            self.assertIn("Compare All Drives", str(ctx.exception))

    def test_workspace_may_not_be_a_whole_drive_or_share(self):
        """crossdrive and hashgaps both WRITE into the workspace, so a bare
        volume/share root - what a scanned drive looks like - is refused."""
        import argparse
        for bad in ("E:\\", "E:", "\\\\nas\\photos"):
            args = argparse.Namespace(workspace=bad)
            cfg = {"output_dir": os.path.join("C:", "DEV", "triage", "X")}
            with self.assertRaises(SystemExit) as ctx:
                cli._resolve_workspace(cfg, args)
            self.assertRegex(str(ctx.exception), "refusing|not found")



class ProjectIdentityTest(unittest.TestCase):
    """A project is its directory PATH, not its NAME. Two folders that merely
    share a name must not share an activity timestamp (a 2024 shoot must not
    drag a 2016 shoot onto fastwork) and must never be proposed into the
    same destination, where their same-named camera files would collide."""

    def _media(self, path, mtime=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(os.urandom(64) + path.encode("utf-8", "replace"))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def _pipeline(self, base, roots):
        out = os.path.join(base, "out")
        logs = os.path.join(base, "logs")
        common = []
        for r in roots:
            common += ["--drive", r]
        common += ["--output-dir", out, "--log-dir", logs]
        for cmd in ("inventory", "hash", "classify"):
            rc, _ = run_cli(cmd, *common)
            self.assertEqual(rc, 0, f"{cmd} failed")
        rows = {}
        for r in roots:
            slug = os.path.basename(r)
            rows.update(rows_by_path(
                os.path.join(out, "classify", f"classify-{slug}.csv"),
                CLASSIFY_COLUMNS))
        return out, rows

    def test_same_named_projects_on_one_drive_stay_separate(self):
        import time
        old_ts = 1451606400  # 2016-01-01: far outside active_project_days
        with tempfile.TemporaryDirectory() as base:
            drive = os.path.join(base, "driveE")
            fresh = self._media(os.path.join(
                drive, "ClientA", "Smith Job", "RAW", "clip1.mp4"),
                time.time() - 3600)
            stale = self._media(os.path.join(
                drive, "ClientB", "Smith Job", "RAW", "clip2.mp4"), old_ts)
            _, rows = self._pipeline(base, [drive])

            r_fresh, r_stale = rows[fresh], rows[stale]
            # the 2016 project must NOT inherit the 2025 project's recency
            self.assertEqual(r_fresh["nas_tier"], "fastwork")
            self.assertEqual(r_stale["nas_tier"], "hdd-mirror",
                             "a same-named project's activity leaked")
            # and the two projects get two destinations
            self.assertNotEqual(r_fresh["proposed_path"],
                                r_stale["proposed_path"])
            self.assertIn("(ClientA)", r_fresh["proposed_path"])
            self.assertIn("(ClientB)", r_stale["proposed_path"])

    def test_same_named_projects_on_two_drives_get_distinct_destinations(self):
        import time
        now = time.time() - 3600
        with tempfile.TemporaryDirectory() as base:
            e = os.path.join(base, "driveE")
            f = os.path.join(base, "driveF")
            a = self._media(os.path.join(
                e, "ClientX", "Smith Job", "RAW", "C0010.MP4"), now)
            b = self._media(os.path.join(
                f, "ClientY", "Smith Job", "RAW", "C0010.MP4"), now)
            _, rows = self._pipeline(base, [e, f])
            pa, pb = rows[a]["proposed_path"], rows[b]["proposed_path"]
            # both active -> both fastwork; but never the same folder, or
            # the two C0010.MP4 would collide in the copy phase
            self.assertEqual(rows[a]["nas_tier"], "fastwork")
            self.assertEqual(rows[b]["nas_tier"], "fastwork")
            self.assertNotEqual(pa.casefold(), pb.casefold())

    def test_unique_project_name_is_not_renamed(self):
        import time
        with tempfile.TemporaryDirectory() as base:
            drive = os.path.join(base, "driveE")
            p = self._media(os.path.join(
                drive, "2023 Acme Rebrand", "RAW", "A001.mp4"),
                time.time() - 3600)
            _, rows = self._pipeline(base, [drive])
            self.assertTrue(rows[p]["proposed_path"].startswith(
                "2023 Acme Rebrand\\"), rows[p]["proposed_path"])


    def test_alias_never_collides_with_a_real_project_name(self):
        """Qualifying "Smith Job" under parent "2016" yields
        "Smith Job (2016)" - which must not be handed out when a project is
        literally called that."""
        from triage.classify import project_aliases
        root = "E:\\"
        projects = {
            "e:\\2016\\smith job": ("2016\\Smith Job", "Smith Job"),
            "e:\\2024\\smith job": ("2024\\Smith Job", "Smith Job"),
            "e:\\other\\smith job (2016)": ("other\\Smith Job (2016)",
                                             "Smith Job (2016)"),
        }
        aliases = project_aliases({root: projects})
        issued = sorted(aliases.values())
        self.assertEqual(len(set(a.casefold() for a in issued)), len(issued))
        for a in issued:
            self.assertNotEqual(a.casefold(), "smith job (2016)")

    def test_aliases_are_stable_across_runs(self):
        from triage.classify import project_aliases
        projects = {
            "e:\\a\\job": ("a\\Job", "Job"),
            "e:\\b\\job": ("b\\Job", "Job"),
        }
        first = project_aliases({"E:\\": projects})
        second = project_aliases({"E:\\": dict(reversed(
            list(projects.items())))})
        self.assertEqual(first, second)


class ProvenanceTest(unittest.TestCase):
    """Classification must be reproducible: the activity cutoff is computed
    once, recorded, and reused - and every run folder carries a provenance
    record naming the version, cutoff and inputs that produced it."""

    def _setup(self, base):
        import time
        drive = os.path.join(base, "driveE")
        path = os.path.join(drive, "Client", "Fresh Job", "RAW", "c.mp4")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as fh:
            fh.write(b"movie" * 100)
        os.utime(path, (time.time() - 3600,) * 2)
        out = os.path.join(base, "out")
        common = ["--drive", drive, "--output-dir", out,
                  "--log-dir", os.path.join(base, "logs")]
        for cmd in ("inventory", "hash"):
            rc, _ = run_cli(cmd, *common)
            self.assertEqual(rc, 0)
        return drive, path, out, common

    def test_cutoff_recorded_and_classify_reproducible(self):
        import json
        with tempfile.TemporaryDirectory() as base:
            drive, path, out, common = self._setup(base)
            rc, _ = run_cli("classify", *common)
            self.assertEqual(rc, 0)
            info_path = os.path.join(out, "run-info.json")
            with open(info_path, encoding="utf-8") as fh:
                info = json.load(fh)
            for field in ("tool_version", "activity_cutoff_iso", "config",
                          "d_reference_csv", "scan_roots",
                          "classified_at_utc"):
                self.assertIn(field, info)

            csv_path = os.path.join(out, "classify",
                                    "classify-driveE.csv")
            with open(csv_path, "rb") as fh:
                first = fh.read()
            rc, _ = run_cli("classify", *common)
            self.assertEqual(rc, 0)
            with open(csv_path, "rb") as fh:
                second = fh.read()
            self.assertEqual(first, second,
                             "re-running classify with recorded inputs "
                             "must be byte-identical")

    def test_recorded_cutoff_is_actually_used(self):
        import json
        with tempfile.TemporaryDirectory() as base:
            drive, path, out, common = self._setup(base)
            rc, _ = run_cli("classify", *common)
            self.assertEqual(rc, 0)
            rows = rows_by_path(os.path.join(out, "classify",
                                             "classify-driveE.csv"),
                                CLASSIFY_COLUMNS)
            self.assertEqual(rows[path]["nas_tier"], "fastwork")
            # push the recorded cutoff into the future: nothing is active
            shared = os.path.join(os.path.dirname(out),
                                  "activity-cutoff.json")
            with open(shared, "w", encoding="utf-8") as fh:
                json.dump({"activity_cutoff_iso": "2999-01-01T00:00:00Z"}, fh)
            rc, _ = run_cli("classify", *common)
            self.assertEqual(rc, 0)
            rows = rows_by_path(os.path.join(out, "classify",
                                             "classify-driveE.csv"),
                                CLASSIFY_COLUMNS)
            self.assertEqual(rows[path]["nas_tier"], "hdd-mirror",
                             "the recorded cutoff was not used")

    def test_cutoff_is_shared_across_per_drive_run_folders(self):
        """Every drive is triaged into its OWN output folder. A per-folder
        cutoff would give each drive whatever date it happened to be
        scanned on, moving the fastwork line from drive to drive."""
        import json, time
        with tempfile.TemporaryDirectory() as base:
            ws = os.path.join(base, "ws")
            outs = []
            for i in (1, 2):
                drive = os.path.join(base, f"drive{i}")
                f = os.path.join(drive, "Client", f"Job{i}", "RAW", "c.mp4")
                os.makedirs(os.path.dirname(f))
                with open(f, "wb") as fh:
                    fh.write(b"movie" * (100 + i))
                os.utime(f, (time.time() - 3600,) * 2)
                out = os.path.join(ws, f"RUN{i}")
                common = ["--drive", drive, "--output-dir", out,
                          "--log-dir", os.path.join(base, "logs")]
                for cmd in ("inventory", "hash", "classify"):
                    rc, _ = run_cli(cmd, *common)
                    self.assertEqual(rc, 0)
                outs.append(out)
            cutoffs = []
            for out in outs:
                with open(os.path.join(out, "run-info.json"),
                          encoding="utf-8") as fh:
                    cutoffs.append(json.load(fh)["activity_cutoff_iso"])
            self.assertEqual(cutoffs[0], cutoffs[1],
                             "each run folder invented its own cutoff")
            self.assertTrue(os.path.exists(
                os.path.join(ws, "activity-cutoff.json")))

    def test_cutoff_flag_rejects_an_impossible_date(self):
        with tempfile.TemporaryDirectory() as base:
            drive, path, out, common = self._setup(base)
            with self.assertRaises(SystemExit) as ctx:
                run_cli("classify", "--cutoff", "2026-13-40", *common)
            self.assertIn("real date", str(ctx.exception))

    def test_cutoff_flag_overrides_and_rerecords(self):
        import json
        with tempfile.TemporaryDirectory() as base:
            drive, path, out, common = self._setup(base)
            rc, _ = run_cli("classify", "--cutoff", "2000-01-01", *common)
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "run-info.json"),
                      encoding="utf-8") as fh:
                info = json.load(fh)
            self.assertEqual(info["activity_cutoff_iso"],
                             "2000-01-01T00:00:00Z")


class PlanTest(unittest.TestCase):
    """The plan stage must prove safety or emit nothing: SHA256 on every
    delete, collision-free destinations, and keeper-copied-before-delete
    ordering."""

    SHA_A = "aa" * 32
    SHA_B = "bb" * 32
    SHA_D = "dd" * 32

    def _mkrun(self, ws, name, classify_rows, hash_rows=()):
        from triage.util import CsvAppender
        rd = os.path.join(ws, name)
        os.makedirs(os.path.join(rd, "inventory"), exist_ok=True)
        with CsvAppender(os.path.join(rd, "classify", "classify-X.csv"),
                         CLASSIFY_COLUMNS) as w:
            for r in classify_rows:
                row = {c: "" for c in CLASSIFY_COLUMNS}
                row.update(r)
                row.setdefault("confidence", "high")
                w.write(row)
        if hash_rows:
            with CsvAppender(os.path.join(rd, "hashes", "full-X.csv"),
                             HASH_COLUMNS) as w:
                for path, size, sha in hash_rows:
                    w.write({"path": path, "size": size,
                             "modified_utc": "2020-01-01T00:00:00Z",
                             "prefix_sha256": sha, "full_sha256": sha,
                             "error": ""})
        return rd

    def _log(self):
        import logging
        log = logging.getLogger("plantest")
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return log

    def test_plan_orders_and_proves_everything(self):
        from triage import plan
        with tempfile.TemporaryDirectory() as ws:
            keeper = r"F:\media\keep.mp4"
            dupe = r"F:\backup\keep copy.mp4"
            dref_dupe = r"F:\old\ddupe.bin"
            self._mkrun(ws, "DriveOne", [
                {"path": keeper, "size": "100", "drive": "F:\\",
                 "class": "MEDIA", "nas_tier": "fastwork",
                 "proposed_path": "Job\\01_RAW"},
                {"path": dupe, "size": "100", "drive": "F:\\",
                 "class": "DUPE_EXTERNAL", "dupe_of": keeper},
                {"path": dref_dupe, "size": "50", "drive": "F:\\",
                 "class": "EXACT_DUPE_OF_D", "dupe_of": r"D:\ref\x.bin"},
                {"path": r"F:\junk\thumbs.db", "size": "10", "class": "JUNK"},
                {"path": r"F:\odd\what.xyz", "size": "5",
                 "class": "UNKNOWN"},
            ], hash_rows=[(keeper, "100", self.SHA_A),
                          (dupe, "100", self.SHA_A),
                          (dref_dupe, "50", self.SHA_D)])
            res = plan.build(ws, self._log())
            rows = list(read_csv_rows(res["plan_csv"], plan.PLAN_COLUMNS))
            self.assertEqual(res["held"], 1)          # UNKNOWN not planned
            by_path = {r["source_path"]: r for r in rows}
            k, d = by_path[keeper], by_path[dupe]
            # every copy precedes every delete
            self.assertTrue(all(
                int(a["seq"]) < int(b["seq"])
                for a in rows if a["action"] == "copy"
                for b in rows if b["action"] != "copy"))
            # the delete names its keeper's copy row and both hashes match
            self.assertEqual(d["depends_on"], k["seq"])
            self.assertEqual(d["sha256"], self.SHA_A)
            self.assertEqual(d["keeper_sha256"], self.SHA_A)
            self.assertEqual(k["sha256"], self.SHA_A)
            self.assertEqual(by_path[dref_dupe]["depends_on"], "D-REF")

    def test_colliding_destinations_are_qualified_not_overwritten(self):
        """Drives are scanned one at a time, so classification cannot know
        another drive holds a same-named project. The clash surfaces here
        and must be resolved - never by letting one file overwrite the
        other."""
        from triage import plan
        with tempfile.TemporaryDirectory() as ws:
            a = "F:\\one\\C0010.MP4"
            b = "F:\\two\\C0010.MP4"
            self._mkrun(ws, "DriveOne", [
                {"path": a, "size": "10", "class": "MEDIA",
                 "nas_tier": "fastwork", "proposed_path": "Job\\01_RAW"},
            ], hash_rows=[(a, "10", self.SHA_A)])
            self._mkrun(ws, "DriveTwo", [
                {"path": b, "size": "20", "class": "MEDIA",
                 "nas_tier": "fastwork", "proposed_path": "Job\\01_RAW"},
            ], hash_rows=[(b, "20", self.SHA_B)])
            res = plan.build(ws, self._log())
            self.assertEqual(res["copies"], 2)
            self.assertEqual(res["qualified"], 1)
            rows = list(read_csv_rows(res["plan_csv"], plan.PLAN_COLUMNS))
            dests = sorted(r["dest_path"] for r in rows)
            self.assertEqual(len(set(d.casefold() for d in dests)), 2,
                             "two files still share one destination")
            self.assertTrue(any(d.startswith("DriveTwo\\") for d in dests))

    def test_identical_content_at_one_destination_is_merged(self):
        from triage import plan
        with tempfile.TemporaryDirectory() as ws:
            a = "F:\\one\\same.mp4"
            b = "F:\\two\\same.mp4"
            self._mkrun(ws, "DriveOne", [
                {"path": a, "size": "10", "class": "MEDIA",
                 "nas_tier": "hdd-mirror",
                 "proposed_path": "Media\\2020\\Job"},
                {"path": b, "size": "10", "class": "MEDIA",
                 "nas_tier": "hdd-mirror",
                 "proposed_path": "Media\\2020\\Job"},
            ], hash_rows=[(a, "10", self.SHA_A), (b, "10", self.SHA_A)])
            res = plan.build(ws, self._log())
            self.assertEqual(res["merged"], 1)
            self.assertEqual(res["copies"], 1)

    def test_hash_contradiction_halts_and_invalidates_a_previous_plan(self):
        """Classification says duplicate, the recorded hashes disagree.
        Something upstream is wrong, so no delete in this plan can be
        trusted - and any earlier plan must not outlive it."""
        from triage import plan
        from triage.util import CsvAppender
        with tempfile.TemporaryDirectory() as ws:
            keeper = "F:\\media\\keep.mp4"
            rd = self._mkrun(ws, "DriveOne", [
                {"path": keeper, "size": "10", "class": "MEDIA",
                 "nas_tier": "fastwork", "proposed_path": "Job\\01_RAW"},
            ], hash_rows=[(keeper, "10", self.SHA_A)])
            first = plan.build(ws, self._log())
            self.assertEqual(first["copies"], 1)

            dupe = "F:\\backup\\copy.mp4"
            with CsvAppender(os.path.join(rd, "classify", "classify-X.csv"),
                             CLASSIFY_COLUMNS) as w:
                row = {c: "" for c in CLASSIFY_COLUMNS}
                row.update({"path": dupe, "size": "10",
                            "class": "DUPE_EXTERNAL", "dupe_of": keeper,
                            "confidence": "high"})
                w.write(row)
            with CsvAppender(os.path.join(rd, "hashes", "full-X.csv"),
                             HASH_COLUMNS) as w:
                w.write({"path": dupe, "size": "10",
                         "modified_utc": "2020-01-01T00:00:00Z",
                         "prefix_sha256": self.SHA_B,
                         "full_sha256": self.SHA_B, "error": ""})
            with self.assertRaises(SystemExit) as ctx:
                plan.build(ws, self._log())
            self.assertIn("NO PLAN WRITTEN", str(ctx.exception))
            self.assertEqual(list(read_csv_rows(
                os.path.join(ws, "_plan", "plan.csv"), plan.PLAN_COLUMNS)),
                [], "stale plan rows survived a violating build")
            with open(os.path.join(ws, "_plan", "plan-report.md"),
                      encoding="utf-8") as fh:
                self.assertIn("NOT BUILT", fh.read())
            with open(os.path.join(ws, "_plan", "plan-violations.csv"),
                      encoding="utf-8") as fh:
                self.assertIn("hash-contradiction", fh.read())

    def test_unprovable_deletes_are_held_not_emitted(self):
        """A delete that does not happen costs disk, never data. Holding
        one must not refuse the whole fleet's plan."""
        from triage import plan
        with tempfile.TemporaryDirectory() as ws:
            keeper = "F:\\media\\keep.mp4"
            no_hash = "F:\\backup\\copy.mp4"
            held_keeper = "F:\\odd\\keeper.xyz"
            held_dupe = "F:\\backup\\odd copy.xyz"
            junk = "F:\\junk\\big.tmp"
            self._mkrun(ws, "DriveOne", [
                {"path": keeper, "size": "10", "class": "MEDIA",
                 "nas_tier": "fastwork", "proposed_path": "Job\\01_RAW"},
                {"path": no_hash, "size": "10", "class": "DUPE_EXTERNAL",
                 "dupe_of": keeper},
                {"path": held_keeper, "size": "9", "class": "UNKNOWN"},
                {"path": held_dupe, "size": "9", "class": "DUPE_EXTERNAL",
                 "dupe_of": held_keeper},
                {"path": junk, "size": "500", "class": "JUNK"},
            ], hash_rows=[(keeper, "10", self.SHA_A),
                          (held_keeper, "9", self.SHA_B),
                          (held_dupe, "9", self.SHA_B)])
            res = plan.build(ws, self._log())
            self.assertEqual(res["copies"], 1)
            self.assertEqual(res["deletes"], 0)
            self.assertEqual(res["held_deletes"], 3)
            with open(res["report"], encoding="utf-8") as fh:
                report = fh.read()
            self.assertIn("no measured SHA256", report)
            self.assertIn("keeper is not scheduled", report)
            self.assertIn("never deleted on its path alone", report)

    def test_rows_carry_the_volume_signature_of_their_drive(self):
        """All six externals mounted as F:, so a path alone does not name a
        file. Every row must tell the executor which disk it means."""
        from triage import plan
        from triage.util import atomic_write_json
        with tempfile.TemporaryDirectory() as ws:
            a = "F:\\media\\keep.mp4"
            rd = self._mkrun(ws, "DriveOne", [
                {"path": a, "size": "10", "class": "MEDIA",
                 "nas_tier": "fastwork", "proposed_path": "Job\\01_RAW"},
            ], hash_rows=[(a, "10", self.SHA_A)])
            atomic_write_json(
                os.path.join(rd, "inventory", "inventory-X.meta.json"),
                {"label": "T7-SHIELD", "size": 2000398934016})
            res = plan.build(ws, self._log())
            rows = list(read_csv_rows(res["plan_csv"], plan.PLAN_COLUMNS))
            self.assertEqual(len(rows), 1)
            self.assertIn("T7-SHIELD", rows[0]["source_volume"])
            self.assertIn("2000398934016", rows[0]["source_volume"])
            with open(res["report"], encoding="utf-8") as fh:
                self.assertIn("source_volume", fh.read())

    def test_zero_byte_junk_is_deletable_without_a_hash(self):
        from triage import plan
        with tempfile.TemporaryDirectory() as ws:
            self._mkrun(ws, "DriveOne", [
                {"path": "F:\\junk\\empty.tmp", "size": "0",
                 "class": "JUNK"},
            ])
            res = plan.build(ws, self._log())
            rows = list(read_csv_rows(res["plan_csv"], plan.PLAN_COLUMNS))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["verify"], "zero-byte")

if __name__ == "__main__":
    unittest.main(verbosity=2)
