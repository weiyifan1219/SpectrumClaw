"""GPU-accelerated MinerU preparse worker.

Uses MinerU Python API directly instead of CLI subprocess. The model is loaded
once into GPU memory and reused across all PDFs, eliminating the ~100s model
reload overhead per file.

Compatible with the same cache format as preparse_mineru.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_pdf_paths(directory: str | None, file_path: str | None) -> list[str]:
    if file_path:
        return [str(Path(file_path))]
    root = Path(directory) if directory else PROJECT_ROOT / "data" / "knowledge_base" / "raw"
    return sorted(str(p) for p in root.glob("*.pdf"))


def _shard(paths: list[str], shards: int, shard_index: int) -> list[str]:
    if shards <= 0:
        raise ValueError("--shards must be >= 1")
    if shard_index < 0 or shard_index >= shards:
        raise ValueError("--shard-index must be in [0, shards)")
    return [p for i, p in enumerate(paths) if i % shards == shard_index]


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _cache_root() -> Path:
    root = os.getenv("MINERU_CACHE_DIR")
    if root:
        return Path(root)
    return PROJECT_ROOT / "data" / "mineru_cache"


def _make_doc_id(path: str) -> str:
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()[:12]


def _is_cached(pdf_path: str) -> bool:
    doc_id = _make_doc_id(str(Path(pdf_path).resolve()))
    content_path = _cache_root() / doc_id / "content_list.json"
    meta_path = _cache_root() / doc_id / "metadata.json"
    if not content_path.exists() or not meta_path.exists():
        return False
    if os.getenv("MINERU_CACHE_REFRESH") == "1":
        return False
    try:
        meta = json.loads(meta_path.read_text())
        stat = Path(pdf_path).stat()
        if meta.get("size") != stat.st_size or meta.get("mtime_ns") != stat.st_mtime_ns:
            return False
        return True
    except Exception:
        return False


def _write_cache(pdf_path: str, content_list: list) -> None:
    from datetime import datetime, timezone
    resolved = str(Path(pdf_path).resolve())
    doc_id = _make_doc_id(resolved)
    doc_dir = _cache_root() / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    stat = Path(pdf_path).stat()
    metadata = {
        "source_path": resolved,
        "filename": Path(pdf_path).name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "parser": "mineru",
        "parser_version": "1.0.0",
        "parse_mode": os.getenv("MINERU_PARSE_MODE", "txt"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "gpu_accelerated": True,
    }

    content_path = doc_dir / "content_list.json"
    meta_path = doc_dir / "metadata.json"
    tmp_content = content_path.with_suffix(".json.tmp")
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_content.write_text(json.dumps(content_list, ensure_ascii=False), encoding="utf-8")
    tmp_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_content.replace(content_path)
    tmp_meta.replace(meta_path)


def _process_single_pdf(pdf_path: str) -> list:
    """Process a single PDF using MinerU Python API with persistent model."""
    from magic_pdf.data.read_api import read_local_pdfs
    from magic_pdf.data.data_reader_writer import FileBasedDataWriter
    from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
    from magic_pdf.config.enums import SupportedPdfParseMethod
    from magic_pdf.config.make_content_config import DropMode
    import tempfile

    datasets = read_local_pdfs(pdf_path)
    if not datasets:
        raise RuntimeError(f"Failed to read PDF: {pdf_path}")

    dataset = datasets[0]
    parse_method = dataset.classify()

    use_ocr = parse_method != SupportedPdfParseMethod.TXT
    infer_result = doc_analyze(dataset, ocr=use_ocr, show_log=False)

    with tempfile.TemporaryDirectory(prefix="mineru_img_") as tmp_dir:
        image_writer = FileBasedDataWriter(tmp_dir)
        if use_ocr:
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        else:
            pipe_result = infer_result.pipe_txt_mode(image_writer)

        content_list = pipe_result.get_content_list(
            image_dir_or_bucket_prefix="",
            drop_mode=DropMode.NONE,
        )

    if isinstance(content_list, str):
        content_list = json.loads(content_list)

    return content_list


def main() -> int:
    ap = argparse.ArgumentParser(description="GPU-accelerated MinerU preparse")
    ap.add_argument("--dir", type=str, help="Directory containing PDFs")
    ap.add_argument("--file", type=str, help="Single PDF to preparse")
    ap.add_argument("--limit", type=int, help="Limit selected files after sharding")
    ap.add_argument("--shards", type=int, default=1, help="Total shard count")
    ap.add_argument("--shard-index", type=int, default=0, help="This worker shard index")
    ap.add_argument("--force", action="store_true", help="Refresh cache even if valid")
    ap.add_argument("--gpu", type=int, default=None, help="GPU device index")
    args = ap.parse_args()

    if args.force:
        os.environ["MINERU_CACHE_REFRESH"] = "1"
    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HOME", str(PROJECT_ROOT / ".cache" / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(PROJECT_ROOT / ".cache" / "huggingface" / "hub"))

    all_paths = _resolve_pdf_paths(args.dir, args.file)
    paths = _shard(all_paths, args.shards, args.shard_index)
    if args.limit:
        paths = paths[:args.limit]

    started = time.time()
    summary = {"selected": len(paths), "cached": 0, "parsed": 0, "failed": 0}

    _emit({
        "event": "worker_start",
        "worker": args.shard_index,
        "shards": args.shards,
        "selected": len(paths),
        "total": len(all_paths),
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
        "cache_dir": str(_cache_root()),
        "mode": "gpu_python_api",
    })

    # Warm up model on first call — subsequent calls reuse ModelSingleton
    _emit({"event": "model_loading", "worker": args.shard_index})
    model_start = time.time()
    try:
        from magic_pdf.model.doc_analyze_by_custom_model import custom_model_init
        custom_model_init(ocr=False, show_log=False)
        _emit({
            "event": "model_loaded",
            "worker": args.shard_index,
            "seconds": round(time.time() - model_start, 2),
        })
    except Exception as exc:
        _emit({
            "event": "model_load_failed",
            "worker": args.shard_index,
            "error": str(exc)[:500],
        })
        return 1

    for offset, path in enumerate(paths, start=1):
        filename = Path(path).name
        if not args.force and _is_cached(path):
            summary["cached"] += 1
            if offset % 50 == 0:
                _emit({
                    "event": "progress",
                    "worker": args.shard_index,
                    "offset": offset,
                    "selected": len(paths),
                    "cached": summary["cached"],
                    "parsed": summary["parsed"],
                    "failed": summary["failed"],
                })
            continue

        file_started = time.time()
        try:
            content_list = _process_single_pdf(path)
            _write_cache(path, content_list)
            elapsed = round(time.time() - file_started, 2)
            summary["parsed"] += 1
            _emit({
                "event": "file_parsed",
                "worker": args.shard_index,
                "offset": offset,
                "selected": len(paths),
                "file": filename,
                "blocks": len(content_list),
                "seconds": elapsed,
            })
        except Exception as exc:
            elapsed = round(time.time() - file_started, 2)
            summary["failed"] += 1
            _emit({
                "event": "file_failed",
                "worker": args.shard_index,
                "offset": offset,
                "selected": len(paths),
                "file": filename,
                "seconds": elapsed,
                "error": str(exc)[:1000],
            })

    summary["seconds"] = round(time.time() - started, 2)
    _emit({"event": "worker_complete", "worker": args.shard_index, **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
