export interface Issue {
  title: string;
  severity: "critical" | "warning" | "info";
  affected: string[];
  root_cause: string;
  explanation: string;
  fix: string;
  kubectl_commands: string[];
  prevention: string;
  confidence: number;
  confidence_reasoning: string[];
}

export interface Diagnosis {
  summary?: string;
  issues?: Issue[];
  root_cause: string;
  explanation: string;
  fix: string;
  kubectl_commands: string[];
  kubectl_command: string;
  prevention: string;
  confidence: number;
  confidence_reasoning: string[];
  healthy?: boolean;
}

export interface Cluster {
  name: string;
  cluster: string;
  user: string;
  current: boolean;
}

export interface InvestigationRow {
  id: string;
  status: "running" | "success" | "partial" | "failed" | "cancelled";
  progress: string;
  cluster: string | null;
  scope: string | null;
  namespace: string | null;
  root_cause: string | null;
  confidence: number | null;
  diagnosis: Diagnosis | null;
  error: string | null;
  created_at: string;
}

/** Steps in the order the backend reports them. */
export const STEPS = [
  { key: "pods", label: "Checking Pods" },
  { key: "logs", label: "Reading Logs" },
  { key: "events", label: "Analyzing Events" },
  { key: "deployments", label: "Inspecting Deployments" },
  { key: "network", label: "Checking Networking" },
  { key: "resources", label: "Inspecting Resources" },
  { key: "ai", label: "AI Reasoning" },
  { key: "done", label: "Root Cause Found" },
] as const;
