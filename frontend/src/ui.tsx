import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { STATUS_LABEL } from "./format";
import type { OrderStatus } from "./types";

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      <div className="page-actions">{children}</div>
    </div>
  );
}

export function Alert({ children, kind = "error" }: { children: ReactNode; kind?: "error" | "info" }) {
  if (!children) return null;
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Loading() {
  return <div className="muted pad">جارٍ التحميل…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

const PAY_LABEL = { paid: "مسددة", partial: "سداد جزئي", unpaid: "غير مسددة" } as const;

/** Settlement state of a committed invoice / purchase order (nothing for drafts and cancelled orders). */
export function PaymentBadge({ status }: { status?: "paid" | "partial" | "unpaid" | null }) {
  if (!status) return <span className="muted">—</span>;
  const cls = status === "paid" ? "badge-confirmed" : status === "partial" ? "badge-draft" : "badge-off";
  return <span className={`badge ${cls}`}>{PAY_LABEL[status]}</span>;
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="إغلاق">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

/** Looks up a name by id in a list, falling back to "#id". */
export function nameOf<T extends { id: number; name: string }>(list: T[] | null | undefined, id: number | null | undefined) {
  if (id == null) return "—";
  return list?.find((x) => x.id === id)?.name ?? `#${id}`;
}

/** Previous/next controls under a paginated table; hidden when everything fits on one page. */
export function Pager({ list }: { list: { page: number; pages: number; total: number; setPage: (p: number) => void } }) {
  if (list.pages <= 1) return null;
  return (
    <div className="pager" style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "center", padding: 12 }}>
      <button className="btn btn-sm" disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}>
        السابق
      </button>
      <span className="muted">
        صفحة {list.page} من {list.pages} · {list.total} سجل
      </span>
      <button className="btn btn-sm" disabled={list.page >= list.pages} onClick={() => list.setPage(list.page + 1)}>
        التالي
      </button>
    </div>
  );
}

/**
 * Search-as-you-type picker backed by a list endpoint (`?search=`), so it works with any number of records.
 * `value` is the chosen item (or null); the parent keeps it so it can use more than the id.
 */
export function Lookup<T extends { id: number }>({
  path,
  params,
  value,
  onChange,
  label,
  text,
  placeholder = "اكتب للبحث…",
  autoFocus,
}: {
  path: string;
  params?: Record<string, string | number | boolean>;
  value: T | null;
  onChange: (item: T | null) => void;
  label: (item: T) => string;
  text?: (item: T) => string;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<T[]>([]);
  const [busy, setBusy] = useState(false);
  const paramsKey = JSON.stringify(params ?? {});

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const t = setTimeout(() => {
      setBusy(true);
      const sp = new URLSearchParams({ limit: "15" });
      for (const [k, v] of Object.entries(params ?? {})) sp.set(k, String(v));
      if (q.trim()) sp.set("search", q.trim());
      api
        .get<T[]>(`${path}?${sp.toString()}`)
        .then((r) => !cancelled && setItems(r))
        .catch(() => !cancelled && setItems([]))
        .finally(() => !cancelled && setBusy(false));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, open, path, paramsKey]);

  const shown = value ? (text ?? label)(value) : q;
  return (
    <div className="lookup" style={{ position: "relative" }}>
      <input
        value={shown}
        placeholder={placeholder}
        autoFocus={autoFocus}
        aria-label={placeholder}
        role="combobox"
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          if (value) onChange(null);
          setQ(e.target.value);
          setOpen(true);
        }}
      />
      {open && !value && (
        <ul
          role="listbox"
          style={{ position: "absolute", insetInline: 0, top: "100%", zIndex: 20, margin: 0, padding: 4, listStyle: "none", background: "var(--surface, #fff)", border: "1px solid var(--border, #d8dde6)", borderRadius: 8, maxHeight: 240, overflow: "auto", boxShadow: "0 8px 24px rgba(0,0,0,.15)" }}
        >
          {busy && items.length === 0 && <li className="muted" style={{ padding: 8 }}>جارٍ البحث…</li>}
          {!busy && items.length === 0 && <li className="muted" style={{ padding: 8 }}>لا نتائج</li>}
          {items.map((it) => (
            <li
              key={it.id}
              role="option"
              aria-selected={false}
              style={{ padding: "7px 10px", cursor: "pointer", borderRadius: 6 }}
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(it);
                setQ("");
                setOpen(false);
              }}
            >
              {label(it)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
