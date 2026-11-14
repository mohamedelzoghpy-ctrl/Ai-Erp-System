/** طبقة الـAPI: ترويسة التوكن تلقائياً + تجديد شفاف عند 401 (refresh token من P0). */
import * as FileSystem from "expo-file-system";
import * as SecureStore from "expo-secure-store";
import { API_BASE } from "./config";

let accessToken: string | null = null;
let refreshToken: string | null = null;
let fullName: string | null = null;

export async function saveTokens(access: string, refresh: string) {
  accessToken = access;
  refreshToken = refresh;
  await SecureStore.setItemAsync("mozad_access", access);
  await SecureStore.setItemAsync("mozad_refresh", refresh);
}

export async function saveFullName(name: string | null) {
  fullName = name;
  await SecureStore.setItemAsync("mozad_full_name", name ?? "");
}

export function getFullName(): string {
  return fullName ?? "";
}

export async function loadTokens() {
  accessToken = await SecureStore.getItemAsync("mozad_access");
  refreshToken = await SecureStore.getItemAsync("mozad_refresh");
  fullName = (await SecureStore.getItemAsync("mozad_full_name")) || null;
}

export async function clearTokens() {
  accessToken = null;
  refreshToken = null;
  fullName = null;
  await SecureStore.deleteItemAsync("mozad_access");
  await SecureStore.deleteItemAsync("mozad_refresh");
  await SecureStore.deleteItemAsync("mozad_full_name");
}

export function hasTokens() {
  return !!accessToken;
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const resp = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!resp.ok) return false;
        const data = await resp.json();
        await saveTokens(data.access_token, data.refresh_token ?? refreshToken!);
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",
    ...((init.headers as Record<string, string>) || {}),
  };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (resp.status === 401 && retry) {
    const ok = await tryRefresh();
    if (ok) return request<T>(path, init, false);
    await clearTokens();
    throw new Error("انتهت الجلسة — سجّل الدخول من جديد");
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : detail;
    } catch {}
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? "{}" : JSON.stringify(body) }),
  saveFullName,
  getFullName,
  /** تنزيل ملف (PDF) بترويسة المصادقة — يعيد مسار الملف المحلي للمشاركة. */
  download: async (path: string): Promise<string> => {
    if (!accessToken) throw new Error("انتهت الجلسة");
    const name = path.split("/").filter(Boolean).pop() ?? "file";
    const target = `${FileSystem.cacheDirectory}mozad-${Date.now()}-${name}.pdf`;
    const res = await FileSystem.downloadAsync(`${API_BASE}${path}`, target, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (res.status !== 200) throw new Error(`تعذر تنزيل الملف (${res.status})`);
    return res.uri;
  },
  login: async (username: string, password: string) => {
    const body = new URLSearchParams({ username, password });
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "ngrok-skip-browser-warning": "true", // مطلوب عبر نفق ngrok المجاني
      },
      body: body.toString(),
    });
    if (!resp.ok) throw new Error("بيانات الدخول غير صحيحة");
    const data = await resp.json();
    await saveTokens(data.access_token, data.refresh_token);
    return data;
  },
  logout: clearTokens,
};
