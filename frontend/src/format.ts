import type { ChequeStatus, OrderStatus, PaymentMethod, Role } from "./types";
import type { Lang } from "./i18n";

/** زوج تسمية ثنائي اللغة — ar للعربية وen للإنجليزية. */
export type Bi = { ar: string; en: string };

// لغة التنسيق الحالية (عملة/تواريخ) — تضبطها I18nProvider عند تغيير اللغة.
let fmtLang: Lang = "ar";
export function setFormatLang(lang: Lang): void {
  fmtLang = lang;
}
const locale = (): string => (fmtLang === "ar" ? "ar-EG-u-nu-latn" : "en-GB");

export function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return n.toLocaleString(locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (fmtLang === "ar" ? " ج.م" : " EGP");
}

export function num(value: number | string | null | undefined): string {
  return Number(value ?? 0).toLocaleString(locale());
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" });
}

export function dayLabel(day: string): string {
  // "2026-10-23" -> short local date; parsed as UTC noon to avoid timezone day-shift.
  return new Date(day + "T12:00:00Z").toLocaleDateString(locale(), { day: "numeric", month: "short" });
}

export const ROLE_LABEL: Record<Role, Bi> = {
  admin: { ar: "مدير عام", en: "Admin" },
  manager: { ar: "مدير", en: "Manager" },
  staff: { ar: "موظف", en: "Staff" },
};

export function roleLabel(role: Role, lang: Lang = fmtLang): string {
  return ROLE_LABEL[role][lang];
}

export const STATUS_LABEL: Record<OrderStatus, Bi> = {
  draft: { ar: "مسودة", en: "Draft" },
  received: { ar: "تم الاستلام", en: "Received" },
  confirmed: { ar: "مؤكد", en: "Confirmed" },
  cancelled: { ar: "ملغي", en: "Cancelled" },
  partial: { ar: "استلام جزئي", en: "Partially received" },
};

export function statusLabel(status: OrderStatus, lang: Lang = fmtLang): string {
  return STATUS_LABEL[status][lang];
}

export const REASON_LABEL: Record<string, Bi> = {
  purchase_receipt: { ar: "استلام مشتريات", en: "Purchase receipt" },
  sale: { ar: "بيع", en: "Sale" },
  adjustment: { ar: "تسوية", en: "Adjustment" },
  stocktake: { ar: "جرد", en: "Stocktake" },
  stock_import: { ar: "استيراد مخزون", en: "Stock import" },
  transfer_out: { ar: "تحويل (صادر)", en: "Transfer (out)" },
  transfer_in: { ar: "تحويل (وارد)", en: "Transfer (in)" },
  transfer_in_transit: { ar: "تحويل (إلى العابر)", en: "Transfer (to transit)" },
  transfer_receipt: { ar: "تحويل (استلام من العابر)", en: "Transfer (transit receipt)" },
  transfer_cancel: { ar: "تحويل (إلغاء عائد)", en: "Transfer (cancel return)" },
  transfer_edit: { ar: "تحويل (تعديل)", en: "Transfer (edit)" },
  qc_reject: { ar: "رفض فحص جودة", en: "QC reject" },
  sales_return: { ar: "مرتجع بيع", en: "Sales return" },
  purchase_return: { ar: "مرتجع شراء", en: "Purchase return" },
};

export function reasonLabel(reason: string, lang: Lang = fmtLang): string {
  return REASON_LABEL[reason]?.[lang] ?? reason;
}

export const METHOD_LABEL: Record<PaymentMethod, Bi> = {
  cash: { ar: "نقداً", en: "Cash" },
  bank: { ar: "تحويل بنكي", en: "Bank transfer" },
  wallet: { ar: "محفظة إلكترونية", en: "E-Wallet" },
  cheque: { ar: "شيك", en: "Cheque" },
};

export function methodLabel(method: PaymentMethod, lang: Lang = fmtLang): string {
  return METHOD_LABEL[method][lang];
}

export const CHEQUE_STATUS_LABEL: Record<ChequeStatus, Bi> = {
  under_collection: { ar: "تحت التحصيل", en: "Under collection" },
  issued: { ar: "مصروف", en: "Issued" },
  collected: { ar: "محصّل", en: "Collected" },
  cashed: { ar: "تم صرفه", en: "Cashed" },
  returned: { ar: "مرتد", en: "Returned" },
};

export function chequeStatusLabel(status: ChequeStatus, lang: Lang = fmtLang): string {
  return CHEQUE_STATUS_LABEL[status][lang];
}

/** Plain calendar date (YYYY-MM-DD) shown without any timezone shift. */
export function dateOnly(day: string): string {
  return new Date(day + "T12:00:00Z").toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" });
}

/** Describes a balance: who owes whom, so a negative number is never ambiguous. */
export function balanceNote(kind: "customer" | "supplier", value: string | number, lang: Lang = fmtLang): string {
  const ar = lang === "ar";
  const n = Number(value);
  if (n === 0) return ar ? "مسدّد" : "Settled";
  if (kind === "customer") return n > 0 ? (ar ? "مستحق على العميل" : "Due from customer") : (ar ? "رصيد دائن للعميل" : "Customer credit balance");
  return n > 0 ? (ar ? "مستحق للمورد" : "Due to supplier") : (ar ? "رصيد مدين لدى المورد" : "Supplier debit balance");
}
