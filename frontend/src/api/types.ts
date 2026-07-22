export type TaskStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "merging"
  | "done"
  | "escalated";

export type SessionStatus = "active" | "idle" | "closed";
export type ApprovalStepKind = "plan" | "task";
export type ApprovalStatus = "pending" | "approved" | "rejected";

export interface Session {
  id: string;
  title: string;
  branch: string;
  worktree_path: string;
  status: SessionStatus;
  tasks?: Task[];
  cost?: number;
}

export interface Task {
  id: string;
  session_id: string;
  title: string;
  spec: string;
  role: "engineer" | "reviewer";
  branch: string | null;
  worktree_path: string | null;
  status: TaskStatus;
  depends_on: string;
  created_at: string;
  artifacts?: Artifact[];
  // present only when status is "escalated" or "rejected"
  outcome_reason?: string;
  failure_class?: "review_rejected" | "test_failed" | "human_rejected" | "escalated";
}

export interface Artifact {
  id: string;
  task_id: string | null;
  session_id: string;
  kind: "plan" | "diff" | "review" | "test_report";
  body: unknown;
  created_at: string;
}

export interface PlanTask {
  id: string;
  title: string;
  spec: string;
  role: "engineer" | "reviewer";
  branch: string;
  depends_on: string[];
}

export interface Plan {
  tasks: PlanTask[];
}

export interface Diff {
  patch: string;
  files_changed: number;
  insertions: number;
  deletions: number;
}

export interface Review {
  verdict: "approve" | "request_changes";
  issues: string[];
  notes: string;
}

export interface TestReport {
  ran: boolean;
  passed: boolean;
  command: string | null;
  output: string;
}

export interface Approval {
  id: string;
  session_id: string;
  task_id: string | null;
  step_kind: ApprovalStepKind;
  payload_ref: string | null;
  status: ApprovalStatus;
  reason: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CostSummary {
  total: number;
  sessions: { id: string; title: string; cost: number }[];
}

export interface WorktreeRow {
  id: string;
  branch: string;
  path: string;
  session_id: string | null;
  status: "active" | "removed";
}

export interface Note {
  id: string;
  kind: string | null;
  text: string;
  created_at: string;
}
