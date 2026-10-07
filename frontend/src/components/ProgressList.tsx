import { STEPS } from "../types/investigation";

export default function ProgressList({ progress, failed }: { progress: string; failed: boolean }) {
  const current = STEPS.findIndex((s) => s.key === progress);
  const finished = progress === "done" && !failed;

  return (
    <div className="card w-80 text-left">
      <ol>
        {STEPS.map((step, i) => {
          const done = finished || i < current;
          const active = i === current && !finished && !failed;
          const isLast = i === STEPS.length - 1;
          return (
            <li
              key={step.key}
              className="animate-slide-in relative flex gap-4 pb-5 last:pb-0"
              style={{ animationDelay: `${i * 70}ms` }}
            >
              {/* connector line that fills as steps complete */}
              {!isLast && (
                <span className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-0.5 overflow-hidden rounded bg-white/10">
                  <span
                    className="block w-full bg-gradient-to-b from-emerald-400 to-emerald-500 transition-all duration-700"
                    style={{ height: done ? "100%" : "0%" }}
                  />
                </span>
              )}

              {/* status bubble */}
              <span className="relative flex h-8 w-8 shrink-0 items-center justify-center">
                {active && <span className="absolute inset-0 animate-ping rounded-full bg-indigo-400/40" />}
                <span
                  className={`relative flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors duration-500 ${
                    done
                      ? "border-emerald-400/60 bg-emerald-500/20 text-emerald-300"
                      : active
                        ? "border-indigo-400 bg-indigo-500/25 text-indigo-200 shadow-[0_0_14px_rgba(99,102,241,0.6)]"
                        : "border-white/10 bg-slate-900 text-slate-600"
                  }`}
                >
                  {done ? (
                    <svg key="done" viewBox="0 0 20 20" className="animate-check-pop h-4 w-4" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 10.5l4 4 8-9" />
                    </svg>
                  ) : active ? (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-transparent" />
                  ) : (
                    i + 1
                  )}
                </span>
              </span>

              <div className="min-w-0 flex min-h-8 items-center">
                <p
                  className={`font-medium transition-colors duration-500 ${
                    done
                      ? "text-emerald-300"
                      : active
                        ? "animate-shimmer bg-[linear-gradient(90deg,#a5b4fc,#fff,#67e8f9,#a5b4fc)] bg-[length:200%_100%] bg-clip-text text-transparent"
                        : "text-slate-500"
                  }`}
                >
                  {step.label}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
