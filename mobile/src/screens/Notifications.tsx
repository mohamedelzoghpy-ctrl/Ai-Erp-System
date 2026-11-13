/** الإشعارات: صندوق المندوب من النظام (P0 push triggers تغذيه). */
import React, { useCallback, useState } from "react";
import { useFocusEffect } from "@react-navigation/native";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { api } from "../api";
import { Alert, Empty, Screen } from "../ui";

export default function NotificationsScreen() {
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .get<any[]>("/reps/me/notifications")
        .then(setRows)
        .catch((e) => setError(e.message));
    }, [])
  );

  const markRead = (id: number) => {
    api.post(`/reps/me/notifications/${id}/read`).then(() =>
      setRows((rs) => rs.map((r) => (r.id === id ? { ...r, is_read: true } : r)))
    ).catch(() => {});
  };

  return (
    <Screen title="🔔 الإشعارات" subtitle="تأكيدات الفواتير، التحصيلات، والمرتجعات">
      <Alert text={error} kind="error" />
      <FlatList
        data={rows}
        keyExtractor={(n) => String(n.id)}
        ListEmptyComponent={<Empty text="لا إشعارات بعد" />}
        renderItem={({ item }) => (
          <View style={[s.card, !item.is_read && s.unread]}>
            <Text style={s.title}>{item.title}</Text>
            <Text style={s.body}>{item.body}</Text>
            <Text style={s.time}>{String(item.created_at ?? "").slice(0, 16).replace("T", " ")}</Text>
            {!item.is_read ? (
              <Text style={s.read} onPress={() => markRead(item.id)}>تعليم كمقروء</Text>
            ) : null}
          </View>
        )}
      />
    </Screen>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: "#fff", borderRadius: 12, borderWidth: 1, borderColor: "#e2e8f0", padding: 12, marginBottom: 8 },
  unread: { borderStartWidth: 4, borderStartColor: "#1f6feb" },
  title: { fontWeight: "800", color: "#0f172a", textAlign: "right" },
  body: { color: "#475569", marginTop: 4, textAlign: "right" },
  time: { color: "#94a3b8", fontSize: 11, marginTop: 6, textAlign: "left" },
  read: { color: "#1f6feb", marginTop: 6, textAlign: "left", fontWeight: "600" },
});
