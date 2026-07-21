import { useState } from "react";

export function ApprovalActions({
  onDecide,
  approveLabel = "Approve",
  rejectLabel = "Reject",
  busy = false,
}: {
  onDecide: (approved: boolean, reason?: string) => void;
  approveLabel?: string;
  rejectLabel?: string;
  busy?: boolean;
}) {
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);

  return (
    <div className="space-y-2">
      {showReason && (
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="reason (optional)"
          rows={2}
          className="w-full rounded border border-[#2a2f37] bg-[#0b0d10] px-2 py-1 text-xs text-white outline-none focus:border-blue-500"
        />
      )}
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={() => onDecide(true, reason || undefined)}
          className="rounded bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-500 disabled:opacity-50"
        >
          {approveLabel}
        </button>
        <button
          disabled={busy}
          onClick={() => {
            if (!showReason) {
              setShowReason(true);
              return;
            }
            onDecide(false, reason || undefined);
          }}
          className="rounded bg-red-600/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
        >
          {rejectLabel}
        </button>
      </div>
    </div>
  );
}
