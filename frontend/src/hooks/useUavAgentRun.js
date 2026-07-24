import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveUavAgentRun,
  cancelUavAgentRun,
  createUavAgentRun,
  fetchUavAgentRun,
  uavAgentRunStreamUrl,
} from "../lib/api.js";

const RUN_CACHE_KEY = "spectrumclaw:uav-agent:last-run";

function cachedRun() {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(RUN_CACHE_KEY) || "null");
    return parsed && typeof parsed.run_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function useUavAgentRun() {
  const [run, setRun] = useState(cachedRun);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sourceRef = useRef(null);

  const closeStream = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const markInterrupted = useCallback((summary = "任务状态连接中断；飞控不会继续执行，请检查仿真状态后重新创建任务。") => {
    closeStream();
    setRun((current) => current ? {
      ...current,
      status: "interrupted",
      summary,
      ended_at: Date.now() / 1000,
      lifecycle: { phase: "interrupted", terminal: true, reason: "orchestrator_connection_lost" },
    } : current);
    setEvents((current) => [...current, { event_type: "interruption", summary, timestamp: Date.now() / 1000 }].slice(-80));
  }, [closeStream]);

  useEffect(() => {
    try {
      if (run) window.sessionStorage.setItem(RUN_CACHE_KEY, JSON.stringify(run));
      else window.sessionStorage.removeItem(RUN_CACHE_KEY);
    } catch {
      // Session storage is a UX convenience only; task truth remains server-side.
    }
  }, [run]);

  const openStream = useCallback((runId) => {
    closeStream();
    const source = new EventSource(uavAgentRunStreamUrl(runId));
    sourceRef.current = source;
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        setEvents((current) => [...current, event].slice(-80));
        if (event.event_type === "run_state") {
          setRun((current) => current ? { ...current, status: event.status, summary: event.summary } : current);
          if (event.status !== "running") {
            source.close();
            // The terminal SSE frame is intentionally tiny. Fetch once so the
            // UI receives the final result/terminal action (for example the
            // confirmed hover) without keeping a live stream open.
            fetchUavAgentRun(runId).then(setRun).catch(() => undefined);
          }
        }
      } catch {
        // The backend already guarantees JSON; ignore a transient malformed frame.
      }
    };
    source.onerror = () => {
      source.close();
      fetchUavAgentRun(runId).then(setRun).catch(() => markInterrupted());
    };
  }, [closeStream, markInterrupted]);

  const createDraft = useCallback(async (intent) => {
    setBusy(true); setError(""); setEvents([]);
    try {
      const next = await createUavAgentRun(intent);
      setRun(next);
      openStream(next.run_id);
      return next;
    } catch (err) {
      setError(err.message || "无法生成任务草案");
      return null;
    } finally { setBusy(false); }
  }, [openStream]);

  const approve = useCallback(async () => {
    if (!run) return null;
    setBusy(true); setError("");
    try {
      const next = await approveUavAgentRun(run.run_id, run.plan_digest);
      setRun(next);
      openStream(next.run_id);
      return next;
    } catch (err) {
      setError(err.message || "任务审批失败");
      return null;
    } finally { setBusy(false); }
  }, [openStream, run]);

  const cancel = useCallback(async () => {
    if (!run) return null;
    setBusy(true); setError("");
    try {
      const next = await cancelUavAgentRun(run.run_id);
      setRun(next);
      closeStream();
      return next;
    } catch (err) {
      setError(err.message || "无法取消任务");
      return null;
    } finally { setBusy(false); }
  }, [closeStream, run]);

  const refresh = useCallback(async () => {
    if (!run?.run_id) return null;
    try {
      const next = await fetchUavAgentRun(run.run_id);
      setRun(next);
      return next;
    } catch (err) {
      markInterrupted();
      return null;
    }
  }, [markInterrupted, run?.run_id]);

  useEffect(() => {
    if (!run?.run_id) return;
    void refresh();
  // Resolve the persistent server record after a tab reload or backend restart.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.run_id]);

  useEffect(() => {
    if (run?.status !== "running") return undefined;
    const timer = window.setInterval(() => { void refresh(); }, 3500);
    return () => window.clearInterval(timer);
  }, [refresh, run?.status]);

  useEffect(() => () => closeStream(), [closeStream]);

  return { run, events, busy, error, createDraft, approve, cancel, refresh };
}
