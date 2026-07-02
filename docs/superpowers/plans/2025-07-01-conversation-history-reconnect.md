# Conversation History & Reconnection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conversation history CRUD (Memory page), new-conversation button, job-based reconnection after page refresh, and activity feed noise reduction.

**Architecture:** Extend existing backend MemoryStore with thread list/delete endpoints. Frontend uses localStorage job_id for reconnection, fetches job events on page load. Activity feed collapses repetitive streaming events into milestone summaries.

**Tech Stack:** FastAPI (Python) backend, React (Vite) frontend, SQLite memory store, SSE streaming

## Global Constraints

- Backend runs on remote 3090, tunneled to localhost:8230
- Frontend runs on localhost:5173 via Vite dev server
- Thread storage uses existing `memory_threads` SQLite table
- Job storage uses in-memory `JobStore` (survives backend restart, NOT frontend refresh)
- All new API endpoints follow existing patterns in `backend/api/memory.py`

---

## File Structure

```
backend/
  api/memory.py          — MODIFY: add thread list/delete endpoints
  memory/store.py        — MODIFY: add list_threads with messages, delete_thread
  runtime/jobs.py        — (no changes needed, already supports get/list)

frontend/
  src/
    lib/api.js           — MODIFY: add fetchThreads, deleteThread, fetchJob
    pages/
      ConsolePage.jsx    — MODIFY: activity feed filter, job recovery on mount, new-chat button
      MemoryPage.jsx     — MODIFY: add "对话历史" tab with thread list + delete
    styles/
      app.css            — MODIFY: activity panel height, compact row styles
```

---

### Task 1: Backend — Add thread list with message preview endpoint

**Files:**
- Modify: `backend/api/memory.py:156-156` (append new endpoints)
- Modify: `backend/memory/store.py:143-148` (add list_threads_with_preview)

**Interfaces:**
- Produces: `GET /api/memory/threads` → `{ threads: [{ thread_id, title, turn_count, updated_at, last_message }] }`
- Produces: `DELETE /api/memory/threads/{thread_id}` → `{ status: "ok" }`

- [ ] **Step 1: Add `list_threads_with_preview` to MemoryStore**

Add to `backend/memory/store.py` after `list_threads`:

```python
def list_threads_with_preview(self, limit: int = 50) -> list[dict]:
    """List threads with last user message as preview."""
    with self._lock:
        rows = self._db.execute(
            """SELECT t.thread_id, t.title, t.turn_count, t.updated_at,
                      (SELECT e.content FROM memory_events e
                       WHERE e.thread_id = t.thread_id AND e.role = 'user'
                       ORDER BY e.created_at DESC LIMIT 1) as last_message
             FROM memory_threads t
             ORDER BY t.updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

def delete_thread(self, thread_id: str) -> bool:
    """Delete a thread and all its events/items. Returns True if deleted."""
    with self._lock:
        cur = self._db.execute("DELETE FROM memory_events WHERE thread_id=?", (thread_id,))
        self._db.execute("DELETE FROM memory_items WHERE thread_id=?", (thread_id,))
        cur = self._db.execute("DELETE FROM memory_threads WHERE thread_id=?", (thread_id,))
        self._db.commit()
        return cur.rowcount > 0
```

- [ ] **Step 2: Add API endpoints in `backend/api/memory.py`**

Append after existing routes (before module end):

```python
@router.get("/api/memory/threads")
async def memory_threads(limit: int = Query(50, ge=1, le=200)):
    svc, _ = _get_service()
    threads = svc.store.list_threads_with_preview(limit=limit)
    return {"threads": threads}


@router.delete("/api/memory/threads/{thread_id}")
async def memory_delete_thread(thread_id: str):
    svc, _ = _get_service()
    deleted = svc.store.delete_thread(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "ok"}
```

- [ ] **Step 3: Test endpoints**

```bash
curl -s http://127.0.0.1:8230/api/memory/threads | python3 -m json.tool | head -20
curl -s -X DELETE http://127.0.0.1:8230/api/memory/threads/test123
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/memory.py backend/memory/store.py
git commit -m "feat: add thread list/delete endpoints for conversation history"
```

---

### Task 2: Frontend API — Add thread list & delete calls

**Files:**
- Modify: `frontend/src/lib/api.js:290-290` (append new functions)

**Interfaces:**
- Consumes: `GET /api/memory/threads`, `DELETE /api/memory/threads/{thread_id}`
- Produces: `fetchThreads()`, `deleteThread(threadId)`

