"""Agent tools share the same measured, persisted results as the wireless UI."""
from __future__ import annotations

import asyncio


async def wireless_status():
    from ..skills.wireless_recognition.service import get_wireless_service
    return await asyncio.to_thread(get_wireless_service().status)


async def list_wireless_records():
    from ..skills.wireless_recognition.service import get_wireless_service
    return await asyncio.to_thread(get_wireless_service().list_records, 30)


async def analyze_wireless_record(record_id: str, start_sample: int = 0, stop_sample: int | None = None,
                                  frequency_start_hz: float | None = None, frequency_stop_hz: float | None = None,
                                  sample_rate_hz: float | None = None):
    from ..api.wireless_recognition import AnalyzeRequest
    from ..memory.hooks import track_skill_run
    from ..skills.wireless_recognition.service import get_wireless_service
    options = AnalyzeRequest(start_sample=start_sample, stop_sample=stop_sample,
                             frequency_start_hz=frequency_start_hz, frequency_stop_hz=frequency_stop_hz,
                             sample_rate_hz=sample_rate_hz)
    with track_skill_run("wireless_recognition", input_data={"record_id": record_id, **options.model_dump()}) as audit:
        result = await asyncio.to_thread(get_wireless_service().analyze, record_id, **options.model_dump())
        audit["output_summary"] = f"analysis={result['id']}, protocol_status={result['protocol']['status']}"
        return result


async def get_wireless_analysis(analysis_id: str):
    from ..skills.wireless_recognition.service import get_wireless_service
    return await asyncio.to_thread(get_wireless_service().get_analysis, analysis_id)


WIRELESS_TOOLS = [
    {"name": "wireless_status", "handler": wireless_status,
     "description": "查看实时采集接收状态和协议模型是否加载。无训练权重时不得声称已经识别协议。",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_wireless_records", "handler": list_wireless_records,
     "description": "列出最近30条完整SAM60采集记录及可用ID；请使用记录ID，不要猜服务器路径或采样率。",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "analyze_wireless_record", "handler": analyze_wireless_record,
     "description": "对用户指定的记录和时间/频率选区测量中心频点与占用带宽，并调用已挂载协议模型。只能使用用户给定/列表返回ID；不得猜测缺失采样率。MODE0仅测参，MODE1才可分类。未配置模型/unknown必须如实报告。",
     "parameters": {"type": "object", "properties": {
         "record_id": {"type": "string"}, "start_sample": {"type": "integer", "minimum": 0},
         "stop_sample": {"type": "integer", "minimum": 1},
         "frequency_start_hz": {"type": "number", "exclusiveMinimum": 0},
         "frequency_stop_hz": {"type": "number", "exclusiveMinimum": 0},
         "sample_rate_hz": {"type": "number", "exclusiveMinimum": 0, "description": "仅在头部缺失时使用用户明确确认的采样率"},
     }, "required": ["record_id"], "additionalProperties": False}},
    {"name": "get_wireless_analysis", "handler": get_wireless_analysis,
     "description": "按分析ID读取用户在无线协议识别界面保存的测量/分类结果与选区依据，再据此解释；不重新猜测协议。",
     "parameters": {"type": "object", "properties": {"analysis_id": {"type": "string"}},
                    "required": ["analysis_id"], "additionalProperties": False}},
]
