# Agent Platform Upgrade Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Upgrade SpectrumClaw into a production-grade, observable, model-aware agent workspace while preserving the current 3090 backend workflow and frontend UX.

**Architecture:** Keep the existing FastAPI + LangGraph-compatible backend and React/Vite frontend. Harden the platform by centralizing model capability metadata, standardizing SSE events, splitting oversized UI/API modules, and adding health/trace surfaces for agent execution, RAG, memory, tools, and long-running spectrum skills.

**Tech Stack:** React 18, Vite 5, FastAPI, Pydantic v2, LangGraph, SQLite memory store, Chroma/RAG, DeepSeek OpenAI-compatible API through the 3090 tunnel.

---

## Guiding Principles

| Principle | Decision |
| --- | --- |
| Stable agent architecture | Prefer a simple augmented-LLM + tools + retrieval + memory loop; use LangGraph for stateful orchestration, streaming, persistence, and future human-in-the-loop. |
| Backend owns truth | Provider/model/reasoning/tool capability metadata comes from backend APIs, not frontend guesses. |
| Typed events | SSE streams use consistent event shapes across Chat, RAG, frequency planning, and spectrum decision. |
| Observable by default | Every agent run should expose stages, selected model, tools, RAG hits, memory writes, errors, and artifacts. |
| Incremental refactor | Preserve working endpoints and UI while carving out small modules behind compatibility wrappers. |
| Verification gate | Each task must include at least compile/build checks and targeted tests where the local environment supports them. |

External references used for direction:

| Source | Relevant takeaway |
| --- | --- |
| Anthropic, “Building effective agents” | Start simple; use workflows for predictable paths and agents when model-directed flexibility is needed; core augmented LLM = retrieval + tools + memory. |
| LangGraph docs | LangGraph is strongest for durable execution, streaming, persistence, human-in-the-loop, and stateful long-running agents. |
| OpenAI Agents SDK docs | Stable production primitives are agent loop, tools, handoffs, guardrails, sessions, human-in-the-loop, and tracing. |

## Milestone Roadmap

| Phase | Goal | Deliverables |
| --- | --- | --- |
| P0. Platform contract | Make frontend/backend agree on models, reasoning, and SSE behavior. | Model registry, unified frontend SSE client, updated tests, clear API contract. |
| P0. Console UX | Make Console feel like a professional agent workspace. | Split model picker/composer/message stream/artifact drawer into components; preserve current visual direction. |
| P1. Runtime observability | Make agent behavior explainable and debuggable. | Run trace schema, stage events, deep health endpoint, System page integration. |
| P1. Agent graph hardening | Reduce legacy/manual drift. | One event contract for LangGraph/manual stream, router metrics, tool/RAG/memory spans. |
| P1. Long task execution | Make ingestion and spectrum inference reliable. | Job API for upload/index/GenSpectra with progress/cancel/result. |
| P2. Evaluation and quality | Track answer quality over time. | RAG golden set, agent regression tests, model capability smoke tests, frontend E2E. |

---

### Task 1: Backend Model Registry

**Files:**
- Create: `backend/llm/model_registry.py`
- Modify: `backend/api/chat.py`
- Modify: `tests/test_chat_api.py`

**Step 1: Write focused tests**

Add tests that verify:
- `/api/llm/options` includes DeepSeek Pro and Flash as configured when DeepSeek credentials exist.
- Every configured DeepSeek option supports `low`, `medium`, `high`, `xhigh`.
- `reasoning_options` returns exactly the backend-supported order.
- `max` reasoning effort remains accepted as a compatibility alias and normalizes to `xhigh`.

Run:

```bash
pytest tests/test_chat_api.py -q
```

Expected in a complete local Python environment: tests fail until `model_registry.py` is wired.

**Step 2: Implement registry**

Create `backend/llm/model_registry.py` with:
- `REASONING_EFFORTS = ("low", "medium", "high", "xhigh")`
- `REASONING_OPTIONS` labels/descriptions.
- `ModelOption` Pydantic model or dataclass.
- `model_options_for_settings(settings)` returning active/current options.
- helpers for label/provider display/support detection.

**Step 3: Wire Chat API**

