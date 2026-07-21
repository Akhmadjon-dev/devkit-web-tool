import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function SessionTabs({
  activeId,
  onSelect,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const { data: sessions } = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions });
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const submittingRef = useRef(false);

  const createSession = async () => {
    if (!title.trim() || submittingRef.current) return;
    submittingRef.current = true;
    setCreating(false);
    try {
      const session = await api.createSession(title.trim());
      setTitle("");
      await qc.invalidateQueries({ queryKey: ["sessions"] });
      onSelect(session.id);
    } finally {
      submittingRef.current = false;
    }
  };

  const active = (sessions ?? []).filter((s) => s.status !== "closed");

  return (
    <div className="flex items-center gap-2 border-b border-[#24282f] bg-[#0f1115] px-3 py-2 overflow-x-auto">
      {active.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={`shrink-0 rounded px-3 py-1.5 text-xs font-medium ${
            s.id === activeId
              ? "bg-blue-600 text-white"
              : "bg-[#1a1d23] text-gray-300 hover:bg-[#20242b]"
          }`}
        >
          {s.title}
        </button>
      ))}
      {creating ? (
        <div className="flex items-center gap-1 shrink-0">
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") createSession();
              if (e.key === "Escape") setCreating(false);
            }}
            placeholder="session title"
            className="rounded border border-[#2a2f37] bg-[#0b0d10] px-2 py-1 text-xs text-white outline-none focus:border-blue-500"
          />
          <button onClick={createSession} className="text-xs text-blue-400 hover:underline">
            create
          </button>
        </div>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="shrink-0 rounded px-3 py-1.5 text-xs font-medium text-gray-400 hover:bg-[#1a1d23]"
        >
          + new
        </button>
      )}
    </div>
  );
}
