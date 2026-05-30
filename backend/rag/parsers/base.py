"""Abstract parser interface with versioning and fallback support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..schemas.document import SpectrumDocument


@dataclass
class ParserConfig:
    save_assets: bool = True
    enable_table: bool = True
    enable_equation: bool = True
    enable_ocr: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDocumentParser(ABC):
    """Abstract parser. Subclasses implement `parse()` and return SpectrumDocument."""

    @abstractmethod
    def parse(self, file_path: str) -> SpectrumDocument: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def version(self) -> str:
        return "1.0.0"

    def can_handle(self, file_path: str) -> bool:
        """Override to restrict file types."""
        return file_path.lower().endswith(".pdf")

    def configured(self) -> bool:
        """Check whether this parser's dependencies are installed."""
        return True


class ParserFactory:
    """Select parser by name with automatic fallback."""

    _registry: dict[str, type[BaseDocumentParser]] = {}

    @classmethod
    def register(cls, name: str, parser_cls: type[BaseDocumentParser]):
        cls._registry[name] = parser_cls

    @classmethod
    def create(cls, name: str, config: ParserConfig | None = None) -> BaseDocumentParser | None:
        cfg = config or ParserConfig()
        if name in cls._registry:
            inst = cls._registry[name]()
            if hasattr(inst, 'configure'):
                inst.configure(cfg)
            return inst
        return None

    @classmethod
    def create_with_fallback(cls, primary: str, fallback: str,
                              config: ParserConfig | None = None) -> BaseDocumentParser:
        """Create primary parser, falling back if unavailable."""
        p = cls.create(primary, config)
        if p is not None and p.configured():
            return p
        f = cls.create(fallback, config)
        if f is not None:
            return f
        raise RuntimeError(f"No available parser (tried {primary}, {fallback})")

    @classmethod
    def list_available(cls) -> list[str]:
        out = []
        for name, pcls in cls._registry.items():
            try:
                inst = pcls()
                if inst.configured():
                    out.append(name)
            except Exception:
                pass
        return out
