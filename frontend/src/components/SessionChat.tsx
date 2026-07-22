import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTopic } from "../api/ws";
import type { Approval, Artifact, Plan } from "../api/types";
import { PlanApprovalCard } from "./PlanApprovalCard";
import { TaskApprovalCard } from "./TaskApprovalCard";
import { TaskStatusBadge } from "./TaskStatusBadge";

interface LogLine {
  id: number;
  text: string;
}

let logCounter = 0;

function describeEvent(event: Record<string, unknown>): string | null {
  switch (event.event) {
    case "task_running":
      return `engineer started: ${event.title}`;
    case "task_done":
      return `task merged to main`;
    case "task_rejected":
      return `task rejected${event.reason ? `: ${event.reason}` : ""}`;
    case "task_escalated":
      return `task escalated: ${event.reason}`;
    case "approval_pending":
      return `waiting on your approval`;
    case "approval_resolved":
      return `approval ${event.status}`;
    case "planner_failed":
      return `planner failed: ${event.detail}`;
    case "agent_event": {
      const payload = event.payload as Record<string, unknown> | undefined;
      if (payload?.type === "assistant") return "agent is working...";
      if (payload?.type === "result") return "agent finished this step";
      return null;
    }
    default:
      return null;
  }
}

export function SessionChat({ sessionId, onClosed }: { sessionId: string; onClosed: () => void }) {
  const qc = useQueryClient();
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [request, setRequest] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [killing, setKilling] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  const { data: session } = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId),
  });
  const { data: approvals } = useQuery({ queryKey: ["approvals"], queryFn: api.pendingApprovals });
  const { data: planArtifacts } = useQuery({
    queryKey: ["artifacts", sessionId, "plan"],
    queryFn: () => api.sessionArtifacts(sessionId, "plan"),
  });

  useTopic(`/ws/session/${sessionId}`, (event) => {
    const text = describeEvent(event);
    if (text) setLogs((prev) => [...prev, { id: logCounter++, text }]);
    qc.invalidateQueries({ queryKey: ["session", sessionId] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["artifacts", sessionId] });
    if (event.event === "task_running" || event.event === "task_done") {
      qc.invalidateQueries({ queryKey: ["task"] });
    }
  });

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const sessionApprovals = (approvals ?? []).filter((a: Approval) => a.session_id === sessionId);
  const planApproval = sessionApprovals.find((a) => a.step_kind === "plan");
  const taskApproval = sessionApprovals.find((a) => a.step_kind === "task");

  const planArtifact: Artifact | undefined = planApproval
    ? planArtifacts?.find((a) => a.id === planApproval.payload_ref)
    : undefined;

  const decidePlan = async (approved: boolean, reason?: string, editedPlan?: Plan) => {
    if (!planApproval) return;
    await api.decideApproval(planApproval.id, approved, reason, editedPlan);
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["session", sessionId] });
  };

  const decideTask = async (approved: boolean, reason?: string) => {
    if (!taskApproval) return;
    await api.decideApproval(taskApproval.id, approved, reason);
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["session", sessionId] });
  };

  const submitRequest = async () => {
    if (!request.trim()) return;
    setSubmitting(true);
    setLogs((prev) => [...prev, { id: logCounter++, text: `you: ${request}` }]);
    try {
      await api.submitRequest(sessionId, request);
      setLogs((prev) => [...prev, { id: logCounter++, text: "planner is working..." }]);
      setRequest("");
    } finally {
      setSubmitting(false);
    }
  };

  const killSession = async () => {
    if (!confirm("Kill this session? Any in-flight agent work is cancelled and its worktree removed.")) return;
    setKilling(true);
    try {
      await api.closeSession(sessionId);
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["worktrees"] });
      onClosed();
    } finally {
      setKilling(false);
    }
  };

  if (!session) return <div className="p-4 text-sm text-gray-500">loading...</div>;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[#24282f] px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-white">{session.title}</div>
          <div className="text-xs text-gray-500 font-mono">{session.branch}</div>
        </div>
        <button
          onClick={killSession}
          disabled={killing}
          className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
        >
          {killing ? "killing..." : "kill session"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {session.tasks && session.tasks.length > 0 && (
          <div className="space-y-1.5 mb-2">
            {session.tasks.map((t) => (
              <div key={t.id}>
                <div className="flex items-center gap-2 text-xs">
                  <TaskStatusBadge status={t.status} />
                  <span className="text-gray-300">{t.title}</span>
                </div>
                {t.outcome_reason && (
                  <div className="mt-1 ml-1 rounded border border-orange-700/40 bg-orange-500/5 px-2 py-1.5 text-[11px] text-orange-300">
                    <span className="font-medium">
                      {t.status === "escalated" ? "Escalated" : "Rejected"}
                      {t.failure_class ? ` (${t.failure_class.replace(/_/g, " ")})` : ""}:
                    </span>{" "}
                    {t.outcome_reason}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {planApproval && (
          <PlanApprovalCard approval={planApproval} artifact={planArtifact} onDecide={decidePlan} />
        )}
        {taskApproval && <TaskApprovalCard approval={taskApproval} onDecide={decideTask} />}

        <div className="space-y-1">
          {logs.map((l) => (
            <div key={l.id} className="text-xs text-gray-400">
              {l.text}
            </div>
          ))}
        </div>
        <div ref={logEndRef} />
      </div>

      <div className="border-t border-[#24282f] p-3">
        <div className="flex gap-2">
          <input
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitRequest();
              }
            }}
            placeholder="describe what you want built..."
            disabled={submitting}
            className="flex-1 rounded border border-[#2a2f37] bg-[#0b0d10] px-3 py-2 text-sm text-white outline-none focus:border-blue-500 disabled:opacity-50"
          />
          <button
            onClick={submitRequest}
            disabled={submitting || !request.trim()}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
