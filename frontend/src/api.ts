// Thin fetch wrapper. All calls go to /api/* (proxied to the FastAPI backend).

const BASE = "/api";
const TOKEN_KEY = "erp_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let token: string | null = localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

export function getToken() {
  return token;
}

export function setToken(value: string | null) {
  token = value;
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

function messageFromDetail(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) ? String(d.loc[d.loc.length - 1]) : "";
        return field ? `${field}: ${d.msg}` : String(d.msg);
      })
      .join("، ");
  }
  if (status === 403) return "ليس لديك صلاحية لهذا الإجراء";
  if (status === 401) return "انتهت الجلسة، سجّل الدخول من جديد";
  return `حدث خطأ غير متوقع (${status})`;
}

async function request<T>(method: string, path: string, body?: unknown, form?: URLSearchParams): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(BASE + path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "تعذّر الاتصال بالخادم، تحقق من الشبكة");
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!res.ok) {
    // A 401 on any call except login means the session is gone.
    if (res.status === 401 && path !== "/auth/login" && onUnauthorized) onUnauthorized();
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, messageFromDetail(res.status, detail));
  }
  return data as T;
}

/** Downloads a file from an authenticated endpoint (a plain link cannot send the Bearer token). */
async function download(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(BASE + path, { headers });
  } catch {
    throw new ApiError(0, "تعذّر الاتصال بالخادم، تحقق من الشبكة");
  }
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      detail = null; // error body was not JSON
    }
    throw new ApiError(res.status, messageFromDetail(res.status, detail));
  }
  const blob = await res.blob();
  const match = /filename="?([^";]+)"?/i.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const api = {
  download,
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: (path: string) => request<void>("DELETE", path),
  login: (username: string, password: string) =>
    request<{ access_token: string }>("POST", "/auth/login", undefined, new URLSearchParams({ username, password })),
};

/** Builds "?a=1&b=2" from defined, non-empty values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
