"""Multimodal processing — VLM client for image/table/formula understanding."""

from .vlm_client import (
    VLMClient,
    QwenVLClient,
    LocalQwen2VLClient,
    build_vlm_client,
    describe_vlm_runtime,
)

__all__ = ["VLMClient", "QwenVLClient", "LocalQwen2VLClient", "build_vlm_client", "describe_vlm_runtime"]
