import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function NotesPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["notes"], queryFn: api.listNotes });
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);

  const notes = data ?? [];

  const addNote = async () => {
    if (!text.trim()) return;
    setAdding(true);
    try {
      await api.createNote(text.trim());
      setText("");
      qc.invalidateQueries({ queryKey: ["notes"] });
    } finally {
      setAdding(false);
    }
  };

  const removeNote = async (id: string) => {
    await api.deleteNote(id);
    qc.invalidateQueries({ queryKey: ["notes"] });
  };

  return (
    <div className="rounded-lg border border-[#24282f] bg-[#14171c] p-3">
      <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
        Notes {notes.length > 0 && <span>({notes.length})</span>}
      </div>
      <p className="text-[11px] text-gray-600 mb-2">
        Conventions and decisions retrieved into Planner/Engineer context.
      </p>
      <div className="flex gap-1 mb-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addNote();
          }}
          placeholder="e.g. always use snake_case for Python function names"
          rows={2}
          className="flex-1 rounded border border-[#2a2f37] bg-[#0b0d10] px-2 py-1 text-xs text-white outline-none focus:border-blue-500"
        />
      </div>
      <button
        onClick={addNote}
        disabled={adding || !text.trim()}
        className="w-full rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50 mb-2"
      >
        Add note
      </button>
      {notes.length === 0 && <div className="text-xs text-gray-600">None yet.</div>}
      <div className="space-y-1.5">
        {notes.map((n) => (
          <div key={n.id} className="group flex items-start justify-between gap-1 rounded border border-[#2a2f37] p-1.5">
            <div className="text-xs text-gray-300">{n.text}</div>
            <button
              onClick={() => removeNote(n.id)}
              className="shrink-0 text-[11px] text-gray-600 opacity-0 group-hover:opacity-100 hover:text-red-400"
            >
              remove
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
