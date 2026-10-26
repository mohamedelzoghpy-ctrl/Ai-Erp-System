import type { OrderStatus, PaymentMethod, Role } from "./types";

const LOCALE = "ar-EG-u-nu-latn"; // Arabic text, Latin digits

export function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return n.toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " ج.م";
}

export function num(value: number | string | null | undefined): string {
  return Number(value ?? 0).toLocaleString(LOCALE);
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(LOCALE, { dateStyle: "medium", timeStyle: "short" });
}

export function dayLabel(day: string): string {
  // "2026-10-23" -> short local date; parsed as UTC noon to avoid timezone day-shift.
  return new Date(day + "T12:00:00Z").toLocaleDateString(LOCALE, { day: "numeric", month: "short" });
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: "مدير عام",
  manager: "مدير",
  staff: "موظف",
};

export const STATUS_LABEL: Record<OrderStatus, string> = {
  draft: "مسودة",
  received: "تم الاستلام",
  confirmed: "مؤكد",
  cancelled: "ملغي",
};

export const REASON_LABEL: Record<string, string> = {
  purchase_receipt: "استلام مشتريات",
  sale: "بيع",
  adjustment: "تسوية",
  stocktake: "جرد",
  transfer_out: "تحويل (صادر)",
  transfer_in: "تحويل (وارد)",
  sales_return: "مرتجع بيع",
  purchase_return: "مرتجع شراء",
};

export const METHOD_LABEL: Record<PaymentMethod, string> = {
  cash: "نقداً",
  bank: "تحويل بنكي",
  wallet: "محفظة إلكترونية",
  cheque: "شيك",
};

/** Plain calendar date (YYYY-MM-DD) shown without any timezone shift. */
export function dateOnly(day: string): string {
  return new Date(day + "T12:00:00Z").toLocaleDateString(LOCALE, { year: "numeric", month: "short", day: "numeric" });
}

/** Describes a balance: who owes whom, so a negative number is never ambiguous. */
export function balanceNote(kind: "customer" | "supplier", value: string | number): string {
  const n = Number(value);
  if (n === 0) return "مسدّد";
  if (kind === "customer") return n > 0 ? "مستحق على العميل" : "رصيد دائن للعميل";
  return n > 0 ? "مستحق للمورد" : "رصيد مدين لدى المورد";
}
