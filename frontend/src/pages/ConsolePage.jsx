import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowRight,
  ChevronDown,
  Download,
  Eye,
  FileCode,
  FileText,
  MessageSquare,
  PanelLeft,
  Plus,
  Trash2,
  X,
  FolderOpen,
  File
} from "lucide-react";
import {
  artifacts as _unusedArtifacts,
  initialMessages,
  skills,
  taskLogSeed as _unusedTaskLog
} from "../data/mockData.js";
import { sendChat, sendChatStream, submitFeedback, fetchSystemLogs, fetchSystemLog, fetchSystemArtifacts, fetchArtifactPreview, artifactDownloadUrl, fetchJobs, fetchJob, fetchThreads, fetchMemoryThread } from "../lib/api.js";
import Composer from "../components/console/Composer.jsx";
import MessageList from "../components/console/MessageList.jsx";
import { useModelOptions } from "../hooks/useModelOptions.js";

/* ── localStorage helpers ── */
const CHAT_KEY = "sc_chat";
const THREAD_KEY = "sc_thread_id";
const TASKLOG_KEY = "sc_tasklog";
const ARTIFACTS_CACHE_KEY = "sc_artifacts";
const PENDING_JOB_KEY = "sc_pending_job";
const MAX_TASK_LOG = 50;
const DEFAULT_TOOL_NAMES = ["get_time", "get_system_status", "get_weather", "web_search", "web_fetch", "search_knowledge_base"];
const STAGE_LABELS = {
  router: "路由",
  rag_search: "知识库检索",
  tool_executor: "工具调用",
  web_search: "联网搜索",
};