Replace local option-building helpers in `backend/api/chat.py` with imports from `backend.llm.model_registry`.

**Step 4: Verify**

Run:

```bash
python -m compileall backend/api/chat.py backend/llm/client.py backend/llm/model_registry.py tests/test_chat_api.py
npm --prefix frontend run build
```

Expected: compile/build exit 0. If pytest dependencies are available, `pytest tests/test_chat_api.py -q` should pass.

---

### Task 2: Unified Frontend SSE Client

**Files:**
- Modify: `frontend/src/lib/api.js`

**Step 1: Add shared helper**

Add a private `streamJsonEvents(path, body, onEvent, options)` helper that owns:
- `AbortController`
- timeout message
- network failure message
- response status handling
- `data: <json>` parsing
- malformed event skipping

**Step 2: Migrate stream callers**

Update these functions to call the helper:
- `sendChatStream`
- `runRagStream`
- `runFrequencyPlanStream`
- `runDecisionAllocationStream`

**Step 3: Preserve behavior**

Keep existing user-facing Chinese error messages and endpoint payloads.

**Step 4: Verify**

Run:

```bash
npm --prefix frontend run build
```

Expected: build exits 0.

---

### Task 3: Console Component Split

**Files:**
- Create: `frontend/src/components/console/ModelMenu.jsx`
- Create: `frontend/src/components/console/Composer.jsx`
- Create: `frontend/src/components/console/MessageList.jsx`
- Create: `frontend/src/hooks/useModelOptions.js`
- Modify: `frontend/src/pages/ConsolePage.jsx`
- Modify: `frontend/src/styles/app.css`

**Step 1: Extract model state**

Move model option fetching, saved model matching, selected model, thinking state, and reasoning effort state into `useModelOptions`.

**Step 2: Extract UI components**

Move model menu, input composer, and message rendering into separate components without changing class names unless needed.

**Step 3: Keep behavior stable**

Existing localStorage keys, request payload fields, and parent `onModelChange` behavior must remain compatible.

**Step 4: Verify**

Run:

```bash
npm --prefix frontend run build
```

Expected: build exits 0.

---

### Task 4: Agent Run Event Contract

**Files:**
- Create: `backend/agent/run_events.py`
- Modify: `backend/agent/events.py`
- Modify: `backend/agent/runtime.py`
- Modify: `backend/rag/graph/stream.py`
- Modify: `backend/api/spectrum_decision.py`
- Test: `tests/test_agent_runtime.py`

**Step 1: Define common event constructors**

Support canonical event types:
- `stage`
- `thinking`
- `content`
- `tool_call`
- `tool_result`
- `rag_result`
- `memory_write`
- `artifact`
- `error`
- `done`

**Step 2: Keep compatibility**

Existing frontend handlers must continue receiving `type` and `data`. New fields should be additive.

**Step 3: Verify**

Run:

```bash
python -m compileall backend/agent backend/rag/graph/stream.py backend/api/spectrum_decision.py tests/test_agent_runtime.py
pytest tests/test_agent_runtime.py -q
```

Expected: compile exits 0; pytest passes when dependencies are installed.

---

### Task 5: Deep System Health

**Files:**
- Modify: `backend/api/system.py`
- Modify: `backend/app.py`
- Modify: `frontend/src/pages/SystemPage.jsx`
- Modify: `frontend/src/lib/api.js`

**Step 1: Backend health endpoint**

Add `GET /api/system/health/deep` returning:
- backend status
- LLM configured/model/provider
- memory DB reachability
- RAG registry/vector/graph readiness
- artifact/log roots
- optional GenSpectra sidecar status

**Step 2: Frontend System page**

Replace static System page content with live cards and degraded/error states.

**Step 3: Verify**

Run:

```bash
python -m compileall backend/api/system.py backend/app.py
npm --prefix frontend run build
```

Expected: compile/build exit 0.

---

### Task 6: Job API for Long Tasks

**Files:**
- Create: `backend/jobs/store.py`
- Create: `backend/api/jobs.py`
- Modify: `backend/app.py`
- Modify: `backend/api/rag.py`
- Modify: `backend/api/spectrum_construction.py`
- Modify: `frontend/src/lib/api.js`

