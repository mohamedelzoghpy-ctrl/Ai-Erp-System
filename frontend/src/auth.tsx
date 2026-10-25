import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  setupAdmin: (username: string, password: string, fullName: string) => Promise<void>;
  logout: () => void;
  /** manager or admin */
  isManager: boolean;
  isAdmin: boolean;
  isPlatformAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(!!getToken());

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Restore the session on first load.
  useEffect(() => {
    if (!getToken()) return;
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password);
    setToken(access_token);
    try {
      setUser(await api.get<User>("/auth/me"));
    } catch (e) {
      setToken(null);
      throw e;
    }
  }, []);

  const setupAdmin = useCallback(
    async (username: string, password: string, fullName: string) => {
      await api.post("/auth/setup", { username, password, full_name: fullName || null });
      await login(username, password);
    },
    [login],
  );

  const value = useMemo<AuthState>(() => {
    const role: Role | undefined = user?.role;
    return {
      user,
      loading,
      login,
      setupAdmin,
      logout,
      isManager: role === "admin" || role === "manager",
      isAdmin: role === "admin",
      isPlatformAdmin: user?.is_platform_admin ?? false,
    };
  }, [user, loading, login, setupAdmin, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
