import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTopic } from "../api/ws";
import { ApprovalActions } from "./ApprovalActions";

export function ApprovalsQueue({ onSelectSession }: { onSelectSession: (sessionId: string) => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["approvals"], queryFn: api.pendingApprovals });

  useTopic("/ws/approvals", () => {
    qc.invalidateQueries({ queryKey: ["approvals"] });
  });

  const decide = async (id: string, approved: boolean, reason?: string) => {
    await api.decideApproval(id, approved, reason);
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["session"] });
  };

  const pending = data ?? [];

  return (
    <div className="rounded-lg border border-[#24282f] bg-[#14171c] p-3">
      <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
        Approvals {pending.length > 0 && <span className="text-yellow-400">({pending.length})</span>}
      </div>
      {pending.length === 0 && <div className="text-xs text-gray-600">Nothing waiting on you.</div>}
      <div className="space-y-3">
        {pending.map((a) => (
          <div key={a.id} className="rounded border border-[#2a2f37] p-2">
            <button
              onClick={() => onSelectSession(a.session_id)}
              className="text-xs font-medium text-blue-400 hover:underline"
            >
              {a.step_kind === "plan" ? "Plan approval" : "Task diff approval"}
            </button>
            <div className="text-[11px] text-gray-500 mb-2">{new Date(a.created_at).toLocaleTimeString()}</div>
            <ApprovalActions onDecide={(approved, reason) => decide(a.id, approved, reason)} />
          </div>
        ))}
      </div>
    </div>
  );
}
