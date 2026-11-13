/** شاشة الدخول — توكن وصول + تجديد (P0) يُخزنان بأمان. */
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from "react-native";
import { api } from "../api";
import { Alert, Btn, Field } from "../ui";

export default function LoginScreen({ onLoggedIn }: { onLoggedIn: (me: any) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      const me = await api.get<any>("/auth/me");
      onLoggedIn(me);
    } catch (e: any) {
      setError(e.message ?? "تعذر تسجيل الدخول");
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.wrap} behavior={Platform.OS === "android" ? undefined : "padding"}>
      <Text style={styles.logo}>MOZAD</Text>
      <Text style={styles.tag}>نظام إدارة المبيعات — حساب المندوب</Text>
      <View style={{ width: "100%", maxWidth: 380 }}>
        <Field placeholder="اسم المستخدم" value={username} onChangeText={setUsername} autoCapitalize="none" />
        <Field placeholder="كلمة السر" value={password} onChangeText={setPassword} secureTextEntry />
        <Alert text={error} kind="error" />
        <Btn label="دخول" onPress={submit} busy={busy} />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#f8fafc", alignItems: "center", justifyContent: "center", padding: 24 },
  logo: { fontSize: 40, fontWeight: "900", color: "#1f6feb", letterSpacing: 2 },
  tag: { color: "#64748b", marginBottom: 28, marginTop: 6 },
});
