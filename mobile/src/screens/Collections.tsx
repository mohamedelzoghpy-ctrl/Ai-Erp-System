/** التحصيلات: سند قبض ميداني عبر /reps/me/collections (قيود كاملة في النظام). */
import React, { useState } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { api } from "../api";
import { listCustomers } from "../db";
import { Alert, Btn, Card, Empty, Field, Screen, money } from "../ui";

export default function CollectionsScreen({ navigation }: any) {
  const [selected, setSelected] = useState<any | null>(null);
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const customers = listCustomers("");

  const submit = async () => {
    setError(null);
    if (!selected) {
      setError("اختر العميل أولًا");
      return;
    }
    const value = Number(amount);
    if (!value || value <= 0) {
      setError("أدخل مبلغاً صحيحاً أكبر من صفر");
      return;
    }
    setBusy(true);
    try {
      // التحصيل يتطلب شبكة — سند نقدي حقيقي بقيود محاسبية (لا يُصطف أوفلاين)
      const res = await api.post<any>("/reps/me/collections", {
        customer_id: selected.id,
        amount: value,
        notes: notes.trim() || null,
      });
      setMsg(`✅ سند #${res.payment_id} — حُصّل ${money(res.amount)} من «${selected.name}»`);
      setSelected(null);
      setAmount("");
      setNotes("");
    } catch (e: any) {
      setError(e.message ?? "فشل التحصيل — تحقق من الشبكة");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen title="💵 تحصيل" subtitle="سند قبض نقدي رسمي — يتطلب اتصالاً بالنظام">
      <Alert text={msg} />
      <Alert text={error} kind="error" />

      {!selected ? (
        <>
          <Text style={s.hint}>اختر العميل:</Text>
          <FlatList
            data={customers}
            keyExtractor={(c) => String(c.id)}
            ListEmptyComponent={<Empty text="لا عملاء — نفّذ المزامنة أولًا" />}
            renderItem={({ item }) => (
              <View style={s.card}>
                <View style={{ flex: 1 }}>
                  <Text style={s.name}>{item.name}</Text>
                  <Text style={[s.balance, { color: Number(item.balance) > 0 ? "#b91c1c" : "#15803d" }]}>
                    يدين لنا: {money(item.balance)}
                  </Text>
                </View>
                <Btn label="تحصيل منه" onPress={() => setSelected(item)} />
              </View>
            )}
          />
        </>
      ) : (
        <Card>
          <Text style={{ textAlign: "right", fontWeight: "800", marginBottom: 8 }}>
            العميل: {selected.name} — يدين: {money(selected.balance)}
          </Text>
          <Field placeholder="المبلغ المحصل" value={amount} onChangeText={setAmount} keyboardType="numeric" autoFocus />
          <Field placeholder="ملاحظة (اختياري)" value={notes} onChangeText={setNotes} />
          <Btn label="💵 تسجيل التحصيل" onPress={submit} busy={busy} />
          <Btn label="إلغاء" kind="ghost" onPress={() => { setSelected(null); setAmount(""); setNotes(""); }} />
        </Card>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  hint: { color: "#64748b", textAlign: "right", marginBottom: 8 },
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", padding: 12, marginBottom: 8, flexDirection: "row-reverse", alignItems: "center", gap: 10 },
  name: { fontWeight: "700", color: "#0f172a", textAlign: "right" },
  balance: { fontSize: 12, marginTop: 4, textAlign: "right" },
});