- [ ] **Step 1: Add API functions**

Append after the memory section in `frontend/src/lib/api.js`:

```js
/* ── Thread / Conversation History ── */

export async function fetchThreads({ limit = 50 } = {}) {
  const resp = await fetch(`${BASE}/api/memory/threads?limit=${limit}`);
  if (!resp.ok) throw new Error(`Threads fetch failed (${resp.status})`);
  return resp.json();
}

export async function deleteThread(threadId) {
  const resp = await fetch(`${BASE}/api/memory/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`Thread delete failed (${resp.status})`);
  return resp.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: add thread list/delete API calls"
```

---

### Task 3: Frontend — Fix activity feed (router filter + event collapsing)

**Files:**
- Modify: `frontend/src/pages/ConsolePage.jsx:204-227`

**Interfaces:**
- Consumes: `thinkingEnabled` from `modelState`
- Changes: `activityFeed` useMemo filter + collapse logic

- [ ] **Step 1: Fix router filter to also filter log items**

The current filter only checks `jobDetail?.events` (trace items), but router stages are also added as log entries via `addTaskLog()`. Fix by filtering both trace AND log items.

Replace the `activityFeed` useMemo with:

```jsx
const activityFeed = useMemo(() => {
    const traceItems = (jobDetail?.events || [])
      .filter((event) => {
        if (!thinkingEnabled && (event.stage === "router" || event.label === "Route Request")) return false;
        return true;
      })
      .map((event, index) => ({
        id: `trace-${event.job_id || selectedJobId || "run"}-${event.trace_seq || index}`,
        source: "trace",
        tone: activityTone(event.type),
        tsMs: Number(event.ts || jobDetail?.updated_at || jobDetail?.started_at || 0) * 1000,
        tsLabel: formatAbsoluteTime(event.ts || jobDetail?.updated_at || jobDetail?.started_at),
        marker: event.trace_seq ? `#${event.trace_seq}` : "RUN",
        message: traceEventLabel(event),
        tag: event.stage || event.type || jobDetail?.kind || "trace",
      }));
    const logItems = logs
      .filter((entry) => {
        // Filter router stage from logs too
        if (!thinkingEnabled && entry.tag === "Agent" && entry.msg.includes("路由")) return false;
        return true;
      })
      .map((entry, index) => ({
        id: `log-${entry.tsMs || "legacy"}-${index}`,
        source: "log",
        tone: activityTone(entry.level),
        tsMs: Number(entry.tsMs) || (Date.now() - index),
        tsLabel: entry.ts || "刚刚",
        marker: "LOG",
        message: entry.msg,
        tag: entry.tag || "Agent",
      }));
    // Collapse: keep only the latest "回答流输出" and "思考流输出" lines
    const collapsed = [];
    let sawContent = false, sawThinking = false;
    for (const item of [...traceItems, ...logItems].sort((a, b) => b.tsMs - a.tsMs)) {
      if (item.message === "回答流输出") {
        if (!sawContent) { sawContent = true; collapsed.push(item); }
        continue;
      }
      if (item.message === "思考流输出") {
        if (!sawThinking) { sawThinking = true; collapsed.push(item); }
        continue;
      }
      collapsed.push(item);
    }
    return collapsed;
  }, [jobDetail, logs, selectedJobId, thinkingEnabled]);
```

- [ ] **Step 2: Verify filter works with test call**

```bash
# Test with thinking disabled (default now)
curl -s -X POST http://127.0.0.1:8230/api/chat -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}],"thinking_enabled":false}'
```

Check that activity feed in UI shows no "路由" row.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ConsolePage.jsx
git commit -m "fix: filter router from activity feed, collapse duplicate stream events"
```

---

### Task 4: Frontend — Job-based reconnection on page refresh

**Files:**
- Modify: `frontend/src/pages/ConsolePage.jsx` (add `useEffect` for job recovery)

**Interfaces:**
- Consumes: `fetchJob` from `api.js`, `localStorage` for pending job_id
- Produces: recovered assistant message in chat

- [ ] **Step 1: Add `PENDING_JOB_KEY` and recovery logic**

In `ConsolePage.jsx`, add near other localStorage keys (around line 30):

```jsx
const PENDING_JOB_KEY = "sc_pending_job";
```

Add this effect after other `useEffect` blocks (around line 350):

