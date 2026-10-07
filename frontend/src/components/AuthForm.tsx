import { useState, type FormEvent } from "react";

import { useAuth } from "../hooks/useAuth";
import { login, setToken } from "../services/api";
import K8sLogo from "./K8sLogo";

export default function AuthForm() {
  const { refresh } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      setToken(await login(password));
      await refresh();
    } catch {
      setError("Wrong password. Use the admin password set at install time.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="animate-pop-in w-full max-w-md">
      <div className="rounded-3xl bg-gradient-to-br from-indigo-500/60 via-white/10 to-cyan-400/60 p-px shadow-2xl shadow-indigo-500/10">
        <form onSubmit={submit} className="space-y-6 rounded-3xl bg-slate-900/95 p-8 text-left backdrop-blur">
          <div className="flex flex-col items-center gap-3 text-center">
            <K8sLogo className="animate-float h-16 w-16 drop-shadow-[0_0_14px_rgba(80,130,255,0.6)]" />
            <div className="animate-slide-in">
              <h2 className="text-2xl font-bold text-white">Welcome back</h2>
              <p className="mt-1 text-sm text-slate-400">Enter the admin password to investigate your cluster.</p>
            </div>
          </div>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-400">Admin password</span>
            <input
              className="input"
              type="password"
              autoFocus
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p className="animate-slide-in rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>
          )}
          <button disabled={busy} className="btn-primary w-full py-3">
            {busy ? "Signing in..." : "Sign in"}
          </button>
          <p className="text-center text-xs text-slate-500">
            Forgot it? Read it with <code className="text-slate-400">kubectl get secret</code> (see the install notes).
          </p>
        </form>
      </div>
    </div>
  );
}
