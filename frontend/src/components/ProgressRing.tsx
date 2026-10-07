import K8sLogo from "./K8sLogo";
import { STEPS } from "../types/investigation";

interface Props {
  progress: string; // "" = idle
  failed: boolean;
  running: boolean;
  onStart: () => void;
  disabled: boolean;
}

/** Big Kubernetes steering wheel: click to start, spins while investigating. */
export default function ProgressRing({ progress, failed, running, onStart, disabled }: Props) {
  const index = STEPS.findIndex((s) => s.key === progress);
  const done = progress === "done" && !failed;
  const percent = done ? 100 : index < 0 ? 2 : Math.round(((index + 0.5) / STEPS.length) * 100);
  const label = done ? "Root Cause Found" : (STEPS[index]?.label ?? "Starting...");

  return (
    <div className="flex flex-col items-center gap-5">
      <button
        type="button"
        onClick={onStart}
        disabled={disabled || running}
        aria-label="Investigate Cluster"
        className={`relative flex h-72 w-72 items-center justify-center rounded-full transition ${
          running ? "cursor-default" : "hover:scale-105 disabled:opacity-50"
        }`}
      >
        {/* glow */}
        <div
          className={`absolute inset-8 rounded-full blur-3xl transition-colors duration-700 ${
            failed ? "bg-red-500/30" : done ? "bg-emerald-400/30" : "bg-indigo-500/35"
          } ${running ? "animate-pulse" : ""}`}
        />
        {/* decorative orbit rings */}
        <svg viewBox="0 0 100 100" className="absolute inset-0">
          <circle cx="50" cy="50" r="49" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="0.4" />
          <circle cx="50" cy="50" r="46" fill="none" stroke={done ? "#34d399" : "#22d3ee"} strokeOpacity="0.5" strokeWidth="0.5" strokeDasharray="1 3" strokeLinecap="round"
            className={`origin-center ${running ? "animate-spin" : ""}`} style={{ animationDuration: "14s", animationDirection: "reverse" }} />
          <circle cx="50" cy="50" r="43" fill="none" stroke={done ? "#34d399" : "#6366f1"} strokeOpacity="0.6" strokeWidth="0.6" strokeDasharray="14 40" strokeLinecap="round"
            className={`origin-center ${running ? "animate-spin" : ""}`} style={{ animationDuration: "6s" }} />
        </svg>
        <K8sLogo
          className={`relative h-56 w-56 drop-shadow-[0_0_24px_rgba(80,130,255,0.65)] transition-all duration-700 ${
            running ? "animate-spin [animation-duration:4s]" : "animate-float"
          } ${failed ? "grayscale" : ""}`}
        />
      </button>

      <div className="h-12 text-center">
        {running ? (
          <>
            <p className="text-2xl font-bold text-white">{percent}%</p>
            <p className="text-sm text-indigo-300">{label}</p>
          </>
        ) : done ? (
          <p className="font-semibold text-emerald-400">✓ Root Cause Found · click to run again</p>
        ) : (
          <p className="text-lg font-semibold text-white">Investigate Cluster</p>
        )}
      </div>
    </div>
  );
}
