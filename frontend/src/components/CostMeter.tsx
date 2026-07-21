import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTopic } from "../api/ws";

export function CostMeter() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["cost"], queryFn: api.cost, refetchInterval: 30_000 });

  useTopic("/ws/cost", () => {
    qc.invalidateQueries({ queryKey: ["cost"] });
  });

  return (
    <div className="rounded-lg border border-[#24282f] bg-[#14171c] p-3">
      <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Cost</div>
      <div className="text-xl font-semibold text-white">
        ${(data?.total ?? 0).toFixed(4)}
      </div>
      {data && data.sessions.length > 0 && (
        <div className="mt-2 space-y-1">
          {data.sessions
            .filter((s) => s.cost > 0)
            .map((s) => (
              <div key={s.id} className="flex justify-between text-xs text-gray-400">
                <span className="truncate">{s.title}</span>
                <span>${s.cost.toFixed(4)}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
