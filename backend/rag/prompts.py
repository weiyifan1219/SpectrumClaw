"""Spectrum-domain multimodal prompt templates — aligned with RAG-Anything format."""

from __future__ import annotations


class PromptRegistry:
    """Stable prompt container with JSON-structured multimodal analysis prompts."""

    def __init__(self):
        self._data: dict[str, str] = {}

    def swap(self, prompts: dict[str, str]):
        self._data = dict(prompts)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __setitem__(self, key: str, value: str):
        self._data[key] = value

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)


PROMPTS = PromptRegistry()

# ── System prompts ──
PROMPTS["IMAGE_ANALYSIS_SYSTEM"] = (
    "You are an expert spectrum analyst. You analyze figures from ITU-R "
    "spectrum management documents. Provide detailed, accurate descriptions "
    "with all frequency values and technical parameters preserved."
)
PROMPTS["TABLE_ANALYSIS_SYSTEM"] = (
    "You are an expert in spectrum allocation data. Extract every row's "
    "frequency band, service, region, and constraint with precision."
)
PROMPTS["EQUATION_ANALYSIS_SYSTEM"] = (
    "You are an expert in radio/wireless system mathematics. Analyze equations "
    "from ITU-R standards — propagation models, link budgets, interference."
)
PROMPTS["GENERIC_ANALYSIS_SYSTEM"] = (
    "You are an expert content analyst specializing in {content_type} content "
    "from ITU-R spectrum management documents."
)

# ── Image analysis — JSON structured ──
PROMPTS["image_analysis"] = """Analyze this figure from a spectrum management document. Output JSON:
{{
    "detailed_description": "Type of figure, all frequency bands/channels/bandwidths shown, radio services and ITU Regions visible, key technical parameters, relationships between elements",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "concise summary for knowledge retrieval (max 150 words)"
    }}
}}
Captions: {captions}
Footnotes: {footnotes}
Context: {context}"""

# ── Table analysis — JSON structured ──
PROMPTS["table_analysis"] = """Analyze this spectrum allocation table. Output JSON:
{{
    "detailed_description": "Row-by-row: frequency band, service(s), ITU Region(s), allocation status (primary/secondary), footnote constraints. Preserve all numerical values and units exactly.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "table purpose and key allocations (max 150 words)"
    }}
}}
Caption: {table_caption}
Body: {table_body}
Footnotes: {table_footnote}
Context: {context}"""

# ── Equation analysis — JSON structured ──
PROMPTS["equation_analysis"] = """Analyze this equation from a spectrum document. Output JSON:
{{
    "detailed_description": "Meaning in radio/wireless context, each variable's definition and units, typical value ranges, application (link budget/propagation/interference/protection), ITU-R reference if applicable",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "equation purpose in spectrum engineering (max 150 words)"
    }}
}}
Equation: {equation_text}
Format: {equation_format}
Context: {context}"""

# ── Generic ──
PROMPTS["generic_analysis"] = """Analyze this {content_type} content. Output JSON:
{{
    "detailed_description": "structure, key information, spectrum domain significance",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "concise summary (max 150 words)"
    }}
}}
Content: {content}
Context: {context}"""

# ── Query-time analysis (simpler, non-JSON) ──
PROMPTS["query_image_description"] = (
    "Briefly describe this spectrum figure's main content, key frequency bands, "
    "services, and important parameters."
)
PROMPTS["query_table_analysis"] = (
    "Summarize this spectrum table's allocations and key data patterns:\n"
    "Table: {table_data}\nCaption: {table_caption}"
)
PROMPTS["query_equation_analysis"] = (
    "Explain this formula from a spectrum document — what it calculates and its "
    "significance for radio/wireless systems:\n"
    "LaTeX: {latex}\nCaption: {equation_caption}"
)
PROMPTS["query_generic_analysis"] = (
    "Summarize this {content_type} content from a spectrum document:\n{content_str}"
)
PROMPTS["query_enhancement_suffix"] = (
    "\n\nProvide a comprehensive answer based on the user query and the multimodal "
    "content information above. Cite specific sources and frequency values."
)
