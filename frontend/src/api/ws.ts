import { useEffect, useRef } from "react";
import { WS_BASE } from "./client";
import { useAuth } from "../store/auth";

/**
 * Subscribes to a backend bus topic over WebSocket for the lifetime of the
 * component. Reconnects with a short fixed backoff on drop - this is a
 * local single-user tool, so a dumb reconnect loop is enough.
 */
export function useTopic(path: string, onEvent: (event: Record<string, unknown>) => void) {
  const token = useAuth((s) => s.token);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!token) return;
    let closedByUs = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      socket = new WebSocket(`${WS_BASE}${path}?token=${encodeURIComponent(token)}`);
      socket.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data));
        } catch {
          // ignore malformed frames
        }
      };
      socket.onclose = () => {
        if (!closedByUs) {
          retryTimer = setTimeout(connect, 1500);
        }
      };
    };
    connect();

    return () => {
      closedByUs = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, [path, token]);
}
