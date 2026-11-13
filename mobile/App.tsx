/** MOZAD ERP — تطبيق المندوبين: أوفلاين أولاً، مزامنة تلقائية، RTL عربي. */
import React, { useEffect, useState } from "react";
import { ActivityIndicator, I18nManager, Text, View } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { StatusBar } from "expo-status-bar";

import { api, hasTokens, loadTokens, clearTokens } from "./src/api";
import { initDb } from "./src/db";
import { CartProvider } from "./src/cart";
import { registerDeviceToken } from "./src/push";

import LoginScreen from "./src/screens/Login";
import HomeScreen from "./src/screens/Home";
import CatalogScreen from "./src/screens/Catalog";
import NewOrderScreen from "./src/screens/NewOrder";
import OrdersScreen from "./src/screens/Orders";
import CustomersScreen from "./src/screens/Customers";
import CollectionsScreen from "./src/screens/Collections";
import NotificationsScreen from "./src/screens/Notifications";
import ShiftScreen from "./src/screens/Shift";
import ManagerScreen from "./src/screens/Manager";
import LeadsScreen from "./src/screens/Leads";

// RTL العربي — يطبق مرة واحدة ثم يعاد التشغيل تلقائياً
if (!I18nManager.isRTL) {
  I18nManager.allowRTL(true);
  I18nManager.forceRTL(true);
}

const Stack = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

function TabsRoot() {
  return (
    <Tabs.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: "#1f6feb" },
        headerTintColor: "#fff",
        tabBarActiveTintColor: "#1f6feb",
      }}
    >
      <Tabs.Screen name="الرئيسية" component={HomeScreen} />
      <Tabs.Screen name="الأصناف" component={CatalogScreen} />
      <Tabs.Screen name="العملاء" component={CustomersScreen} />
      <Tabs.Screen name="المزيد" component={MoreStack} />
    </Tabs.Navigator>
  );
}

function MoreStack() {
  return (
    <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: "#1f6feb" }, headerTintColor: "#fff" }}>
      <Stack.Screen name="more-menu" component={OrdersScreen} options={{ title: "أوردراتي" }} />
      <Stack.Screen name="collections" component={CollectionsScreen} options={{ title: "تحصيل" }} />
      <Stack.Screen name="notifications" component={NotificationsScreen} options={{ title: "الإشعارات" }} />
      <Stack.Screen name="shift" component={ShiftScreen} options={{ title: "الوردية" }} />
      <Stack.Screen name="manager" component={ManagerScreen} options={{ title: "لوحة المدير" }} />
      <Stack.Screen name="leads" component={LeadsScreen} options={{ title: "العملاء المحتملون" }} />
    </Stack.Navigator>
  );
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [profile, setProfile] = useState<any>(null);

  useEffect(() => {
    (async () => {
      initDb();
      await loadTokens();
      if (hasTokens()) {
        try {
          const me = await api.get<any>("/auth/me");
          (globalThis as any).__mozadFullName = me.full_name ?? me.username ?? "";
          setProfile(me);
          setAuthed(true);
          registerDeviceToken(); // إشعارات FCM — صامت عند غياب الأذونات
        } catch {
          await clearTokens();
        }
      }
      setReady(true);
    })();
  }, []);

  if (!ready) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator size="large" color="#1f6feb" />
      </View>
    );
  }

  return (
    <CartProvider>
      <NavigationContainer>
        <StatusBar style="light" />
        {authed ? (
          <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: "#1f6feb" }, headerTintColor: "#fff" }}>
            <Stack.Screen name="tabs" component={TabsRoot} options={{ headerShown: false }} />
            <Stack.Screen name="new-order" component={NewOrderScreen} options={{ title: "أوردر جديد" }} />
          </Stack.Navigator>
        ) : (
          <LoginScreen
            onLoggedIn={(me) => {
              (globalThis as any).__mozadFullName = me.full_name ?? me.username ?? "";
              setProfile(me);
              setAuthed(true);
              registerDeviceToken(); // إشعارات FCM — صامت عند غياب الأذونات
            }}
          />
        )}
      </NavigationContainer>
    </CartProvider>
  );
}
