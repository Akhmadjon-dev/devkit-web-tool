import { useState } from "react";
import type { Approval, Artifact, Plan } from "../api/types";
import { ApprovalActions } from "./ApprovalActions";

export function PlanApprovalCard({
  approval,
  artifact,
  onDecide,
}: {
  approval: Approval;
  artifact: Artifact | undefined;
  onDecide: (approved: boolean, reason?: string, editedPlan?: Plan) => void;
}) {
  const plan = artifact?.body as Plan | undefined;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(() => JSON.stringify(plan, null, 2));

  if (!plan) return null;

  const handleDecide = (approved: boolean, reason?: string) => {
    if (!editing || !approved) {
      onDecide(approved, reason);
      return;
    }
    try {
      const edited = JSON.parse(text) as Plan;
      onDecide(true, reason, edited);
    } catch {
      alert("Plan JSON is invalid - fix it or cancel editing before approving.");
    }
  };

  return (
    <div className="rounded-lg border border-yellow-600/40 bg-yellow-500/5 p-4 space-y-3">
      <div className="text-sm font-medium text-yellow-400">Gate 1 - approve this plan?</div>
      {!editing ? (
        <div className="space-y-2">
          {plan.tasks.map((t) => (
            <div key={t.id} className="rounded border border-[#2a2f37] bg-[#0b0d10] p-2">
              <div className="text-sm text-white font-medium">{t.title}</div>
              <div className="text-xs text-gray-500 font-mono">{t.branch}</div>
              {t.depends_on.length > 0 && (
                <div className="text-xs text-gray-500">depends on: {t.depends_on.join(", ")}</div>
              )}
              <div className="text-xs text-gray-400 mt-1 whitespace-pre-wrap">{t.spec}</div>
            </div>
          ))}
          <button
            onClick={() => setEditing(true)}
            className="text-xs text-blue-400 hover:underline"
          >
            edit plan JSON before approving
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={14}
            className="w-full rounded border border-[#2a2f37] bg-[#0b0d10] px-2 py-1 text-xs font-mono text-white outline-none focus:border-blue-500"
          />
          <button onClick={() => setEditing(false)} className="text-xs text-gray-400 hover:underline">
            cancel edit
          </button>
        </div>
      )}
      <ApprovalActions onDecide={handleDecide} approveLabel={editing ? "Approve edited plan" : "Approve plan"} />
      <div className="text-[11px] text-gray-600">approval {approval.id}</div>
    </div>
  );
}
