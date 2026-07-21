import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Approval, Diff, Review } from "../api/types";
import { ApprovalActions } from "./ApprovalActions";
import { DiffViewer } from "./DiffViewer";

export function TaskApprovalCard({
  approval,
  onDecide,
}: {
  approval: Approval;
  onDecide: (approved: boolean, reason?: string) => void;
}) {
  const taskId = approval.task_id!;
  const { data: task } = useQuery({ queryKey: ["task", taskId], queryFn: () => api.getTask(taskId) });

  const diff = task?.artifacts?.find((a) => a.kind === "diff")?.body as Diff | undefined;
  const review = task?.artifacts?.find((a) => a.kind === "review")?.body as Review | undefined;

  return (
    <div className="rounded-lg border border-yellow-600/40 bg-yellow-500/5 p-4 space-y-3">
      <div className="text-sm font-medium text-yellow-400">
        Gate 2 - approve this diff? <span className="text-gray-400 font-normal">{task?.title}</span>
      </div>

      {review && (
        <div
          className={`rounded border p-2 text-xs ${
            review.verdict === "approve"
              ? "border-green-700/40 bg-green-500/5 text-green-300"
              : "border-orange-700/40 bg-orange-500/5 text-orange-300"
          }`}
        >
          <div className="font-medium">Reviewer: {review.verdict} (pre-filter, not the final say)</div>
          {review.issues.length > 0 && (
            <ul className="list-disc list-inside mt-1">
              {review.issues.map((iss, i) => (
                <li key={i}>{iss}</li>
              ))}
            </ul>
          )}
          {review.notes && <div className="mt-1 text-gray-400">{review.notes}</div>}
        </div>
      )}

      {diff ? (
        <div>
          <div className="text-xs text-gray-500 mb-1">
            {diff.files_changed} file(s) changed, +{diff.insertions} -{diff.deletions}
          </div>
          <DiffViewer patch={diff.patch} />
        </div>
      ) : (
        <div className="text-xs text-gray-500">loading diff...</div>
      )}

      <ApprovalActions onDecide={onDecide} approveLabel="Approve & merge" rejectLabel="Reject" />
      <div className="text-[11px] text-gray-600">approval {approval.id}</div>
    </div>
  );
}
