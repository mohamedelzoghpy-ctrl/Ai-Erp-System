/** الكتالوج: من قاعدة الموبايل المحلية (أوفلاين كامل) — بحث + إضافة للسلة بسعر قائمة العميل + متاح المخزن. */
import React, { useState } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { listProducts, priceFor, type ProductRow } from "../db";
import { getMeta } from "../db";
import { Btn, Empty, Field, Screen, money, qty } from "../ui";
import { useCart } from "../cart";

/** قائمة أسعار العميل المختار للسلة — تُضبط من شاشة العملاء أو أوردر جديد. */
let currentPriceListId: number | null = null;
export function setCurrentPriceList(id: number | null) {
  currentPriceListId = id;
}
export function getCurrentPriceList() {
  return currentPriceListId ?? (getMeta("default_price_list") ? Number(getMeta("default_price_list")) : null);
}

export default function CatalogScreen({ navigation }: any) {
  const [term, setTerm] = useState("");
  const [tick, setTick] = useState(0);
  const cart = useCart();
  const products = listProducts(term);
  const plId = getCurrentPriceList();

  const add = (p: ProductRow) => {
    cart.add({ product_id: p.id, name: p.name, unit: p.unit, unit_price: Number(priceFor(p, plId)) });
    setTick((t) => t + 1);
  };

  return (
    <Screen title="📦 الكتالوج" subtitle={plId ? `أسعار قائمة مختارة #${plId}` : "أسعار البيع المعتمدة"}>
      <Field placeholder="بحث بالاسم أو الباركود…" value={term} onChangeText={setTerm} />
      {cart.items.length > 0 && (
        <Btn label={`متابعة الأوردر (${qty(cart.items.length)} صنف — ${money(cart.total)})`} onPress={() => navigation.navigate("new-order")} />
      )}
      <FlatList
        data={products}
        keyExtractor={(p) => String(p.id)}
        extraData={tick}
        ListEmptyComponent={<Empty text={term ? "لا نتائج مطابقة" : "لا أصناف — نفّذ المزامنة من الرئيسية"} />}
        renderItem={({ item }) => {
          const stock = item.stock != null ? Number(item.stock) : null;
          return (
          <View style={s.card}>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{item.name}</Text>
              <Text style={s.sku}>{item.sku}</Text>
              <Text style={s.price}>{money(priceFor(item, plId))} / {item.unit}</Text>
              {stock != null && (
                <Text style={{ color: stock <= 0 ? "#b91c1c" : "#15803d", fontSize: 11, marginTop: 2, textAlign: "right" }}>
                  {stock <= 0 ? "غير متاح بالمخزن" : `متاح: ${qty(stock)}`}
                </Text>
              )}
            </View>
            <Btn label="＋ أضف" onPress={() => add(item)} />
          </View>
          );
        }}
      />
    </Screen>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", padding: 12, marginBottom: 8, flexDirection: "row-reverse", alignItems: "center", gap: 10 },
  name: { fontWeight: "700", color: "#0f172a", textAlign: "right" },
  sku: { color: "#94a3b8", fontSize: 11, textAlign: "left", marginTop: 2 },
  price: { color: "#1f6feb", fontWeight: "700", marginTop: 4, textAlign: "right" },
});
