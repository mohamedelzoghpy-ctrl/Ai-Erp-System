/** تسجيل جهاز المندوب للإشعارات (FCM) — idempotent عبر /reps/me/devices. */
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

export async function registerDeviceToken() {
  try {
    if (!Device.isDevice) return; // المحاكي بلا FCM — لا شيء يُسجل
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== "granted") return;

    let token: string | null = null;
    if (Platform.OS === "android") {
      // في EAS build يُضبط projectId — عند غيابه نستخدم توكن Expo كمعرف جهاز مؤقت
      const t = await Notifications.getDevicePushTokenAsync().catch(() => null);
      token = t?.data ? String(t.data) : null;
    }
    if (!token) {
      const expo = await Notifications.getExpoPushTokenAsync().catch(() => null);
      token = expo?.data ?? null;
    }
    if (!token) return;

    await api.post("/reps/me/devices", {
      fcm_token: token,
      platform: Platform.OS === "android" ? "android" : "ios",
    });
  } catch {
    // التسجيل لا يعطل التشغيل إطلاقاً — الإشعارات Pull تعمل بلا Push
  }
}
