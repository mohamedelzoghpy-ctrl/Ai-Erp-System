/** لوحة المدير: KPIs من تقارير النظام الموجودة — تعرض فقط لحساب بها صلاحيات التقارير. */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { Text } from "react-native";
import { api } from "../api";
import { Alert, Card, Empty, Row, Screen, money, qty } from "../ui";

export default function ManagerScreen() {
  const [dash, setDash] = useState<any>(null);
  const [aging, setAging] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      (async () => {
        try {
          const [d, a] = await Promise.allSettled([
            api.get<any>("/reports/dashboard"),
            api.get<any>("/reports/receivables/aging"),
          ]);
          if (d.status === "fulfilled") setDash(d.value);
          if (a.status === "fulfilled") setAging(a.value);
          if (d.status === "rejected" && a.status === "rejected") {
            setError("لا تملك صلاحيات التقارير — لوحة المدير للمدراء فقط");
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
      {dash ? (
        <>
          <Card>
            <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>المبيعات</Text>
            <Row left="مبيعات اليوم" right={money(dash.sales_today ?? 0)} />
            <Row left="مبيعات الشهر" right={money(dash.sales_month ?? dash.sales_this_month ?? 0)} />
            <Row left="عدد فواتير اليوم" right={qty(dash.orders_today ?? 0)} />
          </Card>
          <Card>
            <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>التحصيلات</Text>
            <Row left="تحصيلات اليوم" right={money(dash.collections_today ?? 0)} />
            <Row left="أرصدة العملاء (مدينة لنا)" right={money(dash.receivables ?? 0)} />
          </Card>
          <Card>
            <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>المخزون</Text>
            <Row left="قيمة المخزون" right={money(dash.inventory_value ?? 0)} />
            <Row left="أصناف تحت الحد" right={qty(dash.low_stock_count ?? 0)} />
          </Card>
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
