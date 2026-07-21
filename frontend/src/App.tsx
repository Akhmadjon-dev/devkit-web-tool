import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import { TokenGate } from "./components/TokenGate";
import { SessionTabs } from "./components/SessionTabs";
import { SessionChat } from "./components/SessionChat";
import { ApprovalsQueue } from "./components/ApprovalsQueue";
import { CostMeter } from "./components/CostMeter";
import { WorktreesPanel } from "./components/WorktreesPanel";

function Shell() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const { data: sessions } = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions });
  // Only auto-pick a session on first load. Without this guard, killing the
  // active session (which sets activeId back to null) races the sessions
  // list refetch: this effect would see the still-stale cached list (which
  // still includes the just-closed session) and immediately re-select it,
  // undoing the kill from the UI's perspective.
  const autoSelectedRef = useRef(false);

  useEffect(() => {
    if (!autoSelectedRef.current && !activeId && sessions && sessions.length > 0) {
      autoSelectedRef.current = true;
      setActiveId(sessions[0].id);
    }
  }, [sessions, activeId]);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-[#24282f] px-4 py-2">
        <h1 className="text-sm font-semibold text-white">DevWorkspace</h1>
      </header>
      <SessionTabs activeId={activeId} onSelect={setActiveId} />
      <div className="flex flex-1 min-h-0">
        <main className="flex-1 min-w-0 border-r border-[#24282f]">
          {activeId ? (
            <SessionChat key={activeId} sessionId={activeId} onClosed={() => setActiveId(null)} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              Create a session to get started.
            </div>
          )}
        </main>
        <aside className="w-80 shrink-0 space-y-3 overflow-y-auto p-3">
          <ApprovalsQueue onSelectSession={setActiveId} />
          <CostMeter />
          <WorktreesPanel />
        </aside>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="h-screen bg-[#0b0d10]">
      <TokenGate>
        <Shell />
      </TokenGate>
    </div>
  );
}
