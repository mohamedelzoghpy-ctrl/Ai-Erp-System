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
  /** الصلاحيات الفعلية (من /auth/me) — "*" للمدير/الأدمن */
  permissions: string[];
  /** فحص صلاحية (any-of): can("sales.pos.use") */
  can: (...codes: string[]) => boolean;
  /** تحديث الصلاحيات بعد تعديلها من شاشة الإدارة */
  refreshPermissions: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(!!getToken());

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setPermissions([]);
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
      .then((me) => {
        setUser(me);
        setPermissions(me.permissions ?? []);
      })
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password);
    setToken(access_token);
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
      setPermissions(me.permissions ?? []);
      sessionStorage.setItem("erp_welcome", "1"); // رسالة ترحيب للموظف بعد الدخول — Layout يعرضها مرة واحدة
    } catch (e) {
      setToken(null);
      throw e;
    }
  }, []);

  const refreshPermissions = useCallback(async () => {
    const me = await api.get<User>("/auth/me");
    setUser(me);
    setPermissions(me.permissions ?? []);
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
    const can = (...codes: string[]) => {
      if (permissions.includes("*")) return true;
      return codes.some((c) => permissions.includes(c));
    };
    return {
      user,
      loading,
      login,
      setupAdmin,
      logout,
      isManager: role === "admin" || role === "manager",
      isAdmin: role === "admin",
      isPlatformAdmin: user?.is_platform_admin ?? false,
      permissions,
      can,
      refreshPermissions,
    };
  }, [user, loading, login, setupAdmin, logout, permissions, refreshPermissions]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
