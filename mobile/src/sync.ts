/** المزامنة: سحب دلتا (bootstrap?since) + دفع طابور الأوردرات (idempotent بالـclient_ref). */
import { api } from "./api";
import {
  setMeta, getMeta, upsertProducts, upsertCustomers, upsertPriceListItems,
  listPendingOrders, removePendingOrder, bumpPendingOrder, recordSyncedOrder,
} from "./db";

export async function pullBootstrap(): Promise<{ products: number; customers: number }> {
  const since = getMeta("last_sync");
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  const data = await api.get<any>(`/sync/bootstrap${qs}`);
  upsertProducts(data.products ?? []);
  upsertCustomers(data.customers ?? []);
  for (const pl of data.price_lists ?? []) {
    upsertPriceListItems((pl.items ?? []).map((it: any) => ({ ...it, price_list_id: pl.id })));
  }
  setMeta("last_sync", data.server_time);
  if (data.default_warehouse_id) setMeta("default_warehouse_id", String(data.default_warehouse_id));
  return { products: data.products?.length ?? 0, customers: data.customers?.length ?? 0 };
}

export interface PushResult {
  pushed: number;
  failed: number;
  errors: string[];
}

export async function pushPendingOrders(): Promise<PushResult> {
  const pending = listPendingOrders();
  if (!pending.length) return { pushed: 0, failed: 0, errors: [] };

  // الدفع دفعات صغيرة (حد الـAPI 100) — الافتراضي عملياً دفعة واحدة
  const payload = { orders: pending.map((p) => JSON.parse(p.payload)) };
  const resp = await api.post<{ results: { client_ref: string; status: string; order_id: number | null; error: string | null }[] }>(
    "/sync/orders",
    payload
  );

  let pushed = 0, failed = 0;
  const errors: string[] = [];
  for (const r of resp.results) {
    if (r.status === "created" || r.status === "duplicate") {
      removePendingOrder(r.client_ref);
      const original = pending.find((p) => p.client_ref === r.client_ref);
      const parsed = original ? JSON.parse(original.payload) : null;
      recordSyncedOrder(r.order_id!, r.client_ref, parsed ? String(parsed.total ?? "") : "", r.status === "duplicate" ? "draft" : "draft");
      pushed++;
    } else {
      failed++;
      const msg = r.error ?? "خطأ غير معروف";
      errors.push(`${r.client_ref}: ${msg}`);
      bumpPendingOrder(r.client_ref, msg);
    }
  }
  return { pushed, failed, errors };
}

/** دورة مزامنة كاملة: دفع المعلق أولاً ثم سحب الجديد. */
export async function fullSync(): Promise<{ push: PushResult; pull: { products: number; customers: number } }> {
  const push = await pushPendingOrders();
  const pull = await pullBootstrap();
  return { push, pull };
}
