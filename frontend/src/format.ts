import type { OrderStatus, Role } from "./types";

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
};
