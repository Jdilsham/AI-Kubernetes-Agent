import { useEffect, useRef } from "react";

/** The kubectl commands the AI chose to run, one per line. While running, the newest one is marked and the list follows it. */
export function LiveCommands({ steps, active }: { steps: string[]; active: boolean }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [steps.length]);

  if (steps.length === 0) return null;
  return (
    <div className="mt-2 w-full">
      <p className="mb-1 text-[11px] uppercase tracking-wider text-slate-500">
        {steps.length} command{steps.length === 1 ? "" : "s"} run
      </p>
      <ol className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-black/40 p-2 font-mono text-[11px] leading-snug">
        {steps.map((command, i) => {
          const latest = active && i === steps.length - 1;
          return (
            <li key={i} ref={i === steps.length - 1 ? end : undefined} title={command} className="flex gap-2">
              <span className={latest ? "text-indigo-300" : "text-emerald-400"}>{latest ? "▸" : "✓"}</span>
              <span className={`min-w-0 break-all ${latest ? "text-slate-100" : "text-slate-400"}`}>{command}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Saved with the finished investigation: how the AI got to its answer. */
export default function CommandTrail({ steps }: { steps: string[] }) {
  if (steps.length === 0) return null;
  return (
    <details className="card group text-left">
      <summary className="cursor-pointer select-none text-sm font-semibold text-slate-200">
        How the AI investigated <span className="font-normal text-slate-500">· {steps.length} kubectl command{steps.length === 1 ? "" : "s"}</span>
      </summary>
      <ol className="mt-3 space-y-1.5 font-mono text-xs">
        {steps.map((command, i) => (
          <li key={i} className="flex gap-3">
            <span className="w-6 shrink-0 text-right text-slate-600">{i + 1}</span>
            <span className="min-w-0 break-all text-emerald-300">{command}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
