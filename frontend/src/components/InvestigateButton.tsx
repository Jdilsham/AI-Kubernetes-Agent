import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  cancelInvestigation,
  friendlyError,
  getClusters,
  getNamespaces,
  listInvestigations,
  startInvestigation,
  watchInvestigation,
} from "../services/api";
import type { Diagnosis, InvestigationRow } from "../types/investigation";
import ClusterPicker from "./ClusterPicker";
import DiagnosisCard from "./DiagnosisCard";
import ProgressList from "./ProgressList";
import ProgressRing from "./ProgressRing";

export default function InvestigateButton() {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [namespace, setNamespace] = useState<string | null>(null);
  const currentId = useRef<string | null>(null);
  const stopWatching = useRef<(() => void) | null>(null);

  const clusterQuery = useQuery({ queryKey: ["clusters"], queryFn: getClusters, retry: false });
  const clusters = clusterQuery.data?.clusters ?? [];
  const cluster = selected ?? clusterQuery.data?.current ?? null;
  const namespaceQuery = useQuery({
    queryKey: ["namespaces", cluster],
    enabled: !!cluster,
    queryFn: () => getNamespaces(cluster),
    retry: false,
  });
  // namespace-scoped install: the only allowed namespace is pre-selected
  const locked = namespaceQuery.data?.locked ? namespaceQuery.data.namespaces[0] : null;

  // Apply a row pushed by the server to the UI.
  function applyRow(row: InvestigationRow) {
    if (row.id !== currentId.current) return;
    if (row.progress) setProgress(row.progress);
    if (row.diagnosis) setDiagnosis(row.diagnosis);
    if (row.status !== "running") {
      if (row.status === "cancelled") setProgress("");
      else if (row.status === "failed" || row.status === "partial") setError(row.error ?? "The investigation did not finish.");
      setRunning(false);
      void queryClient.invalidateQueries({ queryKey: ["history"] });
    }
  }

  function follow(id: string) {
    stopWatching.current?.();
    currentId.current = id;
    stopWatching.current = watchInvestigation(id, applyRow, () => {
      setError("Lost the live connection. The investigation keeps running; refresh to see the result.");
      setRunning(false);
    });
  }

  // After a page refresh: re-attach to an investigation that is still running.
  useEffect(() => {
    void listInvestigations(0, 1, "running").then(({ rows }) => {
      const row = rows[0];
      if (!row || currentId.current) return;
      setRunning(true);
      setProgress(row.progress ?? "starting");
      if (row.cluster) setSelected(row.cluster);
      if (row.scope) setNamespace(row.scope);
      follow(row.id);
    }).catch(() => {});
    return () => stopWatching.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    setRunning(true);
    setError("");
    setDiagnosis(null);
    setProgress("starting");
    try {
      const row = await startInvestigation(cluster, locked ?? namespace);
      follow(row.id);
      void queryClient.invalidateQueries({ queryKey: ["history"] });
    } catch (err) {
      setError(friendlyError(err));
      setRunning(false);
    }
  }

  async function cancel() {
    if (currentId.current) await cancelInvestigation(currentId.current).catch(() => {});
  }

  return (
    <div className="flex w-full flex-col items-center gap-8">
      {clusters.length > 0 && (
        <ClusterPicker
          clusters={clusters}
          selected={cluster}
          disabled={running}
          onPick={(name) => {
            setSelected(name);
            setNamespace(null); // namespaces differ per cluster
          }}
          namespaces={namespaceQuery.data?.namespaces ?? []}
          namespace={locked ?? namespace}
          onNamespace={setNamespace}
          namespaceLocked={!!locked}
        />
      )}
      <div className="flex flex-col items-center gap-8 md:flex-row md:gap-14">
        <div className="flex flex-col items-center gap-4">
          <ProgressRing progress={progress} failed={!!error} running={running} onStart={start} disabled={!cluster} />
          {running && <p className="text-sm text-indigo-300">Investigating Kubernetes Cluster...</p>}
          {running && (
            <button
              type="button"
              onClick={cancel}
              className="animate-pop-in rounded-xl border border-red-500/40 bg-red-500/10 px-6 py-2 text-sm font-semibold text-red-300 transition hover:bg-red-500/20"
            >
              ✕ Cancel investigation
            </button>
          )}
        </div>
        {progress && <ProgressList progress={progress} failed={!!error} />}
      </div>
      {error && (
        <p className="animate-slide-in max-w-xl whitespace-pre-line rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-3 text-left text-sm text-red-300">
          {error}
        </p>
      )}
      {clusterQuery.data?.error && (
        <p className="max-w-xl whitespace-pre-line rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-3 text-left text-sm text-amber-200">
          {clusterQuery.data.error}
        </p>
      )}
      {diagnosis && <DiagnosisCard diagnosis={diagnosis} />}
    </div>
  );
}
