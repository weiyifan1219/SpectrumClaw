"""Abstract parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SpectrumDocument


class BaseDocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> SpectrumDocument:
        """Parse a document file into a SpectrumDocument."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable parser name."""
        ...
