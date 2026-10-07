import type { Cluster } from "../types/investigation";

interface Props {
  clusters: Cluster[];
  selected: string | null;
  disabled: boolean;
  onPick: (name: string) => void;
  namespaces: string[];
  namespace: string | null; // null = all namespaces
  onNamespace: (ns: string | null) => void;
  namespaceLocked?: boolean; // namespace-scoped install
}

/** Dropdown of the clusters (contexts) in the local kubeconfig. */
export default function ClusterPicker({ clusters, selected, disabled, onPick, namespaces, namespace, onNamespace, namespaceLocked = false }: Props) {
  const active = clusters.find((c) => c.name === selected);

  return (
    <div className="grid w-full max-w-2xl gap-4 text-left sm:grid-cols-[3fr_2fr]">
      <div>
      <label htmlFor="cluster" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400">
        Select cluster
      </label>
      <div className="relative">
        <select
          id="cluster"
          value={selected ?? ""}
          disabled={disabled}
          onChange={(e) => onPick(e.target.value)}
          className="input cursor-pointer appearance-none pr-10 font-medium disabled:cursor-not-allowed disabled:opacity-50"
        >
          {clusters.map((c) => (
            <option key={c.name} value={c.name} className="bg-slate-900">
              {c.name}
              {c.current ? " (current)" : ""}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-slate-400">▾</span>
      </div>
      {active && (
        <p className="mt-1.5 text-xs text-slate-500">
          cluster: {active.cluster} · user: {active.user}
        </p>
      )}
      </div>
      <div>
        <label htmlFor="namespace" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400">
          Namespace
        </label>
        <div className="relative">
          <select
            id="namespace"
            value={namespace ?? ""}
            disabled={disabled || namespaceLocked}
            onChange={(e) => onNamespace(e.target.value || null)}
            className="input cursor-pointer appearance-none pr-10 font-medium disabled:cursor-not-allowed disabled:opacity-50"
          >
            {!namespaceLocked && <option value="" className="bg-slate-900">All namespaces</option>}
            {namespaces.map((ns) => (
              <option key={ns} value={ns} className="bg-slate-900">
                {ns}
              </option>
            ))}
          </select>
          <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-slate-400">▾</span>
        </div>
        <p className="mt-1.5 text-xs text-slate-500">Smaller scope = faster, more focused results</p>
      </div>
    </div>
  );
}
