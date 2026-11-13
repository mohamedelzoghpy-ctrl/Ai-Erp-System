/** العملاء المحتملون (CRM الميداني): قائمة المندوب المسندة إليه — تعمل أوفلاين وتتزامن.
 *  تسجيل نشاط/تغيير مرحلة يُحفظ محليًا فورًا ويُرفع مع أول مزامنة. */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { Linking, Modal, Text, TextInput, View } from "react-native";
import { db, listLeads, queueCrmActivity, queueCrmStage } from "../db";
import { Alert, Btn, Card, Empty, Row, Screen, money } from "../ui";

const STAGES = [
  { key: "new", label: "جديد", color: "#57606a" },
  { key: "contacted", label: "تم التواصل", color: "#0d47a1" },
  { key: "qualified", label: "مؤهل", color: "#6b21a8" },
  { key: "won", label: "تحوّل لعميل", color: "#15803d" },
  { key: "lost", label: "مفقود", color: "#b42318" },
];

const KINDS = [
  { key: "call", label: "📞 مكالمة" },
  { key: "meeting", label: "🤝 اجتماع" },
  { key: "note", label: "📝 ملاحظة" },
];

function waLink(phone: string | null): string | null {
  if (!phone) return null;
  const digits = phone.replace(/[^0-9]/g, "");
  if (digits.length < 8) return null;
  const intl = digits.startsWith("0") ? `2${digits}` : digits; // مصر: 0XXXXXXXXX → 20XXXXXXXXX
  return `https://wa.me/${intl}`;
}

