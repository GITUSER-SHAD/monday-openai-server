"""Synthetic fixture drives for end-to-end tests.

Builds two 'external drives' + a fake D: reference set exercising every
classification path: media (client + personal, active + legacy), records,
archive boxes (backup-named, profile markers, version store), junk,
duplicates (within-drive, cross-drive, vs D:), git repos, and unknowns.
"""

import hashlib
import os
import time


def _w(root, rel, content=b"", mtime=None):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


OLD = time.mktime((2019, 5, 1, 12, 0, 0, 0, 0, -1))
RECENT = time.time() - 30 * 86400

DUP_CONTENT = b"duplicate-within-e " * 5000        # ~95KB > 64KB prefix
DUPJ_CONTENT = b"keepme-junkdir-pair " * 4000      # 80KB identical pair
XDUP_CONTENT = b"cross-drive duplicate " * 4000    # ~88KB
DREF_CONTENT = b"identical to D reference " * 4000  # ~100KB
BIG_A = b"A" * (80 * 1024) + b"tail-one"           # same size,
BIG_B = b"B" * (80 * 1024) + b"tail-two"           # different prefix


def build_drive_e(root):
    # media: active client project
    _w(root, "Shoots/2023 Acme Rebrand/RAW/A001.CR2",
       b"raw-photo-bytes-1", RECENT)
    _w(root, "Shoots/2023 Acme Rebrand/Exports/final_v2.mp4",
       b"export-bytes-1", RECENT)
    # media: legacy personal shoot
    _w(root, "Family/Vacation 2019/IMG_1001.JPG", b"jpeg-bytes-1", OLD)
    # records
    _w(root, "paperwork/invoice_2023-04-15_acme_$1200.pdf",
       b"%PDF-1.4 invoice", OLD)
    _w(root, "paperwork/scan receipt 20220301.jpg", b"jpeg-receipt", OLD)
    _w(root, "docs/randomnotes.txt", b"misc notes", OLD)
    # duplicates
    _w(root, "stuff/dup1.bin", DUP_CONTENT, OLD)
    _w(root, "stuff/copies/dup1 copy.bin", DUP_CONTENT, OLD)
    _w(root, "stuff/xdup.bin", XDUP_CONTENT, OLD)
    _w(root, "stuff/dref.bin", DREF_CONTENT, OLD)
    # same size, different content: prefix filter must stop full hashing
    _w(root, "pair/bigA.bin", BIG_A, OLD)
    # junk
    _w(root, "Downloads/setup_v1.2.3_x64.exe", b"MZ fake installer", OLD)
    _w(root, "cache/tempfile.tmp", b"temp", OLD)
    _w(root, "photos-misc/Thumbs.db", b"thumbcache", OLD)
    _w(root, "empty.txt", b"", OLD)
    # archive box: backup-named with profile markers; letter.doc is a
    # sole survivor, junk.dat sits under AppData (potential sole survivor)
    _w(root, "OldLaptopBackup/Users/jason/Documents/letter.doc",
       b"important letter", OLD)
    _w(root, "OldLaptopBackup/Users/jason/AppData/Local/junk.dat",
       b"app junk", OLD)
    _w(root, "OldLaptopBackup/Users/jason/NTUSER.DAT", b"registry", OLD)
    # version store box (WD-style History)
    for stamp in ("2019_03_22 18_30_00", "2019_04_01 09_00_00",
                  "2019_05_10 11_15_00"):
        _w(root, f"SomeFolder/History/report ({stamp} UTC).docx",
           b"versioned " + stamp.encode(), OLD)
    # git repo
    _w(root, "code/myproj/.git/config", b"[core]", OLD)
    _w(root, "code/myproj/src/main.py", b"print('hi')", OLD)
    # unknown
    _w(root, "weird/data.xyz", b"\x00\x01\x02unknown", OLD)
    # sentinel with a globally unique size: must never be hashed at all
    _w(root, "unique/sentinel.bin", b"U" * 7777, OLD)
    # keeper-vs-junk: identical pair, one copy inside a cache dir - the
    # cache copy must be the DUPE, and the kept copy must never be junked
    _w(root, "cache/dupJ.bin", DUPJ_CONTENT, OLD)
    _w(root, "keep/dupJ.bin", DUPJ_CONTENT, OLD)
    # real media dumped in a temp-named dir: not junk
    _w(root, "temp/real_footage.mov", b"real-footage-in-temp-dir-00001", OLD)
    # 'Personnel' must not trigger the 'personal' shoot keyword
    _w(root, "Shoots/2022 Personnel Training/video.mp4",
       b"personnel-training-video-00001x", OLD)
    # same-named camera files in different card folders of an active project
    _w(root, "Shoots/2023 Acme Rebrand/RAW/card1/A002.CR2",
       b"raw-card1-bytes-0001", RECENT)
    _w(root, "Shoots/2023 Acme Rebrand/RAW/card2/A002.CR2",
       b"raw-card2-bytes-00001", RECENT)
    # ordinary '(N)' copy-number files inside a generic History dir must NOT
    # box the whole tree (only timestamped/backup-tool stores count)
    for i in (1, 2, 3):
        _w(root, f"Stuff2/History/photo ({i}).jpg",
           b"copynum-photo-" + bytes([48 + i]) * (10 + i), OLD)
    # loose file at drive root
    _w(root, "LooseClip.mov", b"loose-clip-at-root-bytes-000001", OLD)


def build_drive_f(root):
    _w(root, "transfer/xdup.bin", XDUP_CONTENT, OLD)   # cross-drive dupe
    _w(root, "2020 Beach Shoot/clip.mov", b"mov-bytes-beach", OLD)
    _w(root, "pair/bigB.bin", BIG_B, OLD)              # size-collides w/ bigA
    _w(root, "empty2.txt", b"", OLD)


def build_d_reference(d_root, csv_path, with_hashes=True):
    """Create the fake D: drive file + its inventory CSV (foreign format)."""
    p = _w(d_root, "Media/2021/Legacy/dref.bin", DREF_CONTENT, OLD)
    sha = hashlib.sha256(DREF_CONTENT).hexdigest()
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        if with_hashes:
            fh.write("FullName;Length;SHA256\n")
            fh.write(f"{p};{len(DREF_CONTENT)};{sha}\n")
            fh.write(f"{d_root}\\other.bin;12345;{'0' * 64}\n")
        else:
            fh.write("FullName;Length\n")
            fh.write(f"{p};{len(DREF_CONTENT)}\n")
    return p, sha