function uid() { return "thread_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8); }
function formatSize(bytes) {
  if (!bytes || bytes < 0) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0, v = bytes;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(i === 0 ? 0 : 1) + " " + u[i];
}
function timeAgo(ts) {
  if (!ts) return "";
  const diff = (Date.now() - ts * 1000) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + "分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + "小时前";
  return Math.floor(diff / 86400) + "天前";
}
function loadThreadId() {
  try { const v = localStorage.getItem(THREAD_KEY); if (v) return v; } catch { /* */ }
  const id = uid();
  try { localStorage.setItem(THREAD_KEY, id); } catch { /* */ }
  return id;
}
function saveThreadId(v) { try { localStorage.setItem(THREAD_KEY, v); } catch { /* */ } }

function threadMsgsKey(tid) { return `sc_msgs_${tid}`; }

function loadMsgsForThread(tid) {
  try {
    const raw = localStorage.getItem(threadMsgsKey(tid));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch { /* */ }
  return null;
}

function saveMsgsForThread(tid, msgs) {
  try {
    const arr = msgs.slice(-80); // keep last 80 messages max
    localStorage.setItem(threadMsgsKey(tid), JSON.stringify(arr));
  } catch { /* */ }
}

function threadTitleKey(tid) { return `sc_title_${tid}`; }
function loadThreadTitle(tid) {
  try { return localStorage.getItem(threadTitleKey(tid)) || ""; } catch { return ""; }
}
function saveThreadTitle(tid, title) {
  try { localStorage.setItem(threadTitleKey(tid), title); } catch { /* */ }
}

function threadMessagesFromDetail(data) {
  const events = (data?.events || []).filter((e) => e.role === "user" || e.role === "assistant");
  return events.map((e) => ({
    role: e.role,
    content: e.content || "",
    meta: { ts: formatShortTime(e.created_at), done: true },
  }));
}

function loadMsgs() {
  const tid = loadThreadId();
  if (tid) {
    const threadMsgs = loadMsgsForThread(tid);
    if (threadMsgs?.length) return threadMsgs;
  }
  try {
    const raw = localStorage.getItem(CHAT_KEY);
    if (raw) { const p = JSON.parse(raw); if (Array.isArray(p) && p.length) return p; }
  } catch { /* ignore */ }
  return null;
}
function saveMsgs(m) { try { localStorage.setItem(CHAT_KEY, JSON.stringify(m)); } catch { /* */ } }

function newChatId() { return "thread_" + Math.random().toString(36).slice(2, 14); }

function loadTaskLog() {
  try {
    const raw = localStorage.getItem(TASKLOG_KEY);
    if (raw) { const p = JSON.parse(raw); if (Array.isArray(p)) return p; }
  } catch { /* */ }
  return [];
}
function saveTaskLog(log) {
  try { localStorage.setItem(TASKLOG_KEY, JSON.stringify(log.slice(0, MAX_TASK_LOG))); } catch { /* */ }
}

function eventStageName(event) {
  if (!event) return "运行阶段";
  return STAGE_LABELS[event.stage] || event.label || event.stage || "运行阶段";
}

function mergePipelineStep(pipeline, event) {
  const id = event.stage || event.label || "stage";
  const step = {
    id,
    name: eventStageName(event),
    status: event.status === "done" || event.type === "stage_done" ? "done" : "active",
  };
  const next = Array.isArray(pipeline) ? [...pipeline] : [];
  const idx = next.findIndex((item) => item.id === id);
  if (idx >= 0) next[idx] = { ...next[idx], ...step };
  else next.push(step);
  return next.slice(-6);
}

function eventDataLabel(data) {
  if (!data || typeof data !== "object") return "";
  return data.name || data.tool || data.source || data.path || data.title || "";
}

function formatShortTime(iso) {
  if (!iso) return "";
  try { const d = new Date(iso); const pad = (n) => String(n).padStart(2, "0"); return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; } catch { return iso; }
}

function formatAbsoluteTime(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return "—";
  }
}

function jobStatusTone(status) {
  if (status === "completed") return "ok";
  if (status === "running") return "info";
  if (status === "error") return "warn";
  return "muted";
}

function jobStatusText(status) {
  if (status === "completed") return "已完成";
  if (status === "running") return "运行中";
  if (status === "error") return "失败";
  return status || "未知";
}

function traceEventLabel(event) {
  if (!event) return "事件";
  if (event.type === "stage" || event.type === "stage_done") {
    return `${event.label || event.stage || "阶段"} · ${event.status === "done" || event.type === "stage_done" ? "完成" : "开始"}`;
  }
  if (event.type === "tool_call") return `工具调用 · ${eventDataLabel(event.data) || "执行中"}`;
  if (event.type === "tool_result") return `工具结果 · ${eventDataLabel(event.data) || "已返回"}`;
  if (event.type === "rag_result") return `知识命中 · ${eventDataLabel(event.data) || "RAG"}`;
  if (event.type === "memory_write") return `记忆写入 · ${event.data?.candidates ?? 0} 条`;
  if (event.type === "done") return "运行完成";
  if (event.type === "error") return event.data || "运行失败";
  if (event.type === "content") return "回答流输出";
  if (event.type === "thinking") return "思考流输出";
  return event.type || event.event || "事件";
}

function activityTone(level) {
  if (level === "completed" || level === "done" || level === "ok") return "ok";
  if (level === "error" || level === "warn") return "warn";
  return "info";
}

function FileTypeIcon({ type }) {
  if (type === "JSON") return <FileCode size={14} color="var(--accent)" />;
  return <FileText size={14} color="var(--accent-2)" />;
}

export default function ConsolePage({ active = true, onOpenSkill, onModelChange }) {
  const [skillSel, setSkillSel] = useState("chat");
  const [messages, setMessages] = useState(() => loadMsgs() ?? initialMessages);
  const [logs, setLogs] = useState(() => loadTaskLog());
  const [logDetail, setLogDetail] = useState(null);  // { name, content } when viewing
  const [logList, setLogList] = useState([]);        // list of log file names
  const [artifacts, setArtifacts] = useState(() => {
    try {
      const cached = localStorage.getItem(ARTIFACTS_CACHE_KEY);
      if (cached) return JSON.parse(cached);
    } catch { /* */ }
    return [];
  });
  const [preview, setPreview] = useState(null);       // { name, content } modal
  const [artLoading, setArtLoading] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [jobDetail, setJobDetail] = useState(null);
  const [jobError, setJobError] = useState("");
  const [jobsState, setJobsState] = useState("unknown");
  const [jobLoading, setJobLoading] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [showLogFiles, setShowLogFiles] = useState(false);
  const logDropdownRef = useRef(null);
  const [draft, setDraft] = useState("");
  const [threadId, setThreadId] = useState(() => loadThreadId());
  const [convListOpen, setConvListOpen] = useState(false);
  const [threadList, setThreadList] = useState([]);
  const [threadLoading, setThreadLoading] = useState(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const bodyRef = useRef(null);
  const switchRequestRef = useRef(0);
  const threadMessagesCacheRef = useRef(new Map());
  const threadFetchCacheRef = useRef(new Map());
  const modelState = useModelOptions({ onModelChange });
  const {
    activeModel,
    canUseReasoning,
    reasoningEffort,
    thinkingEnabled,
  } = modelState;

  const activeSkill = useMemo(
    () => (skillSel === "chat" ? null : skills.find((s) => s.id === skillSel) ?? null),
    [skillSel]
  );
  const selectedJob = useMemo(
    () => jobs.find((job) => job.job_id === selectedJobId) ?? jobs[0] ?? null,
    [jobs, selectedJobId]
  );
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
        if (!thinkingEnabled && entry.tag === "Agent" && (entry.msg.includes("路由") || entry.msg.includes("Route"))) return false;
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
    // Collapse duplicate content/thinking stream entries to one each
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
  const visibleArtifacts = artifacts;
  const jobsEnabled = jobsState === "ready";
  const activityStatusText = useMemo(() => {
    if (jobsEnabled) return `RUNS · ${jobs.length} · LOGS · ${logs.length}`;
    if (jobsState === "unsupported") return `LOCAL LOGS · ${logs.length}`;
    if (jobsState === "error") return `TRACE 异常 · LOGS · ${logs.length}`;
    return jobLoading && jobs.length === 0 ? "加载中…" : `LOGS · ${logs.length}`;
  }, [jobLoading, jobs.length, jobsEnabled, jobsState, logs.length]);

  const loadJobs = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setJobLoading(true);
    try {
      const data = await fetchJobs({ limit: 12 });
      const list = data.jobs || [];
      setJobsState("ready");
      setJobs(list);
      setSelectedJobId((current) => current && list.some((job) => job.job_id === current) ? current : (list[0]?.job_id || ""));
      setJobError("");
    } catch (err) {
      const message = err.message || "无法读取 Job 列表";
      if (message.includes("(404)")) {
        setJobsState("unsupported");
        setJobs([]);
        setSelectedJobId("");
        setJobDetail(null);
        setJobError("");
      } else {
        setJobsState("error");
        if (!silent) setJobError(message);
      }
    } finally {
      if (!silent) setJobLoading(false);
    }
  }, []);

  const loadJobDetail = useCallback(async (jobId, { silent = false } = {}) => {
    if (!jobId) {
      setJobDetail(null);
      return;
    }
    if (!silent) setJobLoading(true);
    try {
      const data = await fetchJob(jobId, { eventLimit: 120 });
      setJobDetail(data);
      if (!silent) setJobError("");
    } catch (err) {
      if (!silent) setJobError(err.message || "无法读取 Trace 详情");
    } finally {
      if (!silent) setJobLoading(false);
    }
  }, []);

  /* persist messages */
  useEffect(() => { saveMsgs(messages); }, [messages]);

  /* auto-scroll */
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages]);

  /* close popovers on outside click */
  useEffect(() => {
    function onDoc() { setModelOpen(false); setSkillOpen(false); }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  /* ── fetch system log file list (for "查看完整日志" click) ── */
  useEffect(() => {
    if (!active) return undefined;
    let mounted = true;
    async function load() {
      try {
        const data = await fetchSystemLogs();
        if (!mounted) return;
        setLogList(data.logs || []);
      } catch { /* best-effort */ }
    }
    load();
    const interval = setInterval(load, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [active]);

  useEffect(() => {
    if (!active) return undefined;
    let mounted = true;
    async function load({ silent = false } = {}) {
      if (!silent) setArtLoading(true);
      try {
        const data = await fetchSystemArtifacts({ limit: 30 });
        if (!mounted) return;
        const list = data.artifacts || [];
        setArtifacts(list);
        try { localStorage.setItem(ARTIFACTS_CACHE_KEY, JSON.stringify(list)); } catch { /* */ }
      } catch { /* best-effort */ }
      finally { if (mounted && !silent) setArtLoading(false); }
    }
    load({ silent: artifacts.length > 0 });
    const interval = setInterval(() => load({ silent: true }), 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [active, artifacts.length]);

  useEffect(() => {
    if (!active) return undefined;
    loadJobs({ silent: jobs.length > 0 });
    const interval = setInterval(() => { loadJobs({ silent: true }); }, 10000);
    return () => clearInterval(interval);
  }, [active, jobs.length, loadJobs]);

  /* ── Conversation list ── */
  const loadThreadList = useCallback(async () => {
    try {
      const data = await fetchThreads({ limit: 50 });
      setThreadList(data.threads || []);
    } catch { /* */ }
  }, []);

  useEffect(() => {
    if (!active) return;
    loadThreadList();
    const interval = setInterval(loadThreadList, 15000);
    return () => clearInterval(interval);
  }, [active, loadThreadList]);

  const getCachedThreadMessages = useCallback((tid) => {
    if (!tid) return null;
    const memoryCached = threadMessagesCacheRef.current.get(tid);
    if (memoryCached?.length) return memoryCached;
    const localCached = loadMsgsForThread(tid);
    if (localCached?.length) {
      threadMessagesCacheRef.current.set(tid, localCached);
      return localCached;
    }
    return null;
  }, []);

  const fetchThreadMessages = useCallback((tid) => {
    const cached = getCachedThreadMessages(tid);
    if (cached?.length) return Promise.resolve(cached);

    const pending = threadFetchCacheRef.current.get(tid);
    if (pending) return pending;

    const request = fetchMemoryThread(tid)
      .then((data) => {
        const msgs = threadMessagesFromDetail(data);
        if (msgs.length) {
          threadMessagesCacheRef.current.set(tid, msgs);
          saveMsgsForThread(tid, msgs);
        }
        return msgs;
      })
      .finally(() => {
        threadFetchCacheRef.current.delete(tid);
      });

    threadFetchCacheRef.current.set(tid, request);
    return request;
  }, [getCachedThreadMessages]);

  useEffect(() => {
    if (!active || !convListOpen || threadList.length === 0) return undefined;
    let cancelled = false;
    const timers = threadList.slice(0, 8).map((t, idx) => setTimeout(() => {
      if (!cancelled) fetchThreadMessages(t.thread_id).catch(() => {});
    }, idx * 90));
    return () => {
      cancelled = true;
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [active, convListOpen, threadList, fetchThreadMessages]);

  function prefetchThread(tid) {
    fetchThreadMessages(tid).catch(() => {});
  }

  async function switchToThread(tid) {
    if (tid === threadId) { setConvListOpen(false); return; }
    const requestId = switchRequestRef.current + 1;
    switchRequestRef.current = requestId;
    // Save current messages before switching
    if (messages.length > 0) {
      saveMsgsForThread(threadId, messages);
    }

    const row = threadList.find((t) => t.thread_id === tid);
    const cachedMsgs = getCachedThreadMessages(tid);
    setThreadId(tid);
    saveThreadId(tid);
    setMessages(cachedMsgs || []);
    setThreadLoading(cachedMsgs?.length ? null : {
      threadId: tid,
      title: loadThreadTitle(tid) || row?.title || "历史对话",
      preview: row?.last_message || "",
    });
    setLogs([]);
    saveTaskLog([]);
    localStorage.removeItem(PENDING_JOB_KEY);
    setConvListOpen(false);

    const apiBase = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8230`;
    fetch(`${apiBase}/api/memory/threads/${encodeURIComponent(tid)}/touch`, { method: "POST" }).catch(() => {});

    if (cachedMsgs?.length) return;

    try {
      const msgs = await fetchThreadMessages(tid);
      if (switchRequestRef.current !== requestId) return;
      setThreadLoading(null);
      if (msgs.length > 0) {
        setMessages(msgs);
      } else {
        setMessages([{
          role: "assistant",
          content: "这个历史对话暂时没有可恢复的完整消息内容。",
          meta: { ts: new Date().toLocaleTimeString("zh-CN", { hour12: false }), done: true },
        }]);
      }
    } catch {
      if (switchRequestRef.current !== requestId) return;
      setThreadLoading(null);
      setMessages([{
        role: "assistant",
        content: "历史消息加载失败。请稍后重试，或重新打开历史列表。",
        meta: { ts: new Date().toLocaleTimeString("zh-CN", { hour12: false }), error: true },
      }]);
    }
  }

  function handleNewChat() {
    if (messages.length > 0) {
      saveMsgsForThread(threadId, messages);
    }
    const id = newChatId();
    setMessages(initialMessages);
    setThreadLoading(null);
    setThreadId(id);
    saveThreadId(id);
    setLogs([]);
    saveTaskLog([]);
    localStorage.removeItem(PENDING_JOB_KEY);
    loadThreadList();
  }

  useEffect(() => {
    if (!active || !selectedJobId || !jobsEnabled) return undefined;
    loadJobDetail(selectedJobId, { silent: !!jobDetail && jobDetail.job_id === selectedJobId });
    const current = jobs.find((job) => job.job_id === selectedJobId);
    const interval = setInterval(
      () => { loadJobDetail(selectedJobId, { silent: true }); },
      current?.status === "running" ? 2500 : 10000,
    );
    return () => clearInterval(interval);
  }, [active, selectedJobId, jobs, jobDetail, jobsEnabled, loadJobDetail]);

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
          pollTimer = setTimeout(poll, 2000);
          return;
        }
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
            const lastAssistant = [...curr].reverse().find((m) => m.role === "assistant" && m.meta?.streaming);
            const recovered = {
              role: "assistant",
              content: contentEvents || `[错误] ${job.last_error || "未知错误"}`,
              reasoning: reasoningEvents || undefined,
              meta: {
                ts: job.finished_at ? new Date(job.finished_at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "",
                streaming: false,
                done: true,
                id: Date.now(),
                job_id: pendingJobId,
              },
            };
            if (lastAssistant && !lastAssistant.content) {
              const idx = curr.indexOf(lastAssistant);
              const next = [...curr];
              next[idx] = recovered;
              return next;
            }
            return [...curr, recovered];
          });
          addTaskLog("ok", `运行完成 · 已恢复`, "Agent");
        }
        localStorage.removeItem(PENDING_JOB_KEY);
      } catch {
        if (mounted) localStorage.removeItem(PENDING_JOB_KEY);
      }
    }

    pollTimer = setTimeout(poll, 500);
    return () => { mounted = false; clearTimeout(pollTimer); };
  }, [active]);

  async function viewLog(name) {
    if (logDetail?.name === name) { setLogDetail(null); return; }
    try {
      const data = await fetchSystemLog(name, { tail: 200 });
      setLogDetail({ name, content: data.content });
    } catch { /* best-effort */ }
  }

function artifactViewUrl(path) {
  return artifactDownloadUrl(path) + "?inline=true";
}

  async function openPreview(art) {
    if (art.preview_type === "image") {
      setPreview({ name: art.name, imageUrl: artifactViewUrl(art.path), isImage: true });
      return;
    }
    if (art.preview_type === "pdf") {
      setPreview({ name: art.name, pdfUrl: artifactViewUrl(art.path), isPdf: true });
      return;
    }
    try {
      const data = await fetchArtifactPreview(art.path);
      setPreview({ name: art.name, content: data.content, isImage: false, isPdf: false });
    } catch (e) {
      setPreview({ name: art.name, content: `预览失败: ${e.message}`, error: true, isImage: false, isPdf: false });
    }
  }

  const addTaskLog = useCallback((level, msg, tag) => {
    const tsMs = Date.now();
    const ts = new Date(tsMs).toLocaleTimeString("zh-CN", { hour12: false });
    setLogs((curr) => {
      const next = [{ ts, tsMs, level, msg, tag }, ...curr];
      saveTaskLog(next);
      return next;
    });
  }, []);

  async function submit(e) {
    e?.preventDefault?.();
    const text = draft.trim();
    if (!text || sending) return;

    const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const userMsg = { role: "user", content: text, meta: { ts } };
    setDraft("");
    setSending(true);

    // task log: user action
    if (activeSkill) {
      addTaskLog("info", `「${activeSkill.label}」任务发起 · ${text.slice(0, 40)}${text.length > 40 ? "…" : ""}`, activeSkill.label);
    } else {
      addTaskLog("info", `对话 · ${text.slice(0, 50)}${text.length > 50 ? "…" : ""}`, "Chat");
    }

    const history = [...messages, userMsg];
    const placeholderId = Date.now();
    const placeholderMsg = {
      role: "assistant",
      content: "",
      meta: { skill: activeSkill?.label ?? null, ts, streaming: true, id: placeholderId },
      reasoning: "",
    };
    setMessages([...history, placeholderMsg]);
    // Save immediately so thread appears in sidebar even before completion
    saveMsgsForThread(threadId, [...history, placeholderMsg]);

    const apiMessages = history
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    const useReasoning = canUseReasoning && thinkingEnabled && reasoningEffort !== "off";
    await sendChatStream(apiMessages, {
      provider: activeModel.provider,
      model: activeModel.model,
      thinking_enabled: useReasoning,
      reasoning_effort: useReasoning ? reasoningEffort : "off",
      tool_names: DEFAULT_TOOL_NAMES,
      thread_id: threadId,
    }, (event) => {
      if (event.job_id) {
        setSelectedJobId(event.job_id);
        localStorage.setItem(PENDING_JOB_KEY, event.job_id);
      }
      if (event.event === "stage" || event.type === "stage" || event.type === "stage_done") {
        const stageName = eventStageName(event);
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], pipeline: mergePipelineStep(next[idx].pipeline, event) };
          }
          return next;
        });
        addTaskLog(event.status === "done" || event.type === "stage_done" ? "ok" : "info", `${stageName} · ${event.status === "done" || event.type === "stage_done" ? "完成" : "开始"}`, "Agent");
      } else if (event.type === "tool_call") {
        addTaskLog("info", `工具调用 · ${eventDataLabel(event.data) || "运行中"}`, "Tool");
      } else if (event.type === "tool_result") {
        addTaskLog("ok", `工具结果 · ${eventDataLabel(event.data) || "已返回"}`, "Tool");
      } else if (event.type === "rag_result") {
        addTaskLog("info", `知识命中 · ${eventDataLabel(event.data) || "RAG"}`, "RAG");
      } else if (event.type === "memory_write") {
        const count = event.data?.candidates ?? 0;
        addTaskLog("ok", `记忆沉淀 · ${count} 条候选`, "Memory");
      } else if (event.type === "artifact") {
        addTaskLog("ok", `产出物 · ${eventDataLabel(event.data) || "已生成"}`, "Artifact");
      } else if (event.type === "thinking") {
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], reasoning: (next[idx].reasoning || "") + event.data };
          }
          return next;
        });
      } else if (event.type === "content") {
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], content: next[idx].content + event.data };
          }
          return next;
        });
      } else if (event.type === "done") {
        localStorage.removeItem(PENDING_JOB_KEY);
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], meta: { ...next[idx].meta, streaming: false, done: true, feedbackId: event.data?.feedback_target_id || null } };
          }
          saveMsgsForThread(threadId, next);
          // Auto-title: use first user message as title
          const firstUser = next.find((m) => m.role === "user");
          if (firstUser) {
            const title = firstUser.content.slice(0, 40);
            saveThreadTitle(threadId, title);
          }
          return next;
        });
        if (activeSkill) {
          addTaskLog("ok", `「${activeSkill.label}」任务完成`, activeSkill.label);
          saveThreadTitle(threadId, `调用 ${activeSkill.label} 技能`);
        } else {
          addTaskLog("ok", "对话完成", "Chat");
        }
        loadJobs({ silent: true });
        loadThreadList();
      } else if (event.type === "error") {
        localStorage.removeItem(PENDING_JOB_KEY);
        addTaskLog("error", `请求失败 · ${(event.data || "未知错误").slice(0, 60)}`, "Error");
        setMessages((curr) => {
          const next = [...curr];
          const idx = next.findIndex((m) => m.meta?.id === placeholderId);
          if (idx >= 0) {
            next[idx] = { ...next[idx], content: event.data || "请求失败", meta: { ...next[idx].meta, error: true, streaming: false, userMsgIndex: history.length - 1 } };
          }
          return next;
        });
        loadJobs({ silent: true });
      }
    });

    setSending(false);
  }

  async function retry(errorIndex) {
    const errMsg = messages[errorIndex];
    if (!errMsg?.meta?.error || sending) return;
    const ui = errMsg.meta.userMsgIndex;
    if (ui == null || !messages[ui] || messages[ui].role !== "user") return;

    setSending(true);
    addTaskLog("info", "重试上一次请求", "Retry");

    // remove the error bubble, keep the user message
    const clean = [...messages];
    clean.splice(errorIndex, 1);
    setMessages(clean);

    try {
      const apiMessages = clean
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      const retryUseReasoning = canUseReasoning && thinkingEnabled && reasoningEffort !== "off";
      const result = await sendChat(apiMessages, {
        provider: activeModel.provider,
        model: activeModel.model,
        thinking_enabled: retryUseReasoning,
        reasoning_effort: retryUseReasoning ? reasoningEffort : "off",
        tool_names: DEFAULT_TOOL_NAMES,
      });
      const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });

      setMessages((curr) => [
        ...curr,
        {
          role: "assistant",
          content: result.reply,
          meta: { skill: activeSkill?.label ?? null, ts }
        }
      ]);
    } catch (err2) {
      setMessages((curr) => [
        ...curr,
        {
          role: "assistant",
          content: err2.message || "重试失败",
          meta: { skill: null, ts: new Date().toLocaleTimeString("zh-CN", { hour12: false }), error: true, userMsgIndex: ui }
        }
      ]);
    } finally {
      setSending(false);
    }
  }

  async function handleFeedback(msgIndex, rating) {
    const msg = messages[msgIndex];
    if (!msg?.meta?.feedbackId) return;
    try {
      await submitFeedback({ targetType: "answer", targetId: msg.meta.feedbackId, rating });
      setMessages((curr) => {
        const next = [...curr];
        next[msgIndex] = { ...next[msgIndex], meta: { ...next[msgIndex].meta, feedbackRating: rating } };
        return next;
      });
    } catch { /* best-effort */ }
  }

  function clearChat() {
    setMessages([initialMessages[0]]);
    setThreadLoading(null);
    saveMsgs([initialMessages[0]]);
    const newId = uid();
    setThreadId(newId);
    saveThreadId(newId);
  }

  const skillSelLabel = skillSel === "chat" ? "普通对话" : activeSkill?.label;
  const modeLabel = skillSel === "chat" ? "普通对话模式" : `技能模式 · ${activeSkill?.label}`;
  const modelProps = { ...modelState, modelOpen, setModelOpen };

  return (
    <div className="page console-page">
      {/* ── Conversation sidebar (rendered via Portal to escape overflow hidden) ── */}
      {convListOpen && createPortal(
        <>
          <div className="conv-overlay" onClick={() => setConvListOpen(false)} />
          <div className="conv-sidebar open">
            <div className="conv-sidebar-head">
              <span className="cn-title sm">对话列表</span>
              <button className="btn ghost sm" onClick={() => setConvListOpen(false)}><X size={14} /></button>
            </div>
            <button className="conv-new-btn" onClick={handleNewChat}>
              <Plus size={14} /> 新对话
            </button>
            <div className="conv-list">
              {threadList.map((t) => {
                const localTitle = loadThreadTitle(t.thread_id);
                const displayTitle = localTitle || t.title || "未命名对话";
                return (
	                  <div key={t.thread_id}
	                    className={`conv-item ${t.thread_id === threadId ? "active" : ""}`}
	                    onMouseEnter={() => prefetchThread(t.thread_id)}
	                    onFocus={() => prefetchThread(t.thread_id)}
	                    onClick={() => switchToThread(t.thread_id)}>
                    <div className="conv-item-main">
                      <span className="conv-item-title">{displayTitle}</span>
                      <span className="conv-item-preview">{t.last_message?.slice(0, 50) || "（空对话）"}</span>
                    </div>
                  </div>
                );
              })}
              {threadList.length === 0 && (
                <div className="conv-empty">暂无对话记录</div>
              )}
            </div>
          </div>
        </>,
        document.body
      )}

      <div className="console-main">
        {/* ───────── Hero: Agent Dialogue ───────── */}
        <section className="chat hero">
        <header className="chat-head">
          <div className="left">
            <span className="eyebrow">AGENT DIALOGUE</span>
            <span className="dot-sep">·</span>
            <span className="cn-title">实时对话</span>
            <span className={`mode-pill ${skillSel === "chat" ? "mode-chat" : `mode-skill acc-${activeSkill?.accent}`}`}>
              {skillSel === "chat" ? <MessageSquare size={11} /> : <span className="ms-dot" />}
              {modeLabel}
            </span>
          </div>
          <div className="right" style={{ gap: 6, display: "flex" }}>
            <button className="btn ghost sm" onClick={() => { setConvListOpen(!convListOpen); loadThreadList(); }} title="历史对话">
              <PanelLeft size={13} /> 历史
            </button>
            <button className="btn ghost sm" onClick={handleNewChat} title="开启新对话">
              <Plus size={13} /> 新对话
            </button>
          </div>
        </header>

	        <MessageList
	          bodyRef={bodyRef}
	          loading={!!threadLoading}
	          loadingSubtitle={threadLoading?.preview}
	          loadingTitle={threadLoading?.title ? `正在加载「${threadLoading.title}」` : "正在加载聊天记录"}
	          messages={messages}
	          onFeedback={handleFeedback}
	          onRetry={retry}
        />

        <Composer
          activeSkill={activeSkill}
          draft={draft}
          modelProps={modelProps}
          onSubmit={submit}
          sending={sending}
          setDraft={setDraft}
          setSkillOpen={setSkillOpen}
          setSkillSel={setSkillSel}
          skillOpen={skillOpen}
          skillSel={skillSel}
          skillSelLabel={skillSelLabel}
        />
      </section>

      {/* ───────── Skill panel (right sidebar) ───────── */}
      <aside className="skill-panel">
        <header className="section-head">
          <span className="cn-title">可用技能</span>
          <span className="eyebrow">SKILLS · {skills.length}</span>
        </header>
        <div className="skill-rail-v">
          {skills.map((s) => {
            const Icon = s.icon;
            const isActive = skillSel === s.id;
            return (
              <article
                key={s.id}
                className={`skill-card acc-${s.accent} ${isActive ? "active" : ""}`}
                onClick={() => setSkillSel(s.id)}
              >
                <div className="sc-glow" aria-hidden="true" />
                <header className="sc-head">
                  <span className="sc-icon"><Icon size={16} /></span>
                  <div className="sc-title">
                    <strong>{s.label}</strong>
                    <small>{s.english}</small>
                  </div>
                </header>
                <p className="sc-desc">{s.summary}</p>
                <footer className="sc-foot">
                  <span className="pill" data-tone={s.statusTone}>
                    <span className="dot" /> {s.status}
                  </span>
                  <button
                    className="sc-open"
                    onClick={(e) => { e.stopPropagation(); onOpenSkill?.(s.id); }}
                  >
                    打开 <ArrowRight size={11} />
                  </button>
                </footer>
              </article>
            );
          })}
          {/* + placeholder card */}
          <article className="skill-card skill-card-add">
            <div className="sc-glow-add" aria-hidden="true" />
            <div className="add-inner">
              <Plus size={24} />
              <span>添加技能</span>
            </div>
          </article>
        </div>
      </aside>
    </div>

      {/* ───────── Bottom: Agent Activity + Artifacts ───────── */}
      <section className="bottom-grid">
        <div className="card panel-card trace-panel activity-panel">
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">AGENT ACTIVITY</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">智能体行为</span>
            </span>
            <div className="activity-head-actions">
              <span className="eyebrow muted">{activityStatusText}</span>
              {logList.length > 0 && (
                <div ref={logDropdownRef} className="activity-head-dropdown">
                  <button
                    className="btn ghost sm"
                    style={{ fontSize: 11, fontFamily: "var(--mono)", padding: "4px 10px", opacity: 0.72 }}
                    onClick={() => setShowLogFiles((v) => !v)}
                  >
                    <FolderOpen size={10} />
                    日志
                    <ChevronDown size={10} style={{ transform: showLogFiles ? "rotate(180deg)" : "", transition: "transform .15s" }} />
                  </button>
                  {showLogFiles && (() => {
                    const rect = logDropdownRef.current?.getBoundingClientRect?.();
                    const top = (rect?.bottom ?? 0) + 6;
                    const right = window.innerWidth - (rect?.right ?? window.innerWidth);
                    const width = 280;
                    return (
                      <>
                        <div style={{ position: "fixed", inset: 0, zIndex: 99 }} onClick={() => setShowLogFiles(false)} />
                        <div style={{
                          position: "fixed", top, right,
                          width, maxHeight: 220, overflowY: "auto",
                          background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
                          boxShadow: "0 8px 24px oklch(0 0 0 / 0.28)", zIndex: 100,
                        }}>
                          {logList.map((f) => (
                            <button
                              key={f.name}
                              className="btn ghost sm"
                              style={{ display: "block", width: "100%", textAlign: "left", fontSize: 11, fontFamily: "var(--mono)", padding: "4px 10px" }}
                              onClick={() => { viewLog(f.name); setShowLogFiles(false); }}
                            >
                              <File size={10} style={{ marginRight: 6 }} />
                              {f.name}
                              <span style={{ opacity: 0.4, marginLeft: 6 }}>{formatSize(f.size)}</span>
                            </button>
                          ))}
                        </div>
                      </>
                    );
                  })()}
                </div>
              )}
              {jobsEnabled && selectedJob && (
                <button
                  type="button"
                  className="activity-run-pill"
                  title={selectedJob.title}
                  onClick={() => setSelectedJobId(selectedJob.job_id)}
                >
                  <span className="activity-run-title">{selectedJob.title}</span>
                  <span className={`pill activity-pill activity-pill-${jobStatusTone(selectedJob.status)}`}>
                    <span className="dot" />{jobStatusText(selectedJob.status)}
                  </span>
                </button>
              )}
            </div>
          </header>
          {jobError && (
            <div style={{ padding: "6px 14px", borderBottom: "1px solid var(--line)", fontSize: 11.5, color: "var(--warn)" }}>
              {jobError}
            </div>
          )}
          <div className="trace-panel-body">
            <div className="trace-event-list">
              {activityFeed.length === 0 && (
                <div className="trace-empty">暂无行为记录，开始对话或运行技能后会自动出现。</div>
              )}
              {activityFeed.map((item) => (
                <div className="trace-event-row" key={item.id} data-tone={item.tone}>
                  <span className="mono trace-seq">{item.marker}</span>
                  <span className="mono trace-ts">{item.tsLabel}</span>
                  <span className="trace-msg">{item.message}</span>
                  <span className={`pill activity-pill activity-pill-${item.tone}`}>
                    <span className="dot" />{item.tag}
                  </span>
                </div>
              ))}
            </div>
          </div>
          {logDetail && (
            <div className="modal-overlay" onClick={() => setLogDetail(null)}>
              <div className="modal-content preview-modal" onClick={(e) => e.stopPropagation()}>
                <header className="modal-head">
                  <span><FileText size={14} /> {logDetail.name}</span>
                  <button className="btn ghost sm" onClick={() => setLogDetail(null)}><X size={14} /></button>
                </header>
                <pre className="preview-body">{logDetail.content}</pre>
              </div>
            </div>
          )}
        </div>

        {/* ── Artifacts ── */}
        <div className="card panel-card">
          <header className="card-head">
            <span className="title">
              <span className="eyebrow">ARTIFACTS</span>
              <span className="dot-sep">·</span>
              <span className="cn-title sm">产出物</span>
            </span>
            <span className="eyebrow muted">
              {artLoading ? "加载中…" : `LATEST · ${artifacts.length}`}
            </span>
          </header>
          <div className="art-list">
            {artifacts.length === 0 && !artLoading && (
              <div className="art-row" style={{ opacity: 0.5 }}>加载产出物列表…</div>
            )}
            {visibleArtifacts.map((a) => (
              <div className="art-row" key={a.path} title={a.path}>
                <FileTypeIcon type={a.type} />
                <span className="name">{a.name}</span>
                <span className="ext mono">{a.type}</span>
                <span className="size mono" style={{ display: "flex", flexDirection: "column", lineHeight: 1.3 }}>
                  <span>{formatSize(a.size)}</span>
                  <span style={{ fontSize: 10, opacity: 0.45 }}>{timeAgo(a.modified)}</span>
                </span>
                <span style={{ display: "flex", gap: 2, flexShrink: 0 }}>
                  {a.previewable && (
                    <button className="btn ghost sm" title={a.preview_type === "image" ? "预览图片" : a.preview_type === "pdf" ? "预览PDF" : "预览"} onClick={() => openPreview(a)}>
                      <Eye size={12} />
                    </button>
                  )}
                  <a className="btn ghost sm" title="下载" href={artifactDownloadUrl(a.path)} download>
                    <Download size={12} />
                  </a>
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Preview Modal ── */}
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <div className="modal-content preview-modal" onClick={(e) => e.stopPropagation()}>
            <header className="modal-head">
              <span><Eye size={14} /> {preview.name}</span>
              <button className="btn ghost sm" onClick={() => setPreview(null)}><X size={14} /></button>
            </header>
            {preview.isPdf ? (
              <iframe src={preview.pdfUrl} style={{ width: "100%", height: "70vh", border: "none" }} title={preview.name} />
            ) : preview.isImage ? (
              <div className="preview-body" style={{ display: "flex", alignItems: "center", justifyContent: "center", background: "oklch(0 0 0 / 0.06)" }}>
                <img src={preview.imageUrl} alt={preview.name} style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain" }} />
              </div>
            ) : (
              <pre className={`preview-body ${preview.error ? "preview-err" : ""}`}>{preview.content}</pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
