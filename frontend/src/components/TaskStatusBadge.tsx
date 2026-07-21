import type { TaskStatus } from "../api/types";

const COLORS: Record<TaskStatus, string> = {
  queued: "bg-gray-600/30 text-gray-300",
  running: "bg-blue-600/30 text-blue-300",
  awaiting_approval: "bg-yellow-600/30 text-yellow-300",
  approved: "bg-teal-600/30 text-teal-300",
  rejected: "bg-red-600/30 text-red-300",
  merging: "bg-purple-600/30 text-purple-300",
  done: "bg-green-600/30 text-green-300",
  escalated: "bg-orange-600/30 text-orange-300",
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${COLORS[status]}`}>
      {status.replace("_", " ")}
    </span>
  );
}
