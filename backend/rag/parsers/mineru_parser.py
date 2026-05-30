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
        path = Path(file_path)
        doc_id = SpectrumDocument.make_doc_id(file_path)

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
            if self._endpoint:
                return self._run_via_endpoint(pdf_path)
            else:
                return self._run_via_cli(pdf_path, out_dir)
        finally:
            # Clean up temp dir (parser output is saved separately by the pipeline)
            if out_dir.exists():
                shutil.rmtree(out_dir, ignore_errors=True)

    def _run_via_cli(self, pdf_path: Path, out_dir: Path) -> list[dict]:
        """Run MinerU via mineru CLI. Falls back to magic-pdf."""
        import shutil
        mineru_bin = shutil.which("mineru")
        magic_pdf = shutil.which("magic-pdf")

        if not mineru_bin and not magic_pdf:
            raise RuntimeError(
                "MinerU not found. Install: pip install mineru magic-pdf\n"
                "MinerU also requires model files and GPU for full functionality."
            )

        # Try mineru CLI first (handles models auto)
        if mineru_bin:
            cmd = [
                mineru_bin, "-p", str(pdf_path), "-o", str(out_dir),
                "-b", "pipeline",
            ]
        else:
            cmd = [
                magic_pdf, "-p", str(pdf_path), "-o", str(out_dir),
                "-m", "auto",
            ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                stderr_tail = result.stderr[-800:] if result.stderr else ""
                raise RuntimeError(
                    f"MinerU failed (exit {result.returncode}). "
                    f"Details: {stderr_tail[:400]}\n"
                    f"Hints: ensure models are downloaded and GPU is available. "
                    f"For CPU-only, use '-b pipeline' with magic-pdf."
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError("MinerU timed out (600s limit) — file may be too large")

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
                timeout=600,
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
