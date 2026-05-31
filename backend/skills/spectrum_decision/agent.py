"""Spectrum Decision Agent — LLM-powered intent understanding + result explanation.

The agent wraps the SLSQP optimizer: the LLM interprets natural language user
requests, extracts allocation parameters, runs the numerical optimizer, and
explains the results in plain language. The optimizer is the primary engine;
the agent is the intelligent assistant.
"""

from __future__ import annotations

import json as _json
from typing import Any, AsyncIterator


INTENT_PARSE_PROMPT = """You are a spectrum resource allocation assistant. Given a user's natural language request about wireless network resource allocation, extract the structured parameters.

Output ONLY a JSON object with these fields:
- num_users (int, 1-50): number of users/devices to allocate resources for
- total_bandwidth_mhz (float, 10-1000): total available spectrum bandwidth in MHz
- environment (string): "urban", "suburban", or "rural"
- service_mix_desc (string): which service type dominates, one of "embb_heavy", "urllc_heavy", "balanced", "default"
- seed (int): random seed for reproducibility, use 0 for random

Service mix mapping:
- "embb_heavy": mostly high-throughput users (video streaming, downloads) — 80% eMBB, 15% URLLC, 5% mMTC
- "urllc_heavy": mostly low-latency users (autonomous driving, industrial control) — 20% eMBB, 70% URLLC, 10% mMTC
- "balanced": equal mix of all three — 40% eMBB, 30% URLLC, 30% mMTC
- "default": standard mix — 60% eMBB, 30% URLLC, 10% mMTC

User request: {user_request}

JSON:"""


RESULT_EXPLAIN_PROMPT = """You are a spectrum resource allocation expert. Explain the following allocation results to the user in clear, professional Chinese.

Scenario:
- {num_users} users, {total_bandwidth_mhz} MHz total bandwidth, {environment} environment, {frequency_mhz} MHz carrier
- Service type: {service_summary}
- Allocation method: {method}
- Total throughput: {total_throughput} Mbps
- Jain's fairness index: {fairness} (1.0 = perfectly fair)

Per-user details (top 10 shown):
{user_details}

Give a concise analysis (3-5 sentences in Chinese) covering:
1. Overall allocation quality (fairness, throughput efficiency)
2. Any notable patterns (which users got more/less bandwidth and why)
3. One actionable recommendation for the network operator

Reply in Chinese, no markdown formatting."""


async def parse_intent(user_request: str) -> dict[str, Any]:
    """Use LLM to parse natural language intent into structured parameters."""
    from ...llm.client import chat
    from ...config import get_settings

    settings = get_settings()
    provider = settings.provider_profile()

    prompt = INTENT_PARSE_PROMPT.format(user_request=user_request)
    messages = [{"role": "user", "content": prompt}]

    reply, _ = await chat(
        messages,
        provider_override=provider.provider,
        model_override=provider.model,
    )

    # Try to extract JSON from reply
    try:
        # Find JSON in the response
        start = reply.find("{")
        end = reply.rfind("}") + 1
        if start >= 0 and end > start:
            return _json.loads(reply[start:end])
    except _json.JSONDecodeError:
        pass

    # Fallback: return default params
    return {
        "num_users": 10,
        "total_bandwidth_mhz": 100,
        "environment": "urban",
        "service_mix_desc": "default",
        "seed": 0,
    }


