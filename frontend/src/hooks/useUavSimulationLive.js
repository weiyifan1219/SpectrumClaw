import { useEffect, useRef, useState } from "react";
import { uavSimulationLiveUrl } from "../lib/api.js";

/**
 * Subscribe to compact Gazebo / PX4 state.  Image frames remain normal HTTP
 * resources, so reconnecting the state socket never repeats large JPEG blobs.
 */
export function useUavSimulationLive(enabled, snapshotIntervalMs = 250, includeSpectrum = false) {
  const [snapshot, setSnapshot] = useState(null);
  const [connection, setConnection] = useState("idle");
  const retryRef = useRef(null);
  const pendingSnapshotRef = useRef(null);
  const publishTimerRef = useRef(null);
  const lastPublishedAtRef = useRef(0);

  useEffect(() => {
    if (!enabled) return undefined;
    let disposed = false;
    let socket = null;

    const connect = () => {
      if (disposed) return;
      setConnection("connecting");
      try {
        socket = new WebSocket(uavSimulationLiveUrl(includeSpectrum));
      } catch {
        setConnection("offline");
        return;
      }
      socket.onopen = () => !disposed && setConnection("online");
      socket.onmessage = (event) => {
        try {
          const next = JSON.parse(event.data);
          if (disposed || next?.type !== "uav_live_v1") return;
          const now = performance.now();
          const elapsed = now - lastPublishedAtRef.current;
          if (elapsed >= snapshotIntervalMs) {
            lastPublishedAtRef.current = now;
            setSnapshot(next);
            return;
          }
          // Camera pixels arrive through MJPEG independently.  Coalescing
          // telemetry keeps those frames off React's reconciliation path.
          pendingSnapshotRef.current = next;
          if (publishTimerRef.current) return;
          publishTimerRef.current = window.setTimeout(() => {
            publishTimerRef.current = null;
            const pending = pendingSnapshotRef.current;
            pendingSnapshotRef.current = null;
            if (!disposed && pending) {
              lastPublishedAtRef.current = performance.now();
              setSnapshot(pending);
            }
          }, Math.max(0, snapshotIntervalMs - elapsed));
        } catch {
          // A malformed frame must not tear down the currently rendered scene.
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnection("offline");
        retryRef.current = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      disposed = true;
      if (retryRef.current) window.clearTimeout(retryRef.current);
      if (publishTimerRef.current) window.clearTimeout(publishTimerRef.current);
      publishTimerRef.current = null;
      pendingSnapshotRef.current = null;
      socket?.close();
    };
  }, [enabled, snapshotIntervalMs, includeSpectrum]);

  return { snapshot, connection };
}
