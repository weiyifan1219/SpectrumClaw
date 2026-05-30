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
        """Run MinerU CLI: magic-pdf or pdf-parse."""
        # Try magic-pdf first
        cmd = [
            sys.executable, "-m", "magic_pdf", "parse",
            str(pdf_path), "--output-dir", str(out_dir),
            "--method", "auto",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback: try pdf-parse (older MinerU entry point)
            cmd2 = [sys.executable, "-m", "magic_pdf.cli", str(pdf_path), str(out_dir)]
            try:
                subprocess.run(cmd2, check=True, capture_output=True, text=True, timeout=300)
            except Exception as exc:
                raise RuntimeError(f"MinerU CLI failed: {exc}") from exc

        # Find content_list.json in output
        cl_path = None
        for root, _, files in os.walk(out_dir):
            if "content_list.json" in files:
                cl_path = Path(root) / "content_list.json"
                break

        if cl_path is None:
            raise RuntimeError("MinerU did not produce content_list.json")

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
