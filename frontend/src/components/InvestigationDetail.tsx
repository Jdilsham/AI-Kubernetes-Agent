import { useEffect } from "react";
import { createPortal } from "react-dom";

import type { InvestigationRow } from "../types/investigation";
import DiagnosisCard from "./DiagnosisCard";

interface Props {
  row: InvestigationRow | null;
  loading: boolean;
  onClose: () => void;
}

export default function InvestigationDetail({ row, loading, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Lock the page scrollbar while the panel is open.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  // Portal to <body>: a transformed ancestor would otherwise break position: fixed.
  return createPortal(
    <div className="fixed inset-0 z-50 animate-pop-in overflow-y-auto bg-slate-950">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/10 bg-slate-950/90 px-6 py-4 backdrop-blur lg:px-12">
        <h3 className="text-xl font-semibold text-white">Investigation details</h3>
        <button
          onClick={onClose}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 transition hover:bg-white/5"
        >
          ✕ Close
        </button>
      </div>

      <div className="mx-auto w-full max-w-5xl space-y-6 px-6 py-8 text-left lg:px-12">
        {loading ? (
          <p className="text-slate-400">Loading...</p>
        ) : !row ? (
          <p className="text-slate-400">Investigation not found.</p>
        ) : (
          <>
            <dl className="card grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
              <Meta label="Time" value={new Date(row.created_at).toLocaleString()} />
              <Meta label="Status" value={row.status} />
              <Meta label="Cluster" value={`${row.cluster ?? "—"} (${row.scope ?? "all namespaces"})`} />
              <Meta label="Namespace" value={row.namespace ?? "—"} />
              <Meta label="Confidence" value={row.confidence != null ? `${row.confidence}%` : "—"} />
            </dl>
            {row.error && (
              <p className="whitespace-pre-line rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                {row.error}
              </p>
            )}
            {row.diagnosis ? (
              <DiagnosisCard diagnosis={row.diagnosis} />
            ) : (
              !row.error && <p className="text-slate-400">No diagnosis was recorded for this investigation.</p>
            )}
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-slate-200">{value}</dd>
    </div>
  );
}
