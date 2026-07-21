function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-gray-400";
  if (line.startsWith("@@")) return "text-purple-400 bg-purple-500/10";
  if (line.startsWith("+")) return "text-green-400 bg-green-500/10";
  if (line.startsWith("-")) return "text-red-400 bg-red-500/10";
  return "text-gray-300";
}

export function DiffViewer({ patch }: { patch: string }) {
  if (!patch.trim()) {
    return <div className="text-sm text-gray-500 italic p-3">No changes.</div>;
  }
  const lines = patch.split("\n");
  return (
    <pre className="text-xs font-mono overflow-x-auto rounded border border-[#24282f] bg-[#0b0d10] p-3 leading-5">
      {lines.map((line, i) => (
        <div key={i} className={lineClass(line)}>
          {line.length ? line : " "}
        </div>
      ))}
    </pre>
  );
}
