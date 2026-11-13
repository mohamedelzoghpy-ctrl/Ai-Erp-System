/** الوردية: فتح برصيد افتتاحي + إقفال بعدّ فعلي — من قلب /shifts (P0 مُختبَر). */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { Text } from "react-native";
import { api } from "../api";
import { Alert, Btn, Card, Field, Row, Screen, money } from "../ui";

export default function ShiftScreen() {
  const [current, setCurrent] = useState<any>(null);
  const [opening, setOpening] = useState("0");
  const [counted, setCounted] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setCurrent(await api.get<any>("/shifts/current"));
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const open = async () => {
    setBusy(true);
    setError(null);
    try {
      setCurrent(await api.post<any>("/shifts/open", { opening_cash: opening || "0" }));
      setMsg("✅ فُتحت الوردية");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const close = async () => {
    setBusy(true);
    setError(null);
    try {
      const closed = await api.post<any>(`/shifts/${current.id}/close`, { counted_cash: counted || "0" });
      setCurrent(null);
      setMsg(
        `تم الإقفال — متوقع ${money(closed.expected_cash)} · معدود ${money(closed.counted_cash)} · الفرق ${money(closed.difference)}`
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen title="⏱ ورديتي" subtitle="درج الكاشير: فتح برصيد افتتاحي وإقفال بعدّ فعلي">
      <Alert text={msg} />
      <Alert text={error} kind="error" />
      {current ? (
        <Card>
          <Row left="الحالة" right="مفتوحة ⏱" strong />
          <Row left="رصيد افتتاحي" right={money(current.opening_cash)} />
          <Row left="نقدية داخلة" right={money(current.cash_in)} />
          <Row left="مرتجعات نقدية" right={money(current.cash_refunds_out)} />
          <Row left="متوقع في الدرج" right={money(current.expected_cash)} strong />
          <Field placeholder="العدّ الفعلي" value={counted} onChangeText={setCounted} keyboardType="numeric" />
          <Btn label="إقفال الوردية" kind="danger" onPress={close} busy={busy} />
        </Card>
      ) : (
        <Card>
          <Text style={{ textAlign: "right", color: "#475569", marginBottom: 8 }}>لا وردية مفتوحة — افتح واحدة لبدء التحصيل</Text>
          <Field placeholder="الرصيد الافتتاحي (الدرج)" value={opening} onChangeText={setOpening} keyboardType="numeric" />
          <Btn label="فتح وردية" onPress={open} busy={busy} />
        </Card>
      )}
    </Screen>
  );
}
