/** عنوان الـAPI: المحاكي يرى جهازك على 10.0.2.2، وعلى الجهاز الحقيقي ضع IP شبكتك. */
import Constants from "expo-constants";

export const API_BASE: string =
  (Constants.expoConfig?.extra as any)?.apiBaseUrl || "http://10.0.2.2:8000";
