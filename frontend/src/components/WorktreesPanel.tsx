import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTopic } from "../api/ws";

export function WorktreesPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["worktrees"], queryFn: api.worktrees, refetchInterval: 15_000 });
  const [cleaning, setCleaning] = useState(false);
  const active = (data ?? []).filter((w) => w.status === "active");

  useTopic("/ws/worktrees", () => {
    qc.invalidateQueries({ queryKey: ["worktrees"] });
  });

  const cleanup = async () => {
    setCleaning(true);
    try {
      const { removed } = await api.cleanupWorktrees();
      qc.invalidateQueries({ queryKey: ["worktrees"] });
      if (removed.length === 0) alert("No orphaned worktrees found.");
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div className="rounded-lg border border-[#24282f] bg-[#14171c] p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase tracking-wide text-gray-500">
          Worktrees {active.length > 0 && <span>({active.length})</span>}
        </div>
        <button
          onClick={cleanup}
          disabled={cleaning}
          className="text-[11px] text-gray-500 hover:text-gray-300 disabled:opacity-50"
        >
          {cleaning ? "cleaning..." : "clean up orphaned"}
        </button>
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
