import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { checkSession, getAuthConfig, setToken } from "../services/api";

interface AuthState {
  authenticated: boolean;
  mode: "password" | "none" | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState>({
  authenticated: false,
  mode: null,
  loading: true,
  refresh: async () => {},
  signOut: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [mode, setMode] = useState<AuthState["mode"]>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const config = await getAuthConfig();
      setMode(config.mode);
      setAuthenticated(config.mode === "none" || (await checkSession()));
    } catch {
      setAuthenticated(false);
    }
    setLoading(false);
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setAuthenticated(false);
  }, []);

  useEffect(() => {
    void refresh();
    // any 401 from the API logs the user out
    window.addEventListener("k8s-agent:logout", signOut);
    return () => window.removeEventListener("k8s-agent:logout", signOut);
  }, [refresh, signOut]);

  return <AuthContext.Provider value={{ authenticated, mode, loading, refresh, signOut }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
