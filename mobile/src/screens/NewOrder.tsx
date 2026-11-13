/** أوردر جديد: السلة → حفظ أوفلاين في طابور المزامنة (client_ref فريد) — لا يحتاج شبكة. */
import React, { useState } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { getMeta, queueOrder } from "../db";
import { Alert, Btn, Card, Empty, Field, Screen, money, qty } from "../ui";
import { useCart } from "../cart";

function newClientRef() {
  return `mob-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function NewOrderScreen({ navigation }: any) {
  const cart = useCart();
  const [customerId, setCustomerId] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** العميل يُختار من شاشة العملاء (يضبط السلة) — هنا نطلب فقط إكمال التفاصيل */
  const selectedCustomer = (globalThis as any).__mozadSelectedCustomer as { id: number; name: string } | undefined;

  const save = () => {
    setError(null);
    if (!selectedCustomer) {
      setError("اختر العميل من شاشة العملاء أولًا (اضغط «أوردر لهذا العميل»)");
      return;
    }
    if (!cart.items.length) {
      setError("السلة فارغة — أضف أصنافاً من الكتالوج");
      return;
    }
    const clientRef = newClientRef();
    const warehouseId = Number(getMeta("default_warehouse_id") ?? "1") || 1;
    const payload = {
      client_ref: clientRef,
      customer_id: selectedCustomer.id,
      warehouse_id: warehouseId,
      notes: notes.trim() || null,
      items: cart.items.map((it) => ({ product_id: it.product_id, quantity: it.quantity, unit_price: it.unit_price })),
      total: cart.total,
      created_local: new Date().toISOString(),
    };
    queueOrder(clientRef, payload);
    cart.clear();
    (globalThis as any).__mozadSelectedCustomer = undefined;
    setMsg(`✅ حُفظ الأوردر أوفلاين (${payload.items.length} صنف — ${money(cart.total)}) — سيرفع تلقائياً مع المزامنة`);
    setTimeout(() => navigation.goBack(), 1200);
  };

  return (
    <Screen title="🧾 أوردر جديد" subtitle={selectedCustomer ? `العميل: ${selectedCustomer.name}` : "لم يُختر عميل بعد"}>
      <Alert text={msg} />
      <Alert text={error} kind="error" />
      {cart.items.length === 0 ? (
        <Empty text="السلة فارغة — أضف من الكتالوج" />
      ) : (
        <FlatList
          data={cart.items}
          keyExtractor={(it) => String(it.product_id)}
          ListHeaderComponent={null}
          renderItem={({ item }) => (
            <Card style={{ flexDirection: "row-reverse", justifyContent: "space-between", alignItems: "center" }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700", textAlign: "right" }}>{item.name}</Text>
                <Text style={{ color: "#64748b", fontSize: 12, textAlign: "right" }}>
                  {qty(item.quantity)} × {money(item.unit_price)}
                </Text>
              </View>
              <Text style={{ fontWeight: "800", color: "#1f6feb" }}>{money(item.unit_price * item.quantity)}</Text>
            </Card>
          )}
        />
      )}
      <Card>
        <Text style={{ textAlign: "right", fontWeight: "800", fontSize: 16 }}>الإجمالي: {money(cart.total)}</Text>
      </Card>
      <Field placeholder="ملاحظات (اختياري)" value={notes} onChangeText={setNotes} />
      <Btn label="💾 حفظ أوفلاين" onPress={save} />
      <Btn label="🗑 إفراغ السلة" kind="danger" onPress={() => cart.clear()} />
    </Screen>
  );
}
