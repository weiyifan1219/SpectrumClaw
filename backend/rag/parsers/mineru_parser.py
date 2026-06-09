"""MinerUParser — high-quality PDF parsing via MinerU (magic-pdf or Docker endpoint).

MinerU produces structured content_list.json with per-element type, bbox, content,
and assets. This parser converts MinerU output to SpectrumDocument.

Install: pip install magic-pdf  OR  set MINERU_ENDPOINT for Docker mode.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseDocumentParser, ParserConfig
from ..schemas.document import SpectrumDocument
from ..schemas.block import SpectrumContentBlock


class MinerUParser(BaseDocumentParser):
    name = "mineru"
    version = "1.0.0"

    def __init__(self):
        self._config = ParserConfig()
        self._endpoint = ""

    def configure(self, config: ParserConfig):
        self._config = config
        self._endpoint = os.getenv("MINERU_ENDPOINT", "")

    def configured(self) -> bool:
        if self._endpoint:
            return True
        try:
            import magic_pdf  # noqa
            return True
        except ImportError:
            return False

    def parse(self, file_path: str) -> SpectrumDocument:
        path = Path(file_path).resolve()
        doc_id = SpectrumDocument.make_doc_id(str(path))

        content_list = self._run_mineru(path)
        blocks = self._convert_to_blocks(content_list, doc_id, str(path))

        return SpectrumDocument(
            doc_id=doc_id,
            filename=path.name,
            source_path=str(path),
            blocks=blocks,
            metadata={
                "parser": self.name,
                "parser_version": self.version,
                "total_pages": max((b.page_idx for b in blocks), default=0),
            },
        )

    def _run_mineru(self, pdf_path: Path) -> list[dict]:
        """Run MinerU on a PDF, return the content_list JSON."""
        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="mineru_"))

        try:
            cached = self._load_cached_content_list(pdf_path)
            if cached is not None:
                return cached

            if self._endpoint:
                content_list = self._run_via_endpoint(pdf_path)
            else:
                content_list = self._run_via_cli(pdf_path, out_dir)
            self._write_cached_content_list(pdf_path, content_list)
            return content_list
        finally:
            # Clean up temp dir (parser output is saved separately by the pipeline)
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)

    def is_cached(self, file_path: str | Path) -> bool:
        """Return whether a valid MinerU content_list cache exists for this PDF."""
        return self._load_cached_content_list(Path(file_path)) is not None

    def _cache_root(self) -> Path:
        root = os.getenv("MINERU_CACHE_DIR")
        if root:
            return Path(root)
        return Path(__file__).resolve().parents[3] / "data" / "mineru_cache"

    def _cache_paths(self, pdf_path: Path) -> tuple[Path, Path]:
        doc_id = SpectrumDocument.make_doc_id(str(pdf_path.resolve()))
        doc_dir = self._cache_root() / doc_id
        return doc_dir / "content_list.json", doc_dir / "metadata.json"

    def _cache_metadata(self, pdf_path: Path) -> dict:
        stat = pdf_path.stat()
        return {
            "source_path": str(pdf_path.resolve()),
            "filename": pdf_path.name,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "parser": self.name,
            "parser_version": self.version,
            "parse_mode": os.getenv("MINERU_PARSE_MODE", "txt"),
        }

    def _load_cached_content_list(self, pdf_path: Path) -> list[dict] | None:
        if os.getenv("MINERU_CACHE_DISABLE") == "1":
            return None
        if os.getenv("MINERU_CACHE_REFRESH") == "1":
            return None

        content_path, meta_path = self._cache_paths(pdf_path)
        if not content_path.exists() or not meta_path.exists():
            return None

        try:
            metadata = json.loads(meta_path.read_text())
            expected = self._cache_metadata(pdf_path)
            for key in ("size", "mtime_ns", "parser", "parser_version", "parse_mode"):
                if metadata.get(key) != expected.get(key):
                    return None
            content = json.loads(content_path.read_text())
        except Exception:
            return None

        return content if isinstance(content, list) else None

    def _write_cached_content_list(self, pdf_path: Path, content_list: list[dict]) -> None:
        if os.getenv("MINERU_CACHE_DISABLE") == "1":
            return

        content_path, meta_path = self._cache_paths(pdf_path)
        content_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = self._cache_metadata(pdf_path)
        metadata["cached_at"] = datetime.now(timezone.utc).isoformat()

        tmp_content = content_path.with_suffix(".json.tmp")
        tmp_meta = meta_path.with_suffix(".json.tmp")
        tmp_content.write_text(json.dumps(content_list, ensure_ascii=False), encoding="utf-8")
        tmp_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_content.replace(content_path)
        tmp_meta.replace(meta_path)

    def _run_via_cli(self, pdf_path: Path, out_dir: Path) -> list[dict]:
        """Run Magic-PDF via CLI with local models. Uses txt mode (no OCR/table)."""
        import shutil, os
        conda_bin = os.path.dirname(sys.executable)
        env = os.environ.copy()
        env["PATH"] = f"{conda_bin}:{env.get('PATH', '')}"

        # libGL for OpenCV (conda env). Keep existing server paths intact.
        conda_lib = str(Path(sys.executable).resolve().parents[1] / "lib")
        mesa_lib = "/opt/nvidia/nsight-compute/2023.1.0/host/linux-desktop-glibc_2_11_3-x64/Mesa"
        env["LD_LIBRARY_PATH"] = ":".join(
            p for p in [conda_lib, mesa_lib, env.get("LD_LIBRARY_PATH", "")] if p
        )
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_HUB_OFFLINE"] = "1"

        magic_pdf_bin = shutil.which("magic-pdf", path=env["PATH"])
        if not magic_pdf_bin:
            raise RuntimeError("magic-pdf not found. Install: pip install magic-pdf")

        mode = os.getenv("MINERU_PARSE_MODE", "txt")
        timeout = int(os.getenv("MINERU_TIMEOUT_SECONDS", "1200"))
        cmd = [magic_pdf_bin, "-p", str(pdf_path), "-o", str(out_dir), "-m", mode]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
            if result.returncode != 0:
                stderr_tail = result.stderr[-800:] if result.stderr else ""
                raise RuntimeError(
                    f"MinerU failed (exit {result.returncode}). "
                    f"Details: {stderr_tail[:400]}\n"
                    f"Hints: ensure models are downloaded and GPU is available. "
                    f"For CPU-only, use '-b pipeline' with magic-pdf."
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"MinerU timed out ({timeout}s limit) — file may be too large")

        # Find output files
        cl_path = None
        md_path = None
        for root, _, files in os.walk(out_dir):
            for f in files:
                fp = Path(root) / f
                if fp.name.endswith("_content_list.json") or fp.name == "content_list.json":
                    cl_path = fp
                if fp.suffix == ".md":
                    md_path = fp

        if cl_path is None:
            # Check for mineru output format
            for root, _, files in os.walk(out_dir):
                for f in files:
                    if f.endswith(".json"):
                        fp = Path(root) / f
                        try:
                            data = json.loads(fp.read_text())
                            if isinstance(data, list) and len(data) > 0:
                                cl_path = fp
                                break
                        except Exception:
                            continue

        if cl_path is None:
            found = []
            for root, _, files in os.walk(out_dir):
                found.extend(files)
            raise RuntimeError(
                f"MinerU produced no content_list.json. Output files: {found[:20]}"
            )

        return json.loads(cl_path.read_text())

    def _run_via_endpoint(self, pdf_path: Path) -> list[dict]:
        """Send PDF to MinerU Docker endpoint via HTTP."""
        import httpx
        with open(pdf_path, "rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            resp = httpx.post(
                self._endpoint,
                files=files,
                timeout=int(os.getenv("MINERU_TIMEOUT_SECONDS", "1200")),
            )
            resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if "content_list" in data:
            return data["content_list"]
        return data  # assume the response IS the content_list

    def _convert_to_blocks(self, content_list: list[dict], doc_id: str, source_path: str) -> list[SpectrumContentBlock]:
        """Convert MinerU content_list items to SpectrumContentBlocks.

        MinerU format:
        {
            "type": "text" | "table" | "image" | "equation" | "page_number" | ...,
            "text": "...",
            "bbox": [x1, y1, x2, y2],
            "page_idx": 0,
            "image_path": "images/xxx.png",  # relative to output dir
            "table_caption": [...],
            "table_footnote": [...],
        }
        """
        blocks = []
        for item in content_list:
            btype = item.get("type", "text")
            # skip page numbers and boilerplate
            if btype in ("page_number",):
                continue

            # MinerU uses "text" for text content
            text = item.get("text", "")

            # image_path in MinerU refers to an extracted image file
            asset_path = item.get("image_path", item.get("img_path", ""))

            caption_raw = item.get("table_caption", item.get("caption", []))
            if isinstance(caption_raw, str):
                caption_raw = [caption_raw] if caption_raw else []
            footnote_raw = item.get("table_footnote", item.get("footnote", []))

            page_idx = item.get("page_idx", 0) + 1  # MinerU uses 0-based pages
            bbox = item.get("bbox")

            block = SpectrumContentBlock.create(
                doc_id=doc_id,
                source_path=source_path,
                page_idx=page_idx,
                block_type=btype,
                raw_content=text,
                content=text,
                caption=caption_raw,
                bbox=bbox,
                asset_path=asset_path,
                parser_name="mineru",
                parser_version=self.version,
                metadata={
                    "parser": "mineru",
                    "source_type": btype,
                },
            )
            # extra fields
            if footnote_raw:
                block.footnote = footnote_raw if isinstance(footnote_raw, list) else [footnote_raw]

            blocks.append(block)

        return blocks
