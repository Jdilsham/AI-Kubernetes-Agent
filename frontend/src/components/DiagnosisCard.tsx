import type { Diagnosis } from "../types/investigation";

/** Split "1. do x 2. do y" (one paragraph from the LLM) into separate steps. */
function parseSteps(raw: string): string[] {
  // The model sometimes writes a literal backslash-n instead of a real line break.
  const text = raw.replace(/\\r\\n|\\n/g, "\n");
  const parts = text.split(/(?:^|\s)\d+[.)]\s+/).map((p) => p.trim()).filter(Boolean);
  return parts.length >= 2 ? parts : [];
}

function Steps({ text }: { text: string }) {
  const steps = parseSteps(text);
  if (!steps.length) return <p className="whitespace-pre-line">{text.replace(/\\r\\n|\\n/g, "\n")}</p>;
  return (
    <ol className="space-y-2">
      {steps.map((step, i) => (
        <li key={i} className="flex gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-500/20 text-xs font-semibold text-indigo-300">
            {i + 1}
          </span>
          <span>{step}</span>
        </li>
      ))}
    </ol>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-indigo-300">{label}</p>
      <div className="mt-1 text-slate-200">{children}</div>
    </div>
  );
}

type IssueFields = Pick<Diagnosis, "root_cause" | "explanation" | "fix" | "kubectl_commands" | "prevention" | "confidence" | "confidence_reasoning">;

function IssueBody({ issue }: { issue: IssueFields }) {
  return (
    <div className="space-y-5">
      <Field label="Root Cause">{issue.root_cause}</Field>
      <Field label="Explanation">{issue.explanation}</Field>
      <Field label="Suggested Fix">
        <Steps text={issue.fix} />
      </Field>
      {issue.kubectl_commands.length > 0 && (
        <Field label="kubectl Commands">
          <pre className="overflow-x-auto rounded-xl border border-white/10 bg-black/50 p-3 text-sm text-emerald-300">
            {issue.kubectl_commands.join("\n")}
          </pre>
        </Field>
      )}
      {issue.prevention && (
        <Field label="Prevention">
          <Steps text={issue.prevention} />
        </Field>
      )}
      <Field label="Confidence">
        <div className="flex items-center gap-3">
          <div className="h-2 w-40 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" style={{ width: `${issue.confidence}%` }} />
          </div>
          <span className="font-semibold text-white">{issue.confidence}%</span>
        </div>
        {issue.confidence_reasoning?.length > 0 && (
          <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-slate-400">
            {issue.confidence_reasoning.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </Field>
    </div>
  );
}

const SEVERITY: Record<string, string> = {
  critical: "bg-red-500/15 text-red-300 border-red-500/30",
  warning: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  info: "bg-sky-500/15 text-sky-300 border-sky-500/30",
};

export default function DiagnosisCard({ diagnosis }: { diagnosis: Diagnosis }) {
  if (diagnosis.healthy) {
    return (
      <div className="card animate-pop-in w-full max-w-xl space-y-1 border-emerald-500/30 text-center">
        <p className="text-3xl text-emerald-400">✓</p>
        <p className="text-lg font-semibold text-white">No critical Kubernetes issues detected.</p>
        <p className="text-slate-400">Cluster appears healthy.</p>
      </div>
    );
  }

  const issues = diagnosis.issues ?? [];
  // Older investigations (and single-issue results) have one root cause.
  if (issues.length <= 1) {
    return (
      <div className="card w-full text-left lg:p-8">
        <IssueBody issue={issues[0] ?? diagnosis} />
      </div>
    );
  }

  return (
    <div className="w-full space-y-5 text-left">
      <div className="card flex flex-wrap items-center gap-3 lg:px-8">
        <span className="rounded-full bg-indigo-500/20 px-3 py-1 text-sm font-semibold text-indigo-200">
          {issues.length} issues found
        </span>
        {diagnosis.summary && <p className="text-slate-300">{diagnosis.summary}</p>}
      </div>
      {issues.map((issue, i) => (
        <article key={i} className="card animate-fade-up lg:p-8" style={{ animationDelay: `${i * 80}ms` }}>
          <header className="mb-5 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-slate-500">Issue {i + 1}</span>
              <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase ${SEVERITY[issue.severity] ?? SEVERITY.warning}`}>
                {issue.severity}
              </span>
            </div>
            {issue.title && <h3 className="text-lg font-semibold text-white">{issue.title}</h3>}
            {issue.affected.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {issue.affected.slice(0, 8).map((a) => (
                  <span key={a} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-xs text-slate-300">
                    {a}
                  </span>
                ))}
                {issue.affected.length > 8 && (
                  <span className="px-1 text-xs text-slate-500">+{issue.affected.length - 8} more</span>
                )}
              </div>
            )}
          </header>
          <IssueBody issue={issue} />
        </article>
      ))}
    </div>
  );
}
