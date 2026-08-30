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
        allowed = {"classify.py": 1, "report.py": 1, "util.py": 1}
        for fn, src in self._sources():
            removes = src.count("os.remove(") + src.count("os.rename(") \
                + src.count("os.unlink(")
            self.assertLessEqual(
                removes, allowed.get(fn, 0),
                f"{fn} contains unexpected delete/rename calls")


if __name__ == "__main__":
    unittest.main(verbosity=2)
