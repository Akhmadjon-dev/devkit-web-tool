import { FormEvent, useState } from "react";
import { useAuth } from "../store/auth";

export function TokenGate({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  const setToken = useAuth((s) => s.setToken);
  const [input, setInput] = useState("");

  if (token) return <>{children}</>;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim()) setToken(input.trim());
  };

  return (
    <div className="h-full flex items-center justify-center bg-[#0b0d10]">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 p-6 rounded-lg border border-[#24282f] bg-[#14171c]">
        <h1 className="text-lg font-semibold text-white">DevWorkspace</h1>
        <p className="text-sm text-gray-400">
          Paste the auth token printed by the backend on startup (or open the
          link it prints, which includes it automatically).
        </p>
        <input
          autoFocus
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="token"
          className="w-full rounded border border-[#2a2f37] bg-[#0b0d10] px-3 py-2 text-sm text-white outline-none focus:border-blue-500"
        />
        <button
          type="submit"
          className="w-full rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
        >
          Connect
        </button>
      </form>
    </div>
  );
}
