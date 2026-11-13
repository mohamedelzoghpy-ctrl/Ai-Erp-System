/** أوردراتي: المرادف محلياً (بانتظار الرفع) + المرحّل للنظام + مشاركة إيصال PDF. */
import React, { useState } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import * as Sharing from "expo-sharing";
import { api } from "../api";
import { listPendingOrders, listSyncedOrders } from "../db";
import { Alert, Empty, Screen, money } from "../ui";

export default function OrdersScreen() {
  const pending = listPendingOrders();
  const synced = listSyncedOrders();
  const [error, setError] = useState<string | null>(null);

  const shareReceipt = async (orderId: number) => {
    setError(null);
    try {
      const uri = await api.download(`/sales-orders/${orderId}/receipt`);
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: `إيصال الأوردر #${orderId}` });
      }
    } catch (e: any) {
      setError(e.message ?? "تعذر مشاركة الإيصال");
    }
  };

  return (
    <Screen title="📦 أوردراتي" subtitle="المعلقة تعمل أوفلاين وترفع مع المزامنة">
      <Alert text={error} kind="error" />
      <Text style={s.section}>بانتظار الرفع ({pending.length})</Text>
      {pending.length === 0 ? (
        <Empty text="لا أوردرات معلقة" />
      ) : (
        <FlatList
          data={pending}
          keyExtractor={(o) => o.client_ref}
          renderItem={({ item }) => {
            const p = JSON.parse(item.payload);
            return (
              <View style={s.card}>
                <Text style={s.name}>{p.items?.length ?? 0} صنف — {money(p.total ?? 0)}</Text>
                <Text style={s.meta}>أُنشئ {p.created_local?.slice(0, 16).replace("T", " ")}</Text>
                {item.last_error ? <Text style={s.err}>آخر خطأ: {item.last_error}</Text> : null}
              </View>
            );
          }}
        />
      )}

      <Text style={s.section}>تم رفعها للنظام ({synced.length})</Text>
      {synced.length === 0 ? (
        <Empty text="لم تُرفع أوردرات بعد" />
      ) : (
        <FlatList
          data={synced}
          keyExtractor={(o) => String(o.order_id)}
          renderItem={({ item }) => (
            <View style={s.card}>
              <View style={{ flex: 1 }}>
                <Text style={s.name}>أوردر #{item.order_id} — {money(item.total || 0)}</Text>
                <Text style={s.meta}>رُفع {item.synced_at?.slice(0, 16).replace("T", " ")}</Text>
              </View>
              <Text style={s.share} onPress={() => shareReceipt(item.order_id)}>📤 إيصال</Text>
            </View>
          )}
        />
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  section: { fontWeight: "800", color: "#334155", marginVertical: 8, textAlign: "right" },
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", padding: 12, marginBottom: 8 },
  name: { fontWeight: "700", color: "#0f172a", textAlign: "right" },
  meta: { color: "#94a3b8", fontSize: 12, marginTop: 2, textAlign: "right" },
  err: { color: "#b91c1c", fontSize: 12, marginTop: 4, textAlign: "right" },
  share: { color: "#1f6feb", fontWeight: "700", padding: 8 },
});

