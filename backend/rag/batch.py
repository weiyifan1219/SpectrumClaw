"""Batch document processing — aligned with RAG-Anything BatchMixin.

Concurrent multi-file processing via asyncio with configurable parallelism.
Matches raganything/batch.py and raganything/batch_parser.py patterns.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pipeline import PipelineResult


@dataclass
class BatchResult:
    total_files: int = 0
    succeeded: int = 0
    failed: int = 0
    total_text_blocks: int = 0
    total_multimodal: int = 0
    total_entities: int = 0
    total_relations: int = 0
    errors: list[dict] = field(default_factory=list)
    per_file: list[PipelineResult] = field(default_factory=list)


async def process_batch(
    file_paths: list[str],
    processor: Any,  # DocumentProcessor
    max_concurrent: int = 3,
    progress_callback=None,
) -> BatchResult:
    """Process multiple documents concurrently with semaphore control.

    Matches RAG-Anything's BatchMixin.process_folder() pattern:
    - Semaphore-based concurrency limiting
    - Per-file error isolation (one failure doesn't block others)
    - Progress tracking via callback
    """
    result = BatchResult(total_files=len(file_paths))
    sem = asyncio.Semaphore(max_concurrent)

    async def _process_one(file_path: str, index: int) -> PipelineResult:
        async with sem:
            if progress_callback:
                progress_callback(index, len(file_paths), Path(file_path).name)
            return await processor.process_document(file_path)

    tasks = [_process_one(fp, i) for i, fp in enumerate(file_paths)]
    per_file = await asyncio.gather(*tasks, return_exceptions=True)

    for i, r in enumerate(per_file):
        if isinstance(r, Exception):
            result.failed += 1
            result.errors.append({"file": file_paths[i], "error": str(r)})
        elif r.errors:
            result.failed += 1
            result.errors.append({"file": file_paths[i], "errors": r.errors})
        else:
            result.succeeded += 1
            result.total_text_blocks += r.text_blocks
            result.total_multimodal += r.multimodal_items
            result.total_entities += r.entities_added
            result.total_relations += r.relations_added
            result.per_file.append(r)

    return result


def batch_process_folder(
    folder: str | Path,
    processor: Any,
    extensions: tuple = (".pdf",),
    max_concurrent: int = 3,
    recursive: bool = False,
) -> BatchResult:
    """Process all files in a folder synchronously.

    Matches RAG-Anything's batch_process_folder().
    """
    folder = Path(folder)
    if recursive:
        files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in extensions)
    else:
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in extensions)

    return asyncio.run(process_batch(
        file_paths=[str(f) for f in files],
        processor=processor,
        max_concurrent=max_concurrent,
    ))
