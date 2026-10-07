import { useHealth } from "../hooks/useHealth";

export default function StatusBadge() {
  const { data, isLoading } = useHealth();

  const label = isLoading ? "Checking..." : data?.status === "healthy" ? "Ready" : "Unavailable";
  const color = label === "Ready" ? "bg-emerald-400" : label === "Checking..." ? "bg-amber-400" : "bg-red-500";

  return (
    <p className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/60 px-3 py-1 text-xs text-slate-400">
      <span className={`h-2 w-2 rounded-full ${color} ${label === "Ready" ? "animate-pulse" : ""}`} />
      System Status: {label}
    </p>
  );
}
