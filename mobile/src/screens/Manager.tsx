/** لوحة المدير: ملخص الشركة من /reps/me/manager-summary (مبيعات، تحصيلات، معلقة،
 *  أفضل المنتجات، أعلى المديونيات) + أعمار الديون من التقارير. يظهر لحاملي صلاحية التقارير فقط. */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { Text } from "react-native";
import { api } from "../api";
import { Alert, Card, Empty, Row, Screen, money, qty } from "../ui";

export default function ManagerScreen() {
  const [sum, setSum] = useState<any>(null);
  const [aging, setAging] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      (async () => {
        try {
          const [s, a] = await Promise.allSettled([
            api.get<any>("/reps/me/manager-summary"),
            api.get<any>("/reports/receivables/aging"),
          ]);
          if (s.status === "fulfilled") setSum(s.value);
          if (a.status === "fulfilled") setAging(a.value);
          if (s.status === "rejected") {
            setError("لا تملك صلاحيات التقارير — لوحة المدير للمدراء فقط");
          } else if (a.status === "rejected") {
            setError("أعمار الديون غير متاحة بصلاحياتك — بقية اللوحة تعمل");
          }
        } catch (e: any) {
          setError(e.message);
        }
      })();
    }, [])
  );

  return (
    <Screen title="📊 لوحة المدير" subtitle="نظرة اليوم على المبيعات والتحصيلات">
      <Alert text={error} kind="error" />
      {sum ? (
        <>
          <Card>
            <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>المبيعات ({sum.as_of})</Text>
            <Row left="مبيعات اليوم" right={money(sum.today_sales ?? 0)} />
            <Row left="فواتير اليوم" right={qty(sum.today_orders ?? 0)} />
            <Row left="مبيعات الشهر" right={money(sum.month_sales ?? 0)} />
            <Row left="فواتير الشهر" right={qty(sum.month_orders ?? 0)} />
          </Card>
          <Card>
            <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>التحصيلات والتشغيل</Text>
            <Row left="تحصيلات اليوم (كل الخزائن)" right={money(sum.collected_today ?? 0)} />
            <Row left="أوردرات بانتظار التأكيد" right={qty(sum.pending_orders ?? 0)} strong={(sum.pending_orders ?? 0) > 0} />
          </Card>

          {sum.top_products?.length ? (
            <Card>
              <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>🏆 أفضل المنتجات هذا الشهر</Text>
              {sum.top_products.map((p: any, i: number) => (
                <Row key={i} left={`${i + 1}. ${p.name}`} right={`${money(p.value)} · ${qty(p.quantity)}`} />
              ))}
            </Card>
          ) : null}

          {sum.top_debtors?.length ? (
            <Card>
              <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>⚠️ أعلى العملاء مديونية</Text>
              {sum.top_debtors.map((d: any, i: number) => (
                <Row key={i} left={d.name} right={money(d.balance)} strong={i === 0} />
              ))}
            </Card>
          ) : null}
        </>
      ) : !error ? (
        <Empty text="جارٍ التحميل…" />
      ) : null}

      {aging?.rows?.length ? (
        <Card>
          <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>أعمار الديون (إجمالي مفتوح)</Text>
          <Row left="حالي (0-30 يوم)" right={money(aging.total_current)} />
          <Row left="31-60 يوم" right={money(aging.total_d31_60)} />
          <Row left="61-90 يوم" right={money(aging.total_d61_90)} />
          <Row left="أكثر من 90" right={money(aging.total_d90_plus)} strong />
        </Card>
      ) : null}
    </Screen>
  );
}
