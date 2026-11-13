/** الرئيسية: ملخص المندوب اليوم + حالة المزامنة + أزرار سريعة. */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { Text, View } from "react-native";
import { api } from "../api";
import { fullSync } from "../sync";
import { listPendingOrders } from "../db";
import { Alert, Btn, Card, Empty, Row, Screen, money, qty } from "../ui";
import { useCart } from "../cart";

export default function HomeScreen({ navigation }: any) {
  const [summary, setSummary] = useState<any>(null);
  const [mgr, setMgr] = useState<any>(null);
  const [pending, setPending] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cart = useCart();

  const refresh = useCallback(async () => {
    setPending(listPendingOrders().length);
    try {
      setSummary(await api.get<any>("/reps/me/summary"));
    } catch {
      /* الحساب قد لا يكون مرتبطاً بمندوب — الشاشة تعمل بالمزامنة */
    }
    // مدير؟ بطاقة الشركة + زر لوحة المدير تظهر فقط عند نجاح الملخص الإداري (403 = مندوب عادي)
    try {
      setMgr(await api.get<any>("/reps/me/manager-summary"));
    } catch {
      setMgr(null);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const doSync = async () => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await fullSync();
      setMsg(
        `✅ مزامنة: رُفع ${r.push.pushed} أوردر${r.push.failed ? ` — فشل ${r.push.failed}` : ""} · نُزل ${r.pull.products} صنف و${r.pull.customers} عميل`
      );
      r.push.errors.forEach((e) => setError((prev) => `${prev ? prev + "\n" : ""}${e}`));
      refresh();
    } catch (e: any) {
      setError(e.message ?? "فشلت المزامنة — تحقق من الشبكة");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen title={`أهلاً ${(globalThis as any).__mozadFullName ?? ""} 👋`} subtitle="عملك اليوم في مكان واحد — يعمل أوفلاين ويتزامن عند توفر الشبكة">
      <Alert text={msg} />
      <Alert text={error} kind="error" />

      <Card>
        <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>📊 ملخصي اليوم</Text>
        {summary ? (
          <>
            <Row left="أوردرات اليوم" right={qty(summary.today_orders ?? 0)} />
            <Row left="تحصيلاتي اليوم" right={money(summary.today_collections ?? 0)} />
            <Row left="صافي مبيعات الفترة (بعد المرتجعات)" right={money(summary.period_net ?? 0)} />
            <Row left="عمولتي التقديرية" right={money(summary.commission ?? 0)} />
          </>
        ) : (
          <Empty text="حسابك غير مرتبط بمندوب — استخدم المزامنة والكتالوج والعملاء" />
        )}
      </Card>

      <Card>
        <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>🔄 المزامنة</Text>
        <Row left="أوردرات بانتظار الرفع" right={qty(pending)} />
        {cart.items.length > 0 && <Row left="في سلة الأوردر الحالي" right={`${qty(cart.items.length)} صنف — ${money(cart.total)}`} />}
        <Btn label="مزامنة الآن" onPress={doSync} busy={busy} />
      </Card>

      {mgr ? (
        <Card>
          <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>🏢 الشركة اليوم</Text>
          <Row left="مبيعات الشركة اليوم" right={money(mgr.today_sales ?? 0)} />
          <Row left="أوردرات بانتظار التأكيد" right={qty(mgr.pending_orders ?? 0)} strong={(mgr.pending_orders ?? 0) > 0} />
          <Btn label="📊 افتح لوحة المدير" kind="ghost" onPress={() => navigation.navigate("manager")} />
        </Card>
      ) : null}

      <Card style={{ flexDirection: "row-reverse", flexWrap: "wrap", gap: 8 }}>
        <View style={{ width: "48%" }}>
          <Btn label="🧾 أوردر جديد" onPress={() => navigation.navigate("new-order")} />
        </View>
        <View style={{ width: "48%" }}>
          <Btn label="📦 أوردراتي" kind="ghost" onPress={() => navigation.navigate("more-menu")} />
        </View>
        <View style={{ width: "48%" }}>
          <Btn label="💵 تحصيل" onPress={() => navigation.navigate("collections")} />
        </View>
        <View style={{ width: "48%" }}>
          <Btn label="🔔 الإشعارات" kind="ghost" onPress={() => navigation.navigate("notifications")} />
        </View>
        <View style={{ width: "48%" }}>
          <Btn label="⏱ الوردية" kind="ghost" onPress={() => navigation.navigate("shift")} />
        </View>
        <View style={{ width: "48%" }}>
          <Btn label="🤝 العملاء المحتملون" kind="ghost" onPress={() => navigation.navigate("leads")} />
        </View>
      </Card>
    </Screen>
  );
}