```jsx
/* ── Recover from page refresh: poll pending job until complete ── */
useEffect(() => {
  if (!active) return;
  const pendingJobId = localStorage.getItem(PENDING_JOB_KEY);
  if (!pendingJobId) return;

  let mounted = true;
  let pollTimer;

  async function poll() {
    try {
      const job = await fetchJob(pendingJobId);
      if (!mounted) return;
      if (job.status === "running") {
        // Still running — poll again in 2s
        pollTimer = setTimeout(poll, 2000);
        return;
      }
      // Job finished — extract reply from events
      const contentEvents = (job.events || [])
        .filter((e) => e.type === "content")
        .map((e) => e.data || "")
        .join("");
      const reasoningEvents = (job.events || [])
        .filter((e) => e.type === "thinking" && e.source === "llm")
        .map((e) => e.data || "")
        .join("");

      if (contentEvents || job.status === "error") {
        setMessages((curr) => {
          // Replace or append the recovered assistant message
          const lastAssistant = [...curr].reverse().find((m) => m.role === "assistant" && m.meta?.streaming);
          const recovered = {
            role: "assistant",
            content: contentEvents || `[错误] ${job.last_error || "未知错误"}`,
            reasoning: reasoningEvents || undefined,
            meta: {
              ts: new Date(job.finished_at * 1000 || Date.now()).toLocaleTimeString("zh-CN", { hour12: false }),
              streaming: false,
              done: true,
              id: Date.now(),
              job_id: pendingJobId,
            },
          };
          if (lastAssistant && !lastAssistant.content) {
            // Replace empty streaming placeholder
            const idx = curr.indexOf(lastAssistant);
            const next = [...curr];
            next[idx] = recovered;
            return next;
          }
          return [...curr, recovered];
        });
      }

      // Clean up pending job
      localStorage.removeItem(PENDING_JOB_KEY);
    } catch {
      // Job might have been cleaned from store — give up
      if (mounted) localStorage.removeItem(PENDING_JOB_KEY);
    }
  }

  // Delay first poll slightly so the UI renders first
  pollTimer = setTimeout(poll, 500);
  return () => { mounted = false; clearTimeout(pollTimer); };
}, [active]);
```

- [ ] **Step 2: Store pending job_id when sending a message**

In the `handleSend` function, after `sendChatStream` is called (around line 418), add:

```jsx
// Inside the stream event handler, catch job_id from the first event:
(event) => {
  if (event.job_id) {
    setSelectedJobId(event.job_id);
    localStorage.setItem(PENDING_JOB_KEY, event.job_id);  // <-- add this line
  }
  // ... rest of handler
```

And in the `done` event handler (around line 469), clear it when complete:

```jsx
} else if (event.type === "done") {
  localStorage.removeItem(PENDING_JOB_KEY);  // <-- add this line
  // ... rest of handler
```

- [ ] **Step 3: Test recovery flow**

```bash
# Start a chat, then immediately refresh the page.
# The message should recover and display after the job completes.
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ConsolePage.jsx
git commit -m "feat: job-based reconnection after page refresh"
```

---

### Task 5: Frontend — New conversation button on main page

**Files:**
- Modify: `frontend/src/pages/ConsolePage.jsx` (add button near composer)

**Interfaces:**
- Produces: "新对话" button that clears messages + generates new thread_id

- [ ] **Step 1: Add new-chat handler and button**

In `ConsolePage.jsx`, add handler:

```jsx
function newChat() {
  const newThreadId = "thread_" + Math.random().toString(36).slice(2, 14);
  setMessages(initialMessages);
  setThreadId(newThreadId);
  saveThreadId(newThreadId);
  setLogs([]);
  saveTaskLog([]);
  localStorage.removeItem(PENDING_JOB_KEY);
}
```

Add button in the JSX, in the top area near the model/skill selectors (around line 640, near the composer):

```jsx
<button
  type="button"
  className="btn ghost sm new-chat-btn"
  onClick={newChat}
  title="开启新对话"
  style={{ marginRight: 8 }}
>
  <Plus size={14} />
  <span className="hide-on-narrow">新对话</span>
</button>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/ConsolePage.jsx
git commit -m "feat: add new conversation button"
```

---

### Task 6: Frontend — Conversation history in Memory page

**Files:**
- Modify: `frontend/src/pages/MemoryPage.jsx` (add "对话历史" tab)
- Modify: `frontend/src/styles/app.css` (add thread list styles)

**Interfaces:**
- Consumes: `fetchThreads`, `deleteThread` from `api.js`
- Produces: Thread list with delete, click to view detail

