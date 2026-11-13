/** عناصر واجهة مشتركة بسيطة — RTL عربي، نمط هادئ متسق. */
import React from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

export const money = (v: string | number | null | undefined) => {
  const n = Number(v ?? 0);
  return `${n.toLocaleString("ar-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م`;
};
export const qty = (v: string | number | null | undefined) => Number(v ?? 0).toLocaleString("ar-EG");

export function Screen({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <View style={styles.screen}>
      <Text style={styles.h1}>{title}</Text>
      {subtitle ? <Text style={styles.sub}>{subtitle}</Text> : null}
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>{children}</ScrollView>
    </View>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: object }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Btn({ label, onPress, kind = "primary", busy, disabled }: {
  label: string; onPress: () => void; kind?: "primary" | "ghost" | "danger"; busy?: boolean; disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || busy}
      style={[styles.btn, kind === "primary" && styles.btnPrimary, kind === "danger" && styles.btnDanger, (disabled || busy) && { opacity: 0.5 }]}
    >
      {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>{label}</Text>}
    </Pressable>
  );
}

export function Field(props: React.ComponentProps<typeof TextInput>) {
  return <TextInput placeholderTextColor="#94a3b8" style={[styles.input, props.style]} {...props} />;
}

export function Empty({ text }: { text: string }) {
  return <Text style={styles.empty}>{text}</Text>;
}

export function Alert({ text, kind = "info" }: { text?: string | null; kind?: "info" | "error" }) {
  if (!text) return null;
  return <Text style={[styles.alert, kind === "error" && styles.alertError]}>{text}</Text>;
}

export function Row({ left, right, strong }: { left: React.ReactNode; right: React.ReactNode; strong?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowText, strong && { fontWeight: "700" }]}>{left}</Text>
      <Text style={[styles.rowValue, strong && { fontWeight: "800" }]}>{right}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, padding: 16, backgroundColor: "#f8fafc" },
  h1: { fontSize: 22, fontWeight: "800", color: "#0f172a", textAlign: "right", marginBottom: 4 },
  sub: { fontSize: 13, color: "#64748b", textAlign: "right", marginBottom: 12 },
  card: { backgroundColor: "#fff", borderRadius: 14, padding: 14, borderWidth: 1, borderColor: "#e2e8f0", marginBottom: 12 },
  btn: { borderRadius: 12, paddingVertical: 12, paddingHorizontal: 18, alignItems: "center", marginVertical: 4 },
  btnPrimary: { backgroundColor: "#1f6feb" },
  btnDanger: { backgroundColor: "#b91c1c" },
  btnText: { color: "#fff", fontWeight: "700", fontSize: 15 },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 12, paddingVertical: 10, paddingHorizontal: 14, fontSize: 15, textAlign: "right", marginBottom: 10 },
  empty: { color: "#64748b", textAlign: "center", padding: 24, fontSize: 14 },
  alert: { color: "#1e40af", backgroundColor: "#dbeafe", borderRadius: 10, padding: 10, fontSize: 13, marginBottom: 8, textAlign: "right" },
  alertError: { color: "#991b1b", backgroundColor: "#fee2e2" },
  row: { flexDirection: "row-reverse", justifyContent: "space-between", paddingVertical: 6 },
  rowText: { color: "#334155", fontSize: 14 },
  rowValue: { color: "#0f172a", fontSize: 14 },
});
