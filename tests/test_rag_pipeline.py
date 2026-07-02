"""Minimal RAG pipeline tests — parser fallback, DocumentProcessor, Chroma, RAG query."""

import json
import os
import sys
import asyncio
from types import ModuleType
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestParserFallback:
    def test_pypdf_parser_always_available(self):
        from backend.rag.parsers import create_parser
        p = create_parser("pypdf", "pypdf")
        assert p.name == "pypdf"
        assert p.configured()

    def test_parser_fallback_when_unavailable(self):
        from backend.rag.parsers import create_parser
        # none parser doesn't exist, should fall back to pypdf
        p = create_parser("nonexistent_parser", "pypdf")
        assert p.name == "pypdf"

    def test_parser_factory_lists_available(self):
        from backend.rag.parsers import ParserFactory
        available = ParserFactory.list_available()
        assert "pypdf" in available


class TestContentSeparation:
    def test_separate_text_from_multimodal(self):
        from backend.rag.processor import separate_content
        from backend.rag.schemas.block import SpectrumContentBlock
        blocks = [
            SpectrumContentBlock.create("d1", "f.pdf", 1, "text", "hello"),
            SpectrumContentBlock.create("d1", "f.pdf", 1, "table", "a|b"),
            SpectrumContentBlock.create("d1", "f.pdf", 2, "image", "", content="img"),
            SpectrumContentBlock.create("d1", "f.pdf", 2, "text", "world"),
            SpectrumContentBlock.create("d1", "f.pdf", 3, "equation", "E=mc2"),
            SpectrumContentBlock.create("d1", "f.pdf", 3, "footnote", "5.340 note"),
        ]
        text, multi = separate_content(blocks)
        assert len(text) == 2
        assert len(multi) == 4
        assert all(b.block_type in ("text", "title") for b in text)
        assert all(b.block_type not in ("text", "title") for b in multi)


