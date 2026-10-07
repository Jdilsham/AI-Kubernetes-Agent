import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getInvestigation, listInvestigations } from "../services/api";
import type { InvestigationRow } from "../types/investigation";
import InvestigationDetail from "./InvestigationDetail";

const PAGE_SIZE = 20;

export function useHistory() {
  return useInfiniteQuery({
    queryKey: ["history"],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const { rows, total } = await listInvestigations(pageParam, PAGE_SIZE);
      return { rows, total, next: pageParam + PAGE_SIZE };
    },
    getNextPageParam: (last) => (last.next < last.total ? last.next : undefined),
  });
}

/** Full row (including the diagnosis JSON) is fetched only when a row is opened. */
function useInvestigation(id: string | null) {
  return useQuery({
    queryKey: ["investigation", id],
    enabled: !!id,
    queryFn: () => getInvestigation(id!),
  });
}

const STALE_MS = 10 * 60 * 1000;

/** A run still marked "running" after 10 minutes was interrupted (e.g. server restart). */
const effectiveStatus = (r: InvestigationRow) =>
  r.status === "running" && Date.now() - new Date(r.created_at).getTime() > STALE_MS ? "interrupted" : r.status;

const badge = (status: string) =>
  status === "success"
    ? "bg-emerald-500/15 text-emerald-300"
    : status === "running"
      ? "bg-indigo-500/15 text-indigo-300"
      : status === "cancelled"
        ? "bg-slate-500/20 text-slate-300"
        : "bg-amber-500/15 text-amber-300";

export default function HistoryTable() {
  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useHistory();
  const [openId, setOpenId] = useState<string | null>(null);
  const detail = useInvestigation(openId);

  const rows = data?.pages.flatMap((p) => p.rows) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  return (
    <section className="w-full text-left">
      <h2 className="mb-2 flex items-baseline gap-2 text-lg font-semibold text-white">
        Previous Investigations
        {total > 0 && <span className="text-sm font-normal text-slate-500">{total} total</span>}
      </h2>
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : !rows.length ? (
        <p className="text-sm text-slate-500">No investigations yet.</p>
      ) : (
        <>
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="bg-white/5 text-left text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="p-3">Time</th>
                  <th className="p-3">Root Cause</th>
                  <th className="p-3">Cluster</th>
                  <th className="p-3">Namespace</th>
                  <th className="p-3">Confidence</th>
                  <th className="p-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setOpenId(r.id)}
                    className="cursor-pointer border-t border-white/5 transition hover:bg-white/5"
                  >
                    <td className="whitespace-nowrap p-3">{new Date(r.created_at).toLocaleString()}</td>
                    <td className="max-w-md truncate p-3">{r.root_cause ?? "—"}</td>
                    <td className="max-w-[10rem] truncate p-3">
                      {r.cluster ?? "—"}
                      <span className="block text-xs text-slate-500">{r.scope ?? "all namespaces"}</span>
                    </td>
                    <td className="p-3">{r.namespace ?? "—"}</td>
                    <td className="p-3">{r.confidence != null ? `${r.confidence}%` : "—"}</td>
                    <td className="p-3">
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${badge(effectiveStatus(r))}`}>
                        {effectiveStatus(r) === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-300" />}
                        {effectiveStatus(r)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="mx-auto mt-4 block rounded-xl border border-white/10 px-5 py-2 text-sm text-slate-300 transition hover:bg-white/5 disabled:opacity-50"
            >
              {isFetchingNextPage ? "Loading..." : `Load more (${rows.length} of ${total})`}
            </button>
          )}
        </>
      )}

      {openId && (
        <InvestigationDetail row={detail.data ?? null} loading={detail.isLoading} onClose={() => setOpenId(null)} />
      )}
    </section>
  );
}