**Step 1: Add minimal in-process job store**

Support `submit`, `status`, `result`, and `cancel_requested`. Start with in-memory state plus persisted artifact references; do not introduce Redis yet.

**Step 2: Wrap long operations**

Wrap RAG indexing and GenSpectra generation with job records while preserving existing synchronous endpoints for compatibility.

**Step 3: Verify**

Run:

```bash
python -m compileall backend/jobs backend/api/jobs.py backend/api/rag.py backend/api/spectrum_construction.py backend/app.py
npm --prefix frontend run build
```

Expected: compile/build exit 0.

---

## First Execution Batch

| Order | Task | Why first |
| --- | --- | --- |
| 1 | Task 1: Backend Model Registry | Backend must own model/reasoning truth before UI and agent routing can be reliable. |
| 2 | Task 2: Unified Frontend SSE Client | Reduces duplicated stream behavior and makes future agent event work safer. |
| 3 | Task 5: Deep System Health | Gives us a live operating dashboard before deeper runtime changes. |

## Non-Goals For This Phase

| Non-goal | Reason |
| --- | --- |
| Replace LangGraph with another framework | Current stack already aligns with stable production patterns. |
| Add a new database or queue immediately | In-process job API is enough for the first reliability step. |
| Rewrite every frontend page | Console and shared API are the highest leverage first. |
| Force all tools through MCP immediately | Useful later, but current local tools/skills should be stabilized first. |

---

## Current Status - 2026-06-22

| Area | Status | Notes |
| --- | --- | --- |
| Backend model registry | Done | `/api/llm/options` is backend-owned and currently exposes only DeepSeek Pro and DeepSeek Flash. Both support `off`, `low`, `medium`, `high`, and `xhigh`. |
| Reasoning control | Done | `off` maps to explicit DeepSeek disabled thinking; real off stream returns no `thinking` events. `max` remains a compatibility alias for `xhigh`. |
| Console model UX | Done | Model picker is split into `useModelOptions`, `ModelMenu`, `Composer`, and `MessageList`, with Codex-style Pro/Flash + reasoning control. |
| System status | Done | System page reads backend health plus frontend model selection, so choosing Flash in Console is reflected in the status UI. |
| SSE contract | Done | Agent/RAG/chat/spectrum decision streams now share additive `agent-run-v1` fields while preserving legacy `type` and `data`. |
| Runtime observability | Partial | Console consumes `stage`, `rag_result`, `tool_*`, `memory_write`, and `artifact` events for pipeline/task-log visibility. |
| 3090 backend | Done | Code synced and uvicorn restarted on the 3090 backend during implementation. |

## Next Execution Queue

| Priority | Task | Outcome |
| --- | --- | --- |
| P0 | Reduce hidden-page background API load | Only mounted/visible pages should poll heavy system, memory, RAG, and spectrum endpoints. This prevents a single uvicorn worker from being saturated by inactive tabs/views. |
| P0 | Add lightweight frontend integration checks | Add a small browser or DOM-level check for model selection, System status selected model, and stream event handling. |
| P1 | Job API for long tasks | Add job submit/status/result/cancel primitives for RAG ingestion and spectrum construction. Preserve existing synchronous endpoints. |
| P1 | Agent trace panel | Store and display per-run trace metadata: model, reasoning mode, stages, tool calls, RAG hits, memory writes, errors, and artifacts. |
| P1 | Runtime concurrency hardening | Move expensive synchronous skill work out of the request path or into bounded workers so `/health` and `/api/llm/options` stay responsive under load. |
| P2 | Evaluation suite | Add regression fixtures for RAG, tool routing, model options, and stream contracts; run them locally and on the 3090 environment when pytest is available. |

## Handoff Notes

| Topic | Detail |
| --- | --- |
| Local frontend | Vite is expected on `http://127.0.0.1:5174/`. |
| Backend tunnel | Local `8230` forwards to the 3090 backend. |
| Model source of truth | Backend registry controls available models; frontend selection is per-browser via `sc_model`. |
| Commit scope | This plan and the current platform-upgrade code/tests are intended to be committed. Historical local deletions of `AGENTS.md` and `CLAUDE.md` are not part of this feature batch. |