class TestSchemas:
    def test_block_v2_create(self):
        from backend.rag.schemas.block import SpectrumContentBlock
        b = SpectrumContentBlock.create("d1", "f.pdf", 1, "text", "hello",
                                         parser_name="pypdf", parser_version="2.0")
        assert b.block_id
        assert b.content_hash
        assert b.parser_name == "pypdf"

    def test_block_v1_upgrade(self):
        from backend.rag.schemas.block import SpectrumContentBlock
        d = {"block_id": "abc", "doc_id": "x", "source_path": "f.pdf",
             "page_idx": 3, "block_type": "text", "content": "test",
             "enhanced_content": "enhanced", "caption": "cap",
             "section_path": ["s1"], "metadata": {"parser": "pypdf"}}
        b = SpectrumContentBlock.from_v1_dict(d)
        assert b.block_id == "abc"
        assert b.content == "test"
        assert b.parser_name == "pypdf"
        assert b.caption == ["cap"]

    def test_document_from_dict_auto_upgrade(self):
        from backend.rag.schemas.document import SpectrumDocument
        d = {"doc_id": "d1", "filename": "f.pdf", "source_path": "/tmp/f.pdf",
             "blocks": [{"block_id": "b1", "doc_id": "d1", "source_path": "/tmp/f.pdf",
                          "page_idx": 1, "block_type": "text", "content": "hello"}]}
        doc = SpectrumDocument.from_dict(d)
        assert doc.doc_id == "d1"
        assert len(doc.blocks) == 1

    def test_materialize_mineru_assets_persists_cache_files(self, tmp_path):
        from backend.rag.parsers.mineru_parser import materialize_mineru_assets

        asset_root = tmp_path / "mineru_out"
        image_dir = asset_root / "images"
        image_dir.mkdir(parents=True)
        source_asset = image_dir / "figure_1.png"
        source_asset.write_bytes(b"png")

        cache_doc_dir = tmp_path / "cache_doc"
        content, changed, missing = materialize_mineru_assets(
            [{"type": "image", "image_path": "images/figure_1.png"}],
            cache_doc_dir=cache_doc_dir,
            asset_root=asset_root,
        )

        cached_asset = cache_doc_dir / "assets" / "images" / "figure_1.png"
        assert changed is True
        assert missing == 0
        assert cached_asset.exists()
        assert content[0]["image_path"] == str(cached_asset.resolve())

    def test_mineru_cache_invalidates_missing_assets(self, tmp_path, monkeypatch):
        import backend.rag.parsers.mineru_parser as mineru_parser

        pdf_path = tmp_path / "sample.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 sample")

        cache_root = tmp_path / "mineru_cache"
        monkeypatch.setenv("MINERU_CACHE_DIR", str(cache_root))

        parser = mineru_parser.MinerUParser()
        doc_dir = parser._cache_doc_dir(pdf_path)
        doc_dir.mkdir(parents=True)
        (doc_dir / "content_list.json").write_text(
            json.dumps([{"type": "image", "image_path": "assets/missing.png"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (doc_dir / "metadata.json").write_text(
            json.dumps(parser._cache_metadata(pdf_path), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        assert parser._load_cached_content_list(pdf_path) is None


class TestFrequencyMatcher:
    def test_build_vlm_client_prefers_local_model(self, tmp_path, monkeypatch):
        from backend.rag.multimodal import build_vlm_client, LocalQwen2VLClient

        model_dir = tmp_path / "MinerU2.5-Pro-2605-1.2B"
        model_dir.mkdir()
        monkeypatch.setenv("QWEN_VL_MODE", "local")
        monkeypatch.setenv("QWEN_VL_LOCAL_MODEL_PATH", str(model_dir))

        client = build_vlm_client()

        assert isinstance(client, LocalQwen2VLClient)
        assert client.configured is True

    def test_build_vlm_client_uses_api_when_requested(self, monkeypatch):
        from backend.rag.multimodal import build_vlm_client, QwenVLClient

        monkeypatch.setenv("QWEN_VL_MODE", "api")
        monkeypatch.setenv("QWEN_VL_API_KEY", "dummy-key")
        monkeypatch.setenv("QWEN_VL_BASE_URL", "http://127.0.0.1:9999/v1")
        monkeypatch.setenv("QWEN_VL_MODEL", "qwen-vl-test")

        client = build_vlm_client()

        assert isinstance(client, QwenVLClient)
        assert client.configured is True

    def test_describe_vlm_runtime_reports_local_mode(self, tmp_path, monkeypatch):
        from backend.rag.multimodal import describe_vlm_runtime

        model_dir = tmp_path / "MinerU2.5-Pro-2605-1.2B"
        model_dir.mkdir()
        monkeypatch.setenv("QWEN_VL_MODE", "local")
        monkeypatch.setenv("QWEN_VL_LOCAL_MODEL_PATH", str(model_dir))
        monkeypatch.delenv("QWEN_VL_API_KEY", raising=False)

        runtime = describe_vlm_runtime()

        assert runtime == {
            "configured": True,
            "mode": "local",
            "model": "MinerU2.5-Pro-2605-1.2B",
            "backend": "transformers",
        }

    def test_local_vlm_client_flattens_structured_content(self, tmp_path, monkeypatch):
        from backend.rag.multimodal import LocalQwen2VLClient

        model_dir = tmp_path / "MinerU2.5-Pro-2605-1.2B"
        model_dir.mkdir()

        class FakeImage:
            def convert(self, _mode):
                return self

        pil_module = ModuleType("PIL")
        pil_module.Image = SimpleNamespace(open=lambda _path: FakeImage())
        monkeypatch.setitem(sys.modules, "PIL", pil_module)

        client = LocalQwen2VLClient(model_path=str(model_dir))
        client._client = SimpleNamespace(
            two_step_extract=lambda _image: [
                {"type": "table", "content": {"rows": 2}},
                {"type": "text", "content": ["cell-a", "cell-b"]},
            ]
        )

        output = client._call_local(str(tmp_path / "unused.png"), "prompt")

        assert '[table] {"rows": 2}' in output
        assert "[text] cell-a\ncell-b" in output

    def test_equation_processor_uses_vlm_for_equation_assets(self, tmp_path):
        from backend.rag.processors.equation import EquationModalProcessor
        from backend.rag.schemas.block import SpectrumContentBlock

        asset = tmp_path / "equation.png"
        asset.write_bytes(b"png")

        class FakeVLM:
            configured = True

            async def describe_equation(self, image_path: str, **kwargs):
                return f"VLM equation summary for {kwargs.get('equation_text', '')}"

        block = SpectrumContentBlock.create(
            "d1",
            "f.pdf",
            1,
            "equation",
            r"\frac{C}{N}",
            asset_path=str(asset),
        )

        result = asyncio.run(EquationModalProcessor(vlm_client=FakeVLM()).process_async(block))

        assert result.modality_summary.startswith("VLM equation summary")
        assert "[Formula VLM]" in result.enhanced_content
        assert result.metadata["is_latex"] is True

    def test_image_processor_falls_back_when_asset_missing(self):
        from backend.rag.processors.image import ImageModalProcessor
        from backend.rag.schemas.block import SpectrumContentBlock

        class FakeVLM:
            configured = True

            async def describe_image(self, image_path: str, prompt: str = ""):
                raise AssertionError("missing assets should not call VLM")

        block = SpectrumContentBlock.create(
            "d1",
            "f.pdf",
            1,
            "image",
            "",
            asset_path="/tmp/does-not-exist.png",
            caption=["Figure 1"],
        )

        result = asyncio.run(ImageModalProcessor(vlm_client=FakeVLM()).process_async(block))

        assert result.modality_summary.startswith("[Image] Caption: Figure 1")

    def test_text_processor_extracts_single_frequency_without_crashing(self):
        from backend.rag.processors.text import TextModalProcessor
        from backend.rag.schemas.block import SpectrumContentBlock

        block = SpectrumContentBlock.create("d1", "f.pdf", 1, "text", "Mobile allocation at 3500 MHz")
        result = TextModalProcessor().process(block)

        assert "3500 MHz" in result.metadata["freq_ranges"]

    def test_exact_match(self):
        from backend.rag.keyword.frequency_matcher import FrequencyRangeMatcher
        fm = FrequencyRangeMatcher()
        r = fm.search("2300-2400 MHz", ["2300-2400 MHz band", "other text"])
        assert len(r) > 0
        assert r[0][1] == 1.0

    def test_overlap_match(self):
        from backend.rag.keyword.frequency_matcher import FrequencyRangeMatcher
        fm = FrequencyRangeMatcher()
        r = fm.search("2350 MHz", ["2300-2400 MHz band"], mode="overlap")
        assert len(r) > 0

    def test_band_alias(self):
        from backend.rag.keyword.frequency_matcher import FrequencyRangeMatcher
        fm = FrequencyRangeMatcher()
        r = fm.search("S-band radar", ["2-4 GHz allocation"])
        assert len(r) > 0


class TestQueryAnalyzer:
    def test_extract_frequency_and_region(self):
        from backend.rag.retrievers.query_analyzer import SpectrumQueryAnalyzer
        a = SpectrumQueryAnalyzer()
        qi = a.analyze("2300-2400 MHz 在 Region 3 能用于移动通信吗？")
        assert qi.frequency_range == "2300-2400 MHz"
        assert qi.region == "Region 3"
        assert qi.radio_service == "Mobile"

    def test_country_to_region(self):
        from backend.rag.retrievers.query_analyzer import SpectrumQueryAnalyzer
        a = SpectrumQueryAnalyzer()
        qi = a.analyze("日本 の周波数割り当て")
        assert qi.country == "日本"
        assert qi.region == "Region 3"


class TestPrompts:
    def test_prompt_registry(self):
        from backend.rag.prompts import PROMPTS
        assert "image_analysis" in PROMPTS
        assert "table_analysis" in PROMPTS
        assert "equation_analysis" in PROMPTS
        assert "query_image_description" in PROMPTS


class TestEmbeddings:
    def test_hash_embedding_is_stable_and_normalized(self):
        from backend.rag.embeddings.sentence_transformer import HashingEmbeddingProvider

        provider = HashingEmbeddingProvider(dimension=16)
        first = provider.embed_query("3500 MHz mobile allocation")
        second = provider.embed_query("3500 MHz mobile allocation")

        assert first == second
        assert len(first) == 16
        assert sum(v * v for v in first) == pytest.approx(1.0)


class TestDocRegistry:
    def test_register_and_check(self, tmp_path, monkeypatch):
        # Point registry to tmp_path to avoid polluting data/index/
        import backend.rag.doc_registry as dr
        monkeypatch.setattr(dr, "DOC_REGISTRY_PATH", tmp_path / "doc_registry.json")

        tf = tmp_path / "test.pdf"
        tf.write_bytes(b"%PDF-1.4 test content")
        doc_id = dr.register_doc(str(tf), parser_name="pypdf", parser_version="2.0")
        assert doc_id
        dr.update_status(doc_id, "indexed")
        assert dr.is_cached(str(tf), "pypdf", "2.0")
        assert not dr.is_cached(str(tf), "mineru", "1.0")

    def test_index_documents_updates_registry_with_registered_id(self, tmp_path, monkeypatch):
        import backend.rag.doc_registry as dr
        import backend.rag.ingest as ingest

        monkeypatch.setattr(dr, "DOC_REGISTRY_PATH", tmp_path / "doc_registry.json")
        tf = tmp_path / "test.pdf"
        tf.write_bytes(b"%PDF-1.4 test content")

        class FakeVectorStore:
            def count(self):
                return 1

            def clear(self):
                pass

        class FakeProcessor:
            parser = SimpleNamespace(name="pypdf", version="2.0")
            vector_store = FakeVectorStore()
            llm_chat = None

            async def process_document(self, file_path):
                return SimpleNamespace(
                    doc_id="path-derived-doc-id",
                    text_blocks=1,
                    multimodal_items=0,
                    entities_added=0,
                    relations_added=0,
                    errors=[],
                )

        monkeypatch.setattr(ingest, "_build_doc_processor", lambda: FakeProcessor())

        result = asyncio.run(ingest.index_documents([str(tf)]))

        assert result["total_pdfs"] == 1
        assert dr.is_cached(str(tf), "pypdf", "2.0")

    def test_clear_rebuild_does_not_skip_cached_files(self, tmp_path, monkeypatch):
        import backend.rag.doc_registry as dr
        import backend.rag.ingest as ingest

        monkeypatch.setattr(dr, "DOC_REGISTRY_PATH", tmp_path / "doc_registry.json")
        tf = tmp_path / "test.pdf"
        tf.write_bytes(b"%PDF-1.4 test content")
        doc_id = dr.register_doc(str(tf), parser_name="pypdf", parser_version="2.0")
        dr.update_status(doc_id, "indexed")

        class FakeVectorStore:
            def __init__(self):
                self.clear_called = False

            def count(self):
                return 1

            def clear(self):
                self.clear_called = True

        class FakeProcessor:
            parser = SimpleNamespace(name="pypdf", version="2.0")
            llm_chat = None

            def __init__(self):
                self.vector_store = FakeVectorStore()
                self.processed = 0

            async def process_document(self, file_path):
                self.processed += 1
                return SimpleNamespace(
                    doc_id="path-derived-doc-id",
                    text_blocks=1,
                    multimodal_items=0,
                    entities_added=0,
                    relations_added=0,
                    errors=[],
                )

        fake_processor = FakeProcessor()
        monkeypatch.setattr(ingest, "_build_doc_processor", lambda: fake_processor)

        result = asyncio.run(ingest.index_documents([str(tf)], clear=True))

        assert result["total_pdfs"] == 1
        assert fake_processor.vector_store.clear_called
        assert fake_processor.processed == 1


class TestDocumentProcessor:
    def test_text_context_uses_original_block_index(self, tmp_path):
        from backend.rag.pipeline import DocumentProcessor
        from backend.rag.schemas.block import SpectrumContentBlock
        from backend.rag.schemas.document import SpectrumDocument

        table = SpectrumContentBlock.create("d1", "f.pdf", 1, "table", "A|B")
        text = SpectrumContentBlock.create("d1", "f.pdf", 1, "text", "3500 MHz mobile allocation")

        class FakeParser:
            name = "fake"
            version = "1.0"

            def parse(self, file_path):
                return SpectrumDocument("d1", "f.pdf", file_path, [table, text])

        class RecordingContextBuilder:
            def __init__(self):
                self.indexes = []

            def build_from_blocks(self, blocks, block_idx):
                self.indexes.append(block_idx)
                return None

        class FakeTextProcessor:
            def process(self, block, context=None):
                block.enhanced_content = block.content
                return block

        ctx = RecordingContextBuilder()
        processor = DocumentProcessor(
            parser=FakeParser(),
            text_proc=FakeTextProcessor(),
            context_builder=ctx,
        )

        result = asyncio.run(processor.process_document(str(tmp_path / "f.pdf")))

        assert result.errors == []
        assert ctx.indexes[0] == 1


class TestCallbacks:
    def test_callback_manager(self):
        from backend.rag.callbacks import CallbackManager
        mgr = CallbackManager()
        events = []
        mgr.register(lambda e: events.append(e))
        mgr.emit("parse_start", file_path="test.pdf", status="started")
        mgr.emit("parse_complete", file_path="test.pdf", status="completed", progress=1.0)
        assert len(events) == 2
        assert events[0].name == "parse_start"
        assert events[1].progress == 1.0


class TestEdges:
    def test_empty_blocks_separation(self):
        from backend.rag.processor import separate_content
        text, multi = separate_content([])
        assert text == []
        assert multi == []

    def test_all_text_no_multimodal(self):
        from backend.rag.processor import separate_content
        from backend.rag.schemas.block import SpectrumContentBlock
        blocks = [SpectrumContentBlock.create("d1", "f.pdf", 1, "text", "a"),
                   SpectrumContentBlock.create("d1", "f.pdf", 1, "title", "b")]
        text, multi = separate_content(blocks)
        assert len(text) == 2
        assert len(multi) == 0
