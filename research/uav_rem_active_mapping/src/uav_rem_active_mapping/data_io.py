from __future__ import annotations

from pathlib import Path
import os
import tempfile
from typing import Any, Mapping

import numpy as np

from .contracts import DEFAULT_DATASET_SPEC, DatasetSpec, validate_sample


def durable_replace(temporary: Path, destination: Path) -> None:
    """Flush file contents and the rename before reporting persistence."""
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(destination)
    directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_text(destination: str | Path, text: str) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=".write_", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if temporary.read_text(encoding="utf-8") != text:
            raise OSError("写入内容与读回内容不一致")
        durable_replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def save_sample(
    path: str | Path,
    sample: Mapping[str, Any],
    spec: DatasetSpec = DEFAULT_DATASET_SPEC,
) -> Path:
    validate_sample(sample, spec)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".npz_", delete=False) as handle:
        temporary = Path(handle.name)
        np.savez_compressed(handle, **sample)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        load_sample(temporary, spec)  # Verify ZIP CRC and every member before publishing.
        durable_replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_sample(path: str | Path, spec: DatasetSpec = DEFAULT_DATASET_SPEC) -> dict[str, np.ndarray]:
    with np.load(Path(path), allow_pickle=False) as archive:
        sample = {key: archive[key] for key in archive.files}
    validate_sample(sample, spec)
    return sample
