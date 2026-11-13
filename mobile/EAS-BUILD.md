# بناء APK عبر EAS — خطوات جاهزة (مرة واحدة)

الإعدادات جاهزة في `eas.json` (بروفايل `preview` = APK مباشر للتثبيت على الأجهزة).
البناء سحابي على خوادم Expo — لا يحتاج Android Studio ولا Java على جهازك.

## 1) حساب Expo + تسجيل دخول (مرة واحدة)

```bash
cd mobile
npm install -g eas-cli        # أو استخدم npx eas-cli@latest دون تثبيت
eas login                     # سجّل بحساب Expo (إنشاء حساب مجاني: https://expo.dev/signup)
eas whoami                    # للتأكد
```

## 2) ربط المشروع ب حسابك (مرة واحدة)

```bash
eas init                      # ينشئ project id ويحدّث app.json تلقائياً
```

## 3) بناء APK الاختباري (كل مرة تحتاج تحديثاً)

```bash
eas build --platform android --profile preview
```

- البناء يستغرق ~10-15 دقيقة، ويعطيك رابط QR + رابط تنزيل APK.
- ثبّت الـ APK مباشرة على جهاز المندوب (السماح بتثبيت مصادر غير معروفة).
- عند سؤال Keystore: اختر **Create new keystore** (Expo يحفظه لك).

## 4) (اختياري) إشعارات FCM داخل الـ APK

الإشعارات تعمل في تطبيق Expo Go بدون إعداد، لكن APK مستقل يحتاج ملف Firebase:

1. أنشئ مشروعاً على https://console.firebase.google.com → أندرويد باسم الحزمة `com.mozad.erp`
2. نزّل `google-services.json` وضعه في مجلد `mobile/`
3. أضف في `app.json` داخل `expo.android`:
   ```json
   "googleServicesFile": "./google-services.json"
   ```
4. ضع بيانات حساب الخدمة في متغيرات البيئة (موجودة أصلاً للسيرفر): `FCM_SERVICE_ACCOUNT_JSON`

ثم أعد بناء الـ APK.

## 5) نشر رسمي لاحقاً (AAB لمتجر Play)

```bash
eas build --platform android --profile production
```

## ملاحظات

- عنوان الـ API داخل التطبيق في `app.json` → `extra.apiBaseUrl` (حالياً نفق ngrok).
  قبل بناء نسخة إنتاجية، غيّره لعنوان السيرفر الثابت.
- أرقام الإصدارات: `production` يزيد `versionCode` تلقائياً؛ لرفع إصدار الـ preview يدوياً عدّل
  `android.versionCode` في `app.json`.