export default function LeadsScreen() {
  const [term, setTerm] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [actFor, setActFor] = useState<any | null>(null);
  const [kind, setKind] = useState("call");
  const [body, setBody] = useState("");
  const [stageFor, setStageFor] = useState<any | null>(null);
  const [stagePick, setStagePick] = useState<string | null>(null);
  const [lostReason, setLostReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setRows(listLeads(term));
  }, [term]);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const saveActivity = () => {
    if (!actFor || !body.trim()) return;
    const ref = `mob-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    queueCrmActivity(ref, actFor.id, kind, body.trim());
    setActFor(null);
    setBody("");
    setMsg("حُفظ النشاط محليًا — سيُرفع مع المزامنة");
    refresh();
  };

  const pickStage = (lead: any, status: string) => {
    setStagePick(status);
    setLostReason("");
  };

  const confirmStage = () => {
    if (!stageFor || !stagePick) return;
    if (stagePick === "lost" && !lostReason.trim()) {
      setError("سبب الفقد مطلوب");
      return;
    }
    queueCrmStage(stageFor.id, stagePick, lostReason.trim() || null);
    db.runSync("UPDATE crm_leads SET status = ? WHERE id = ?", [stagePick, stageFor.id]);
    setStageFor(null);
    setStagePick(null);
    setMsg(stagePick === "won" ? "تم البيع! سيُحوَّل لعميل فعلي مع المزامنة 🎉" : "حُفظت المرحلة محليًا — ستُرفع مع المزامنة");
    setError(null);
    refresh();
  };

  return (
    <Screen
      title="🤝 العملاء المحتملون"
      subtitle="خط مبيعاتك الميداني — يعمل أوفلاين ويتزامن عند توفر الشبكة"
    >
      <Alert text={msg} />
      <Alert text={error} kind="error" />
      <Card>
        <Text style={{ fontWeight: "800", marginBottom: 6, textAlign: "right" }}>🔍 بحث</Text>
        <TextInput
          value={term}
          onChangeText={setTerm}
          onBlur={refresh}
          placeholder="ابحث بالاسم أو النشاط أو الهاتف…"
          style={{ borderWidth: 1, borderColor: "#d0d7de", borderRadius: 8, padding: 8, textAlign: "right" }}
        />
      </Card>

      {rows.length === 0 ? (
        <Empty text="لا عملاء محتملون مسندون إليك بعد — اطلب من المدير إسنادك قادة." />
      ) : (
        rows.map((l) => {
          const st = STAGES.find((s) => s.key === l.status) ?? STAGES[0];
          const wa = waLink(l.phone);
          const open = l.status !== "won" && l.status !== "lost";
          return (
            <Card key={l.id}>
              <View style={{ flexDirection: "row-reverse", justifyContent: "space-between", marginBottom: 4 }}>
                <Text style={{ fontWeight: "800", textAlign: "right" }}>{l.name}</Text>
                <Text style={{ color: st.color, fontWeight: "700", fontSize: 12 }}>{st.label}</Text>
              </View>
              {l.company_name ? <Row left="النشاط" right={l.company_name} /> : null}
              {l.phone ? <Row left="الهاتف" right={l.phone} /> : null}
              <Row left="القيمة المتوقعة" right={money(l.expected_value)} />
              {l.next_follow_up_at ? <Row left="متابعة" right={new Date(l.next_follow_up_at).toLocaleString("ar-EG")} /> : null}
              <View style={{ flexDirection: "row-reverse", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                {l.phone ? (
                  <>
                    <Btn label="📞 اتصال" kind="ghost" onPress={() => Linking.openURL(`tel:${l.phone}`)} />
                    {wa ? <Btn label="💬 واتساب" kind="ghost" onPress={() => Linking.openURL(wa!)} /> : null}
                  </>
                ) : null}
                {open && <Btn label="📝 نشاط" onPress={() => { setActFor(l); setBody(""); }} />}
                {open && <Btn label="⏭ المرحلة" kind="ghost" onPress={() => { setStageFor(l); setStagePick(null); }} />}
              </View>
            </Card>
          );
        })
      )}

      <Modal visible={actFor !== null} transparent animationType="slide" onRequestClose={() => setActFor(null)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}>
          <View style={{ backgroundColor: "#fff", borderRadius: 16, padding: 16 }}>
            <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 10, textAlign: "right" }}>📝 تسجيل نشاط — {actFor?.name}</Text>
            <View style={{ flexDirection: "row-reverse", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              {KINDS.map((k) => (
                <Btn key={k.key} label={k.label} kind={kind === k.key ? "primary" : "ghost"} onPress={() => setKind(k.key)} />
              ))}
            </View>
            <TextInput
              value={body}
              onChangeText={setBody}
              placeholder="اكتب ما حدث في هذه المتابعة…"
              multiline
              style={{ borderWidth: 1, borderColor: "#d0d7de", borderRadius: 8, padding: 10, minHeight: 60, textAlignVertical: "top", textAlign: "right" }}
            />
            <View style={{ flexDirection: "row-reverse", gap: 8, marginTop: 10 }}>
              <Btn label="حفظ" onPress={saveActivity} />
              <Btn label="إلغاء" kind="ghost" onPress={() => setActFor(null)} />
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={stageFor !== null} transparent animationType="slide" onRequestClose={() => setStageFor(null)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}>
          <View style={{ backgroundColor: "#fff", borderRadius: 16, padding: 16 }}>
            <Text style={{ fontWeight: "800", fontSize: 16, marginBottom: 10, textAlign: "right" }}>⏭ تغيير المرحلة — {stageFor?.name}</Text>
            {STAGES.map((s) => (
              <Btn key={s.key} label={s.label} kind={stagePick === s.key ? "primary" : "ghost"} onPress={() => pickStage(stageFor, s.key)} />
            ))}
            {stagePick === "lost" && (
              <TextInput
                value={lostReason}
                onChangeText={setLostReason}
                placeholder="سبب الفقد (مطلوب)"
                style={{ borderWidth: 1, borderColor: "#d0d7de", borderRadius: 8, padding: 8, textAlign: "right", marginTop: 8 }}
              />
            )}
            <View style={{ flexDirection: "row-reverse", gap: 8, marginTop: 10 }}>
              <Btn label="تأكيد" onPress={confirmStage} disabled={!stagePick} />
              <Btn label="إلغاء" kind="ghost" onPress={() => { setStageFor(null); setStagePick(null); }} />
            </View>
          </View>
        </View>
      </Modal>
    </Screen>
  );
}
