/** المزامنة: سحب دلتا (bootstrap?since) + دفع طوابير الأوفلاين (أوردرات + CRM) — idempotent. */
import { api } from "./api";
import {
  setMeta, getMeta, upsertProducts, upsertCustomers, upsertPriceListItems, upsertLeads, upsertStock,
  listPendingOrders, removePendingOrder, bumpPendingOrder, recordSyncedOrder,
  listPendingCrmActivities, removePendingCrmActivity,
  listPendingCrmStages, removePendingCrmStage,
} from "./db";

/** حجم دفعة الرفع — حد الـAPI 100 نرسل بنصفه هامشًا، والدفعات تتعاقب حتى نفاد الطابور. */
const PUSH_CHUNK = 50;

export async function pullBootstrap(): Promise<{ products: number; customers: number; leads: number }> {
  const since = getMeta("last_sync");
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  const data = await api.get<any>(`/sync/bootstrap${qs}`);
  upsertProducts(data.products ?? []);
  upsertStock(data.stock ?? []); // كميات المتاح بمخزن المندوب — كاملة كل مزامنة
  upsertCustomers(data.customers ?? []);
  upsertLeads(data.crm_leads ?? []);
  for (const pl of data.price_lists ?? []) {
    upsertPriceListItems((pl.items ?? []).map((it: any) => ({ ...it, price_list_id: pl.id })));
  }
  setMeta("last_sync", data.server_time);
  if (data.default_warehouse_id) setMeta("default_warehouse_id", String(data.default_warehouse_id));
  return { products: data.products?.length ?? 0, customers: data.customers?.length ?? 0, leads: data.crm_leads?.length ?? 0 };
}

export interface PushResult {
  pushed: number;
  failed: number;
  errors: string[];
}

export async function pushPendingOrders(): Promise<PushResult> {
  const pending = listPendingOrders();
  if (!pending.length) return { pushed: 0, failed: 0, errors: [] };

  let pushed = 0, failed = 0;
  const errors: string[] = [];
  // دفعات متتابعة (PUSH_CHUNK) — فشل شبكة يوقف الحلقة والبقية تبقى في الطابور للمزامنة التالية
  for (let i = 0; i < pending.length; i += PUSH_CHUNK) {
    const chunk = pending.slice(i, i + PUSH_CHUNK);
    try {
      const resp = await api.post<{ results: { client_ref: string; status: string; order_id: number | null; error: string | null }[] }>(
        "/sync/orders",
        { orders: chunk.map((p) => JSON.parse(p.payload)) }
      );
      for (const r of resp.results) {
        if (r.status === "created" || r.status === "duplicate") {
          removePendingOrder(r.client_ref);
          const original = chunk.find((p) => p.client_ref === r.client_ref);
          const parsed = original ? JSON.parse(original.payload) : null;
          recordSyncedOrder(r.order_id!, r.client_ref, parsed ? String(parsed.total ?? "") : "", "draft");
          pushed++;
        } else {
          failed++;
          const msg = r.error ?? "خطأ غير معروف";
          errors.push(`${r.client_ref}: ${msg}`);
          bumpPendingOrder(r.client_ref, msg);
        }
      }
    } catch (e: any) {
      failed += chunk.length;
      errors.push(`دفعة ${Math.floor(i / PUSH_CHUNK) + 1} (${chunk.length} أوردر): ${e.message ?? "فشل الشبكة"}`);
      break; // الشبكة ساقطة — لا معنى لمحاولة الدفعات التالية الآن
    }
  }
  return { pushed, failed, errors };
}

/** دورة مزامنة كاملة: دفع المعلق أولاً ثم سحب الجديد. */
export async function fullSync(): Promise<{ push: PushResult; pull: { products: number; customers: number; leads: number } }> {
  const crm = await pushPendingCrm();
  const push = await pushPendingOrders();
  const pull = await pullBootstrap();
  return { push, pull };
}

/** دفع أنشطة المتابعة وتغييرات المراحل المسجلة أوفلاين (idempotent بالـclient_ref / آخر حالة). */
export async function pushPendingCrm(): Promise<{ pushed: number; failed: number; errors: string[] }> {
  const errors: string[] = [];
  let pushed = 0, failed = 0;

  const activities = listPendingCrmActivities();
  if (activities.length > 0) {
    try {
      const r = await api.post<any>("/sync/crm/activities", {
        activities: activities.map((a) => ({ client_ref: a.client_ref, lead_id: a.lead_id, kind: a.kind, body: a.body })),
      });
      for (const res of r.results ?? []) {
        const row = activities.find((x) => x.client_ref === res.client_ref);
        if (res.ok) { if (row) removePendingCrmActivity(res.client_ref); pushed++; }
        else { failed++; errors.push(`${res.client_ref}: ${res.reason ?? "فشل"}`); }
      }
    } catch (e: any) {
      failed += activities.length;
      errors.push(`رفع الأنشطة فشل: ${e.message}`);
    }
  }

  const stages = listPendingCrmStages();
  if (stages.length > 0) {
    try {
      const r = await api.post<any>("/sync/crm/stages", {
        updates: stages.map((s) => ({ lead_id: s.lead_id, status: s.status, lost_reason: s.lost_reason ?? undefined })),
      });
      for (const res of r.results ?? []) {
        if (res.ok) { removePendingCrmStage(res.lead_id); pushed++; }
        else { failed++; errors.push(`قائد ${res.lead_id}: ${res.reason ?? "فشل"}`); }
      }
    } catch (e: any) {
      failed += stages.length;
      errors.push(`رفع المراحل فشل: ${e.message}`);
    }
  }
  return { pushed, failed, errors };
}
