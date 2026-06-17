"""PDF deduplication — move content-identical files to a duplicates folder.

Compares full-file MD5 hashes. Keeps one file per unique hash (prefers the
filename with the highest version number, then longest name as tiebreaker).
Moved duplicates go to data/knowledge_base/duplicates/ for manual review.

Usage (run on server):
    python scripts/dedup_pdfs.py                      # dry-run (report only)
    python scripts/dedup_pdfs.py --execute            # actually move files
    python scripts/dedup_pdfs.py --dir /custom/path   # custom PDF directory
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def extract_version(name: str) -> int:
    m = re.search(r"-(\d+)-\d{6}", name)
    return int(m.group(1)) if m else -1


def pick_keeper(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: (extract_version(p.name), len(p.name)))


def main():
    ap = argparse.ArgumentParser(description="Deduplicate PDFs by content MD5")
    ap.add_argument("--dir", type=str, help="PDF directory")
    ap.add_argument("--execute", action="store_true", help="Actually move duplicates (default: dry-run)")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    pdf_dir = Path(args.dir) if args.dir else project_root / "data" / "knowledge_base" / "raw"
    dup_dir = pdf_dir.parent / "duplicates"

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    print(f"Scanning {len(pdfs)} PDFs in {pdf_dir} ...")

    hash_groups: dict[str, list[Path]] = defaultdict(list)
    for i, p in enumerate(pdfs):
        h = md5_file(p)
        hash_groups[h].append(p)
        if (i + 1) % 200 == 0:
            print(f"  hashed {i + 1}/{len(pdfs)}")

    dup_groups = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}
    total_dups = sum(len(paths) - 1 for paths in dup_groups.values())

    print(f"\nResults:")
    print(f"  Total files: {len(pdfs)}")
    print(f"  Unique content hashes: {len(hash_groups)}")
    print(f"  Duplicate groups: {len(dup_groups)}")
    print(f"  Files to remove: {total_dups}")
    print(f"  Files to keep: {len(pdfs) - total_dups}")

    if not dup_groups:
        print("\nNo duplicates found.")
        return

    print(f"\nDuplicate groups:")
    to_move = []
    for h, paths in sorted(dup_groups.items(), key=lambda x: -len(x[1])):
        keeper = pick_keeper(paths)
        removals = [p for p in paths if p != keeper]
        to_move.extend(removals)
        print(f"  [{len(paths)} copies] keep: {keeper.name}")
        for r in removals:
            print(f"    remove: {r.name}")

    if not args.execute:
        print(f"\n[DRY RUN] Would move {len(to_move)} files to {dup_dir}/")
        print("Re-run with --execute to actually move them.")
        return

    dup_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for p in to_move:
        dest = dup_dir / p.name
        if dest.exists():
            dest = dup_dir / f"{p.stem}_dup{moved}{p.suffix}"
        shutil.move(str(p), str(dest))
        moved += 1

    print(f"\nMoved {moved} duplicate files to {dup_dir}/")
    print(f"Remaining PDFs: {len(pdfs) - moved}")


if __name__ == "__main__":
    main()
