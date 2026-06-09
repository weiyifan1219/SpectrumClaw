"""Seed the memory database with demo data for UI development.

Creates realistic-looking memory items, threads, skill runs, feedback,
and evolution reports so the Memory & Evolution page has content to display.

Usage:
    python -m backend.memory.seed
    python -m backend.memory.seed --clear  # wipe and re-seed
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from backend.memory.service import MemoryService
from backend.memory.store import MemoryStore


THREADS = [
    {"thread_id": "t_001", "title": "2300-2400 MHz Region 3 分配查询"},
    {"thread_id": "t_002", "title": "UAV REM 场景 148 重建分析"},
    {"thread_id": "t_003", "title": "频率规划 IMT-2020 合规检查"},
    {"thread_id": "t_004", "title": "GenSpectra 模型效果评估"},
    {"thread_id": "t_005", "title": "5G NR n78 干扰分析"},
]

MEMORY_ITEMS = [
    {"text": "2300-2400 MHz 在 Region 3 分配给移动业务（主要业务），脚注 5.384A 规定需要与卫星业务协调。", "kind": "domain", "thread_id": "t_001", "tags": ["2300MHz", "Region3", "Mobile"], "confidence": 0.92},
    {"text": "用户首次查询 2300 MHz 频段时关注的是 IMT 系统在该频段的可用性，特别是室外宏站部署场景。", "kind": "episodic", "thread_id": "t_001", "tags": ["IMT", "macro_cell"], "confidence": 0.78},
    {"text": "UAV REM 场景 148 使用 ABR 主动采样策略，128×128×5 分辨率，5% 采样率下 RMSE=1.32 dB，优于 Random (3.93) 和 KNN (6.06)。", "kind": "episodic", "thread_id": "t_002", "tags": ["UAV_REM", "ABR", "RMSE"], "confidence": 0.95},
    {"text": "GenSpectra pretrain 模型在 64×64 分辨率、75% mask ratio 下 RMSE=0.44 dB，重建质量满足频率规划可视化需求。", "kind": "skill", "thread_id": "t_004", "skill_name": "spectrum_construction", "tags": ["GenSpectra", "pretrain"], "confidence": 0.90},
    {"text": "频率规划模块在处理 IMT-2020 候选频段时，需要同时考虑相邻频段的带外辐射限值（参见 ITU-R SM.329）。", "kind": "domain", "tags": ["frequency_planning", "IMT-2020", "OOB"], "confidence": 0.85},
    {"text": "RAG 检索 ITU-R M.2292 时返回了多个版本的文档块，用户反馈希望优先返回最新版本。", "kind": "episodic", "thread_id": "t_003", "tags": ["RAG", "versioning"], "confidence": 0.72},
    {"text": "spectrum_construction skill 调用 GenSpectra 时，如果 checkpoint 不可用会 fallback 到纯 Gudmundson 生成器，此时不返回 reconstruction 字段。", "kind": "skill", "skill_name": "spectrum_construction", "tags": ["GenSpectra", "fallback"], "confidence": 0.88},
    {"text": "5G NR n78 频段 (3300-3800 MHz) 与 C 波段卫星下行链路存在潜在干扰，ITU-R S.1432 给出了保护标准。", "kind": "domain", "thread_id": "t_005", "tags": ["n78", "C-band", "interference"], "confidence": 0.91},
    {"text": "用户偏好：查询结果中应包含具体的 ITU-R 建议书编号和脚注引用，便于后续查验。", "kind": "episodic", "tags": ["user_preference", "citation"], "confidence": 0.80},
    {"text": "frequency_planning skill 在处理多运营商共存场景时需要考虑 guard band 和 ACIR 约束，当前实现仅支持单运营商。", "kind": "skill", "skill_name": "frequency_planning", "tags": ["multi-operator", "guard_band"], "confidence": 0.75},
    {"text": "知识图谱中 FrequencyBand 实体已覆盖 150 kHz ~ 275 GHz 范围，但毫米波频段 (>24 GHz) 的关系密度较低。", "kind": "domain", "tags": ["knowledge_graph", "mmWave"], "confidence": 0.82},
    {"text": "UAV REM 的 GeoBelief ABR 策略在建筑密集区域表现更优，因为 uncertainty term 能有效识别阴影区。", "kind": "skill", "skill_name": "spectrum_construction", "thread_id": "t_002", "tags": ["ABR", "urban", "shadow"], "confidence": 0.87},
]

SKILL_RUNS = [
    {"skill_name": "spectrum_construction", "thread_id": "t_002", "output_summary": "UAV REM scene 148, Z2, ABR method. RMSE=1.32dB, 193 path points, 5% coverage.", "status": "success", "latency_ms": 2340},
    {"skill_name": "spectrum_construction", "thread_id": "t_004", "output_summary": "GenSpectra pretrain 64x64, mask_ratio=0.75, RMSE=0.44dB.", "status": "success", "latency_ms": 4120},
    {"skill_name": "spectrum_construction", "thread_id": "t_004", "output_summary": "GenSpectra pretrain 128x128, checkpoint not found.", "status": "failed", "latency_ms": 890, "error": "checkpoint not found: pretrain_GenSpectraLM_128.pth"},
    {"skill_name": "frequency_planning", "thread_id": "t_003", "output_summary": "IMT-2020 candidate band analysis: 3300-3800 MHz, 4800-4990 MHz.", "status": "success", "latency_ms": 1560},
    {"skill_name": "frequency_planning", "thread_id": "t_003", "output_summary": "Guard band calculation for n78/C-band coexistence.", "status": "success", "latency_ms": 980},
    {"skill_name": "rag_query", "thread_id": "t_001", "output_summary": "Retrieved 8 blocks from ITU-R M.1036, M.2292. Hybrid retrieval: vec=5, kw=2, graph=1.", "status": "success", "latency_ms": 3200},
    {"skill_name": "rag_query", "thread_id": "t_005", "output_summary": "Retrieved 12 blocks from ITU-R S.1432, SM.2368. Query: 5G n78 interference with FSS.", "status": "success", "latency_ms": 2890},
    {"skill_name": "spectrum_construction", "output_summary": "GenSpectra 32x32, seed=42, mask_ratio=0.75. RMSE=0.38dB.", "status": "success", "latency_ms": 3800},
    {"skill_name": "rag_query", "thread_id": "t_003", "output_summary": "Query failed: Chroma collection empty.", "status": "failed", "latency_ms": 120, "error": "No vectors in collection spectrum_blocks"},
    {"skill_name": "spectrum_decision", "thread_id": "t_005", "output_summary": "Interference assessment: n78 DL vs FSS DL, separation distance 10km required.", "status": "success", "latency_ms": 5600},
]

FEEDBACK = [
    {"target_type": "rag_answer", "target_id": "ans_001", "rating": 4, "comment": "引用准确，但希望包含更多脚注细节"},
    {"target_type": "rag_answer", "target_id": "ans_002", "rating": 5, "comment": "完美覆盖了 Region 3 的分配情况"},
    {"target_type": "skill_run", "target_id": "run_003", "rating": 2, "comment": "128x128 分辨率无法重建，需要修复 checkpoint 路径"},
    {"target_type": "rag_answer", "target_id": "ans_004", "rating": 3, "comment": "返回了旧版文档，应优先最新版"},
    {"target_type": "skill_run", "target_id": "run_008", "rating": 5, "comment": "32x32 重建质量很好"},
]

REPORTS = [
    {
        "period": "2026-06-01 ~ 2026-06-07",
        "summary": "本周系统完成 12 次 RAG 查询、8 次频谱构建任务。RAG 准确率约 82%（用户反馈 4/5 评分），主要不足是版本控制和多模态检索覆盖。GenSpectra 在 32/64 分辨率表现稳定，128 分辨率 checkpoint 缺失需修复。建议优先完成 MinerU 全量预解析以提升 RAG 召回率。",
        "metrics": {"rag_queries": 12, "skill_runs": 8, "avg_rating": 3.8, "success_rate": 0.75},
        "suggestions": [
            {"priority": "high", "action": "完成 5276 文档的 MinerU 预解析和 Chroma 索引"},
            {"priority": "medium", "action": "修复 GenSpectra 128x128 checkpoint 路径"},
            {"priority": "low", "action": "增加 RAG 结果的版本排序策略"},
        ],
    },
    {
        "period": "2026-05-25 ~ 2026-05-31",
        "summary": "系统初始化阶段。完成了前端 4 页核心布局、后端 API 框架、记忆系统 schema 设计。RAG pipeline 基础链路搭建完成（PyPDF→Chroma→LangGraph），知识图谱结构设计对标 RAG-Anything。下周目标：MinerU GPU 加速解析、全量 ingest。",
        "metrics": {"pages_built": 4, "api_endpoints": 15, "schema_tables": 6},
        "suggestions": [
            {"priority": "high", "action": "GPU 加速 MinerU 预解析（已完成）"},
            {"priority": "high", "action": "部署 bge-m3 embedding 到 3090"},
            {"priority": "medium", "action": "前端态势构建接入真实后端"},
        ],
    },
]


def seed(clear: bool = False):
    db_path = str(PROJECT_ROOT / "data" / "memory" / "spectrum_memory.sqlite3")

    if clear:
        p = Path(db_path)
        if p.exists():
            p.unlink()
            print(f"[*] Deleted {db_path}")

    svc = MemoryService(db_path=db_path)

    # Threads
    for t in THREADS:
        svc.ensure_thread(t["thread_id"], t["title"])
        for _ in range(3):
            svc.bump_thread(t["thread_id"])
    print(f"[+] Created {len(THREADS)} threads")

    # Memory items
    for item in MEMORY_ITEMS:
        svc.add_memory(
            text=item["text"],
            kind=item.get("kind", "episodic"),
            thread_id=item.get("thread_id", ""),
            skill_name=item.get("skill_name", ""),
            tags=item.get("tags"),
            confidence=item.get("confidence", 0.5),
        )
    print(f"[+] Created {len(MEMORY_ITEMS)} memory items")

    # Skill runs
    for run in SKILL_RUNS:
        svc.record_skill_run(
            skill_name=run["skill_name"],
            thread_id=run.get("thread_id", ""),
            output_summary=run.get("output_summary", ""),
            status=run.get("status", "success"),
            latency_ms=run.get("latency_ms", 0),
            error=run.get("error", ""),
        )
    print(f"[+] Created {len(SKILL_RUNS)} skill runs")

    # Feedback
    for fb in FEEDBACK:
        svc.record_feedback(
            target_type=fb["target_type"],
            target_id=fb["target_id"],
            rating=fb["rating"],
            comment=fb.get("comment", ""),
        )
    print(f"[+] Created {len(FEEDBACK)} feedback entries")

    # Evolution reports
    import json
    for rpt in REPORTS:
        svc.add_report(
            summary=rpt["summary"],
            period=rpt["period"],
            metrics=rpt.get("metrics"),
            suggestions=rpt.get("suggestions"),
        )
    print(f"[+] Created {len(REPORTS)} evolution reports")

    # Overview
    ov = svc.overview()
    report_count = len(svc.store.list_reports(limit=100))
    print(f"\n{'='*50}")
    print(f"Memory DB seeded: {db_path}")
    print(f"  Threads:    {ov.thread_count}")
    print(f"  Items:      {ov.item_count}")
    print(f"  Skill runs: {ov.skill_run_count}")
    print(f"  Feedback:   {ov.feedback_count}")
    print(f"  Reports:    {report_count}")


def main():
    ap = argparse.ArgumentParser(description="Seed memory database with demo data")
    ap.add_argument("--clear", action="store_true", help="Clear existing DB before seeding")
    args = ap.parse_args()
    seed(clear=args.clear)


if __name__ == "__main__":
    main()
