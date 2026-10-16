#!/usr/bin/env python3
"""Check durable writes before spending GPU time. Never suppress fsync errors."""
import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".storage_check_", dir=args.directory) as name:
            root = Path(name)
            hashes = {}
            for index in range(4):
                payload = os.urandom(1024 * 1024)
                temporary = root / f"{index}.tmp"
                with temporary.open("wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                destination = root / f"{index}.bin"
                temporary.replace(destination)
                hashes[destination] = hashlib.sha256(payload).digest()
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            time.sleep(3)
            for path, expected in hashes.items():
                if hashlib.sha256(path.read_bytes()).digest() != expected:
                    raise OSError("读回校验和不匹配")
        print(json.dumps({"ok": True, "directory": str(args.directory), "bytes_verified": 4*1024*1024}))
        return 0
    except OSError as error:
        print(json.dumps({"ok": False, "directory": str(args.directory), "errno": error.errno, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