async def explain_result(
    result: dict[str, Any],
    users: list[dict],
    environment: str = "urban",
    frequency_mhz: float = 3500.0,
) -> str:
    """Use LLM to explain allocation results in plain language."""
    from ...llm.client import chat
    from ...config import get_settings

    settings = get_settings()
    provider = settings.provider_profile()

    # Service summary
    svc_counts: dict[str, int] = {}
    for u in users:
        svc = u.get("service", "eMBB")
        svc_counts[svc] = svc_counts.get(svc, 0) + 1
    service_summary = ", ".join(f"{k}={v}" for k, v in svc_counts.items())

    # User details (top 10)
    allocs = result.get("allocations", [])[:10]
    user_detail_lines = []
    for a in allocs:
        user_detail_lines.append(
            f"  {a.get('user_id', '?')}: {a.get('service', '?')} CQI={a.get('cqi', '?')} "
            f"BW={a.get('bandwidth_mhz', 0)}MHz Rate={a.get('rate_mbps', 0)}Mbps "
            f"SNR={a.get('snr_db', '?')}dB LOS={a.get('los', False)}"
        )
    user_details = "\n".join(user_detail_lines) if user_detail_lines else "(none)"

    prompt = RESULT_EXPLAIN_PROMPT.format(
        num_users=len(users),
        total_bandwidth_mhz=result.get("total_bandwidth_mhz", 0),
        environment=environment,
        frequency_mhz=frequency_mhz,
        service_summary=service_summary,
        method=result.get("method", "unknown"),
        total_throughput=result.get("total_throughput_mbps", 0),
        fairness=result.get("fairness", 0),
        user_details=user_details,
    )

    messages = [{"role": "user", "content": prompt}]

    reply, _ = await chat(
        messages,
        provider_override=provider.provider,
        model_override=provider.model,
    )
    return reply.strip()


async def run_agent_allocation(
    user_request: str = "",
    num_users: int | None = None,
    total_bandwidth_mhz: float = 100.0,
    environment: str = "urban",
    frequency_mhz: float = 3500.0,
    seed: int = 0,
    service_mix: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Full agent-driven allocation pipeline.

    If user_request is provided, the agent parses intent to extract parameters.
    Otherwise, explicit parameters are used directly.
    Then runs the SLSQP optimizer and explains the results.
    """
    from .dataset import generate_users
    from .resource_allocator import allocate_multi_service

    # Step 1: parse intent (if natural language)
    parsed = {}
    if user_request and user_request.strip():
        try:
            parsed = await parse_intent(user_request)
        except Exception:
            pass

    n_users = num_users or parsed.get("num_users", 10)
    n_bw = total_bandwidth_mhz if num_users else parsed.get("total_bandwidth_mhz", total_bandwidth_mhz)
    env = environment or parsed.get("environment", "urban")
    s_seed = seed or parsed.get("seed", 0)
    if s_seed == 0:
        import random as _random
        s_seed = _random.randint(1, 9999)

    # Map service_mix_desc to actual mix
    mix_map = {
        "embb_heavy": {"eMBB": 0.8, "URLLC": 0.15, "mMTC": 0.05},
        "urllc_heavy": {"eMBB": 0.2, "URLLC": 0.7, "mMTC": 0.1},
        "balanced": {"eMBB": 0.4, "URLLC": 0.3, "mMTC": 0.3},
        "default": {"eMBB": 0.6, "URLLC": 0.3, "mMTC": 0.1},
    }
    mix_desc = parsed.get("service_mix_desc", "default")
    final_mix = service_mix or mix_map.get(mix_desc, mix_map["default"])

    # Step 2: generate users + run optimizer
    users = generate_users(
        num_users=n_users, seed=s_seed,
        environment=env, frequency_mhz=frequency_mhz,
        service_mix=final_mix,
    )
    alloc_result = allocate_multi_service(users, n_bw)

    # Attach SNR/distance/LOS to allocations
    for a, u in zip(alloc_result["allocations"], users):
        a.update({
            "snr_db": u.get("snr_db", 0),
            "distance_m": u.get("distance_m", 0),
            "los": u.get("los", False),
            "spectral_efficiency": u.get("spectral_efficiency", 0),
        })

    # Step 3: agent explains results
    explanation = ""
    try:
        explanation = await explain_result(alloc_result, users, env, frequency_mhz)
    except Exception:
        explanation = "(结果解释生成失败，请重试)"

    return {
        "users": users,
        "allocations": alloc_result["allocations"],
        "total_bandwidth_mhz": alloc_result["total_bandwidth_mhz"],
        "total_throughput_mbps": alloc_result["total_throughput_mbps"],
        "fairness": alloc_result["fairness"],
        "method": alloc_result["method"],
        "environment": env,
        "frequency_mhz": frequency_mhz,
        "seed": s_seed,
        "parsed_intent": parsed,
        "agent_explanation": explanation,
    }
