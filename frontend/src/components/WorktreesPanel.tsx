import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function WorktreesPanel() {
  const { data } = useQuery({ queryKey: ["worktrees"], queryFn: api.worktrees, refetchInterval: 10_000 });
  const active = (data ?? []).filter((w) => w.status === "active");

  return (
    <div className="rounded-lg border border-[#24282f] bg-[#14171c] p-3">
      <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
        Worktrees {active.length > 0 && <span>({active.length})</span>}
      </div>
      {active.length === 0 && <div className="text-xs text-gray-600">None active.</div>}
      <div className="space-y-1.5">
        {active.map((w) => (
          <div key={w.id} className="text-xs">
            <div className="text-gray-300 font-mono truncate">{w.branch}</div>
            <div className="text-gray-600 truncate">{w.path}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
