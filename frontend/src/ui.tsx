import { useEffect, type ReactNode } from "react";
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
