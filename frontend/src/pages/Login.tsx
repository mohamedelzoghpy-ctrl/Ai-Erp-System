import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { useAction } from "../hooks";
import { Alert, Field } from "../ui";
import { useI18n } from "../i18n";

export default function Login() {
  const { login, setupAdmin } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [setupMode, setSetupMode] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const { busy, error, setError, run } = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(() => (setupMode ? setupAdmin(username, password, fullName) : login(username, password)));
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <h1>{t("app.name")}</h1>
        <div className="sub">{setupMode ? t("auth.setup") : t("auth.login")}</div>
        <Alert>{error}</Alert>
        {setupMode && (
          <Field label={t("auth.fullName")}>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
          </Field>
        )}
        <Field label={t("auth.username")} hint={setupMode ? (lang === "ar" ? "3 أحرف على الأقل" : "At least 3 characters") : undefined}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            minLength={setupMode ? 3 : undefined}
          />
        </Field>
        <Field label={t("auth.password")} hint={setupMode ? (lang === "ar" ? "8 أحرف على الأقل" : "At least 8 characters") : undefined}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={setupMode ? "new-password" : "current-password"}
            required
            minLength={setupMode ? 8 : undefined}
          />
        </Field>
        <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
          {busy ? "…" : setupMode ? t("auth.setup") : t("auth.login")}
        </button>
        <p className="muted" style={{ marginTop: 14, marginBottom: 0, fontSize: 13 }}>
          {setupMode ? (lang === "ar" ? "لديك حساب؟ " : "Have an account? ") : (lang === "ar" ? "أول تشغيل للنظام؟ " : "First run? ")}
          <button
            type="button"
            className="linklike"
            onClick={() => {
              setSetupMode(!setupMode);
              setError(null);
            }}
          >
            {setupMode ? t("auth.login") : t("auth.setup")}
          </button>
        </p>
        <div style={{ marginTop: 12, textAlign: "center" }}>
          <button type="button" className="linklike" onClick={() => setLang(lang === "ar" ? "en" : "ar")}>
            {lang === "ar" ? "English" : "العربية"}
          </button>
        </div>
      </form>
    </div>
  );
}
