/** العملاء: من القاعدة المحلية — اختيار عميل للأوردر + أورده له (يضبط قائمة أسعاره). */
import React, { useState } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { listCustomers } from "../db";
import { Alert, Btn, Empty, Field, Screen, money } from "../ui";
import { setCurrentPriceList } from "./Catalog";
import { useCart } from "../cart";

export default function CustomersScreen({ navigation }: any) {
  const [term, setTerm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const customers = listCustomers(term);
  const cart = useCart();

  const pick = (c: any) => {
    cart.setCustomer({ id: c.id, name: c.name });
    setCurrentPriceList(c.price_list_id ?? null);
    setMsg(`✅ العميل «${c.name}» جاهز — أضف الأصناف من الكتالوج`);
  };

  const newOrderFor = (c: any) => {
    pick(c);
    navigation.navigate("new-order");
  };

  return (
    <Screen title="👥 العملاء" subtitle="اختر عميلاً لضبط قائمة أسعاره ثم أنشئ أوردره">
      <Alert text={msg} />
      <Field placeholder="بحث بالاسم أو الهاتف…" value={term} onChangeText={setTerm} />
      <FlatList
        data={customers}
        keyExtractor={(c) => String(c.id)}
        ListEmptyComponent={<Empty text={term ? "لا نتائج" : "لا عملاء — نفّذ المزامنة من الرئيسية"} />}
        renderItem={({ item }) => (
          <View style={s.card}>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{item.name}</Text>
              {item.phone ? <Text style={s.phone}>{item.phone}</Text> : null}
              <Text style={[s.balance, { color: Number(item.balance) > 0 ? "#b91c1c" : "#15803d" }]}>
                الرصيد: {money(item.balance)}
                {item.credit_limit ? ` — الحد ${money(item.credit_limit)}` : ""}
              </Text>
            </View>
            <View style={{ gap: 6 }}>
              <Btn label="أوردر له" onPress={() => newOrderFor(item)} />
              <Btn label="اختيار" kind="ghost" onPress={() => pick(item)} />
            </View>
          </View>
        )}
      />
    </Screen>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", padding: 12, marginBottom: 8, flexDirection: "row-reverse", alignItems: "center", gap: 10 },
  name: { fontWeight: "700", color: "#0f172a", textAlign: "right" },
  phone: { color: "#64748b", fontSize: 12, marginTop: 2 },
  balance: { fontSize: 12, marginTop: 4, textAlign: "right" },
});