- [ ] **Step 1: Add thread list tab to MemoryPage**

Add import:

```jsx
import { fetchThreads, deleteThread, fetchMemoryThread } from "../lib/api.js";
```

Add a new tab "对话历史" and state:

```jsx
const [threadTab, setThreadTab] = useState("memory"); // "memory" | "threads"
const [threads, setThreads] = useState([]);
const [threadsLoading, setThreadsLoading] = useState(false);
const [selectedThreadId, setSelectedThreadId] = useState(null);
const [threadDetail, setThreadDetail] = useState(null);

async function loadThreads() {
  setThreadsLoading(true);
  try {
    const data = await fetchThreads({ limit: 50 });
    setThreads(data.threads || []);
  } catch (e) { /* */ }
  finally { setThreadsLoading(false); }
}

async function handleDeleteThread(threadId) {
  if (!confirm("确定删除此对话？")) return;
  try {
    await deleteThread(threadId);
    setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
  } catch (e) { alert("删除失败: " + e.message); }
}

async function handleViewThread(threadId) {
  try {
    const data = await fetchMemoryThread(threadId);
    setSelectedThreadId(threadId);
    setThreadDetail(data);
  } catch (e) { alert("加载失败: " + e.message); }
}
```

- [ ] **Step 2: Add thread list UI**

Add tab switcher and thread list panel in the MemoryPage JSX. Key structure:

```jsx
{/* Tab switcher */}
<div className="mem-tabs">
  <button className={threadTab === "memory" ? "active" : ""} onClick={() => setThreadTab("memory")}>记忆库</button>
  <button className={threadTab === "threads" ? "active" : ""} onClick={() => { setThreadTab("threads"); loadThreads(); }}>对话历史</button>
</div>

{/* Thread list panel */}
{threadTab === "threads" && (
  <div className="thread-list-panel">
    {threadsLoading && <Loader2 className="spin" />}
    {threads.map((t) => (
      <div key={t.thread_id} className="thread-row" onClick={() => handleViewThread(t.thread_id)}>
        <span className="thread-title">{t.title || "未命名对话"}</span>
        <span className="thread-preview">{t.last_message?.slice(0, 60) || ""}</span>
        <span className="thread-meta">{t.turn_count || 0} 轮 · {formatTime(t.updated_at)}</span>
        <button className="btn ghost sm" onClick={(e) => { e.stopPropagation(); handleDeleteThread(t.thread_id); }}>
          <Minus size={12} />
        </button>
      </div>
    ))}
    {!threadsLoading && threads.length === 0 && <div className="empty-state">暂无对话记录</div>}
  </div>
)}
```

- [ ] **Step 3: Add CSS for thread list**

In `app.css`, add styles:

```css
.thread-list-panel { display: flex; flex-direction: column; gap: 2px; }
.thread-row { display: grid; grid-template-columns: minmax(0, 1fr) 120px 36px; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.thread-row:hover { background: oklch(1 0 0 / 0.03); }
.thread-title { font-size: 13px; font-weight: 600; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thread-preview { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thread-meta { font-size: 10.5px; color: var(--muted); font-family: var(--mono); text-align: right; }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/MemoryPage.jsx frontend/src/styles/app.css
git commit -m "feat: add conversation history tab to Memory page"
```

---

### Task 7: Frontend — Visual polish with UI/UX Pro Max styles

**Files:**
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Tighten bottom panel for 3-row fit**

```css
.bottom-grid {
  --bottom-panel-list-height: 100px;  /* ~3 rows at 33px each */
  gap: 8px;
}

.card-head {
  padding: 5px 10px;  /* tighter header */
}

.trace-event-row {
  grid-template-columns: 28px 48px minmax(0, 1fr) auto;
  gap: 6px;
  padding: 4px 10px;  /* compact row */
  font-size: 10.5px;
}

.art-row {
  padding: 4px 10px;
}
```

- [ ] **Step 2: Add subtle tech-accent glow to active items**

```css
.trace-event-row[data-tone="info"] .dot { box-shadow: 0 0 4px var(--info); }
.activity-pill .dot { width: 5px; height: 5px; border-radius: 50%; display: inline-block; margin-right: 4px; }
```

- [ ] **Step 3: Verify layout**

Manual check: open `http://127.0.0.1:5173`, verify bottom panel shows ~3 rows compactly, scrolling works.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/app.css
git commit -m "style: compact bottom panel with UI/UX Pro Max polish"
```
