import { useEffect, useState, type ReactNode } from "react";
import { api, getToken } from "./api";
import { statusLabel } from "./format";
import { useI18n } from "./i18n";
import type { OrderStatus, Product } from "./types";

function NoImage() {
  const { t } = useI18n();
  return <div className="product-thumb-empty" aria-label={t("common.noImage")}>📦</div>;
}

/** صورة مصغّرة للمنتج: مرفوعة (bytea عبر /products/{id}/image) أو رابط إنترنت — أو 📦 */
export function ProductThumb({ product }: { product: Product }) {
  const [failed, setFailed] = useState(false);
  const tok = getToken();
  const src = product.image_uploaded
    ? `/api/products/${product.id}/image${tok ? `?token=${encodeURIComponent(tok)}` : ""}`
    : product.image_url || null;
  if (!src || failed) return <NoImage />;
  return (
    <img
      className="product-thumb"
      src={src}
      alt={product.name}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

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
  const { t } = useI18n();
  return <div className="muted pad">{t("common.loading")}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function StatusBadge({ status }: { status: OrderStatus }) {
  const { lang } = useI18n();
  return <span className={`badge badge-${status}`}>{statusLabel(status, lang)}</span>;
}

/** حالة التفعيل الموحدة في كل الشاشات: «نشط» / «موقوف». */
export function ActiveBadge({ active }: { active: boolean }) {
  const { t } = useI18n();
  return (
    <span className={`badge ${active ? "badge-active" : "badge-inactive"}`}>
      <span className="status-dot" />
      {active ? t("common.active") : t("common.suspended")}
    </span>
  );
}

const PAY_LABEL = {
  paid: { ar: "مسددة", en: "Paid" },
  partial: { ar: "سداد جزئي", en: "Partially paid" },
  unpaid: { ar: "غير مسددة", en: "Unpaid" },
} as const;

/** Settlement state of a committed invoice / purchase order (nothing for drafts and cancelled orders). */
export function PaymentBadge({ status }: { status?: "paid" | "partial" | "unpaid" | null }) {
  const { lang } = useI18n();
  if (!status) return <span className="muted">—</span>;
  const cls = status === "paid" ? "badge-confirmed" : status === "partial" ? "badge-draft" : "badge-off";
  return <span className={`badge ${cls}`}>{PAY_LABEL[status][lang]}</span>;
}

export function Modal({
  title,
  onClose,
  children,
  wide,
  fullscreen,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  fullscreen?: boolean;
}) {
  const { t } = useI18n();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}${fullscreen ? " modal-fullscreen" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
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
  const { lang } = useI18n();
  if (list.pages <= 1) return null;
  return (
    <div className="pager" style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "center", padding: 12 }}>
      <button className="btn btn-sm" disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}>
        {lang === "ar" ? "السابق" : "Previous"}
      </button>
      <span className="muted">
        {lang === "ar" ? `صفحة ${list.page} من ${list.pages} · ${list.total} سجل` : `Page ${list.page} of ${list.pages} · ${list.total} records`}
      </span>
      <button className="btn btn-sm" disabled={list.page >= list.pages} onClick={() => list.setPage(list.page + 1)}>
        {lang === "ar" ? "التالي" : "Next"}
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
  placeholder,
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
  const { t } = useI18n();
  const ph = placeholder ?? t("common.typeToSearch");
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
        placeholder={ph}
        autoFocus={autoFocus}
        aria-label={ph}
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
          {busy && items.length === 0 && <li className="muted" style={{ padding: 8 }}>{t("common.searching")}</li>}
          {!busy && items.length === 0 && <li className="muted" style={{ padding: 8 }}>{t("common.noResults")}</li>}
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
