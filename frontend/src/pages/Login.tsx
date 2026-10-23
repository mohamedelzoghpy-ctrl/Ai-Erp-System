import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { useAction } from "../hooks";
import { Alert, Field } from "../ui";

export default function Login() {
  const { login, setupAdmin } = useAuth();
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
        <h1>نظام ERP</h1>
        <div className="sub">{setupMode ? "إنشاء حساب المدير العام الأول" : "تسجيل الدخول"}</div>
        <Alert>{error}</Alert>
        {setupMode && (
          <Field label="الاسم الكامل">
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
          </Field>
        )}
        <Field label="اسم المستخدم" hint={setupMode ? "3 أحرف على الأقل" : undefined}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            minLength={setupMode ? 3 : undefined}
          />
        </Field>
        <Field label="كلمة المرور" hint={setupMode ? "8 أحرف على الأقل" : undefined}>
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
          {busy ? "…" : setupMode ? "إنشاء الحساب والدخول" : "دخول"}
        </button>
        <p className="muted" style={{ marginTop: 14, marginBottom: 0, fontSize: 13 }}>
          {setupMode ? "لديك حساب؟ " : "أول تشغيل للنظام؟ "}
          <button
            type="button"
            className="linklike"
            onClick={() => {
              setSetupMode(!setupMode);
              setError(null);
            }}
          >
            {setupMode ? "تسجيل الدخول" : "إنشاء المدير العام"}
          </button>
        </p>
      </form>
    </div>
  );
}
