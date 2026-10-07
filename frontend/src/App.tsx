import AuthForm from "./components/AuthForm";
import HistoryTable from "./components/HistoryTable";
import InvestigateButton from "./components/InvestigateButton";
import StatusBadge from "./components/StatusBadge";
import { useAuth } from "./hooks/useAuth";

export default function App() {
  const { authenticated, mode, loading, signOut } = useAuth();

  return (
    <div className="flex min-h-screen w-full flex-col px-6 py-6 lg:px-12">
      <header className="animate-fade-up flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-500 text-lg">
            ☸
          </span>
          <h1 className="text-lg font-semibold text-white">AI Kubernetes Agent</h1>
        </div>
        {authenticated && mode === "password" && (
          <div className="flex items-center gap-3 text-sm">
            <button
              onClick={signOut}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-slate-300 transition hover:bg-white/5"
            >
              Sign out
            </button>
          </div>
        )}
      </header>

      <main className="flex w-full flex-1 flex-col items-center gap-10 py-10 text-center">
        <div className="animate-fade-up space-y-3" style={{ animationDelay: "50ms" }}>
          <h2 className="bg-gradient-to-r from-white to-slate-400 bg-clip-text text-4xl font-bold tracking-tight text-transparent sm:text-5xl">
            Troubleshoot Kubernetes with AI
          </h2>
          <p className="text-slate-400">Collect cluster evidence, find the root cause, get the fix.</p>
        </div>

        {loading ? (
          <p className="text-slate-500">Loading...</p>
        ) : !authenticated ? (
          <AuthForm />
        ) : (
          <div className="flex w-full flex-col items-center gap-10">
            <div className="animate-fade-up w-full" style={{ animationDelay: "100ms" }}>
              <InvestigateButton />
            </div>
            <div className="animate-fade-up w-full" style={{ animationDelay: "300ms" }}>
              <HistoryTable />
            </div>
          </div>
        )}
      </main>

      <footer className="flex justify-center pb-2">
        <StatusBadge />
      </footer>
    </div>
  );
}
