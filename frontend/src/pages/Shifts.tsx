import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { dateTime, money } from "../format";
import { useAction, useFetch, usePagedList } from "../hooks";
import type { Shift } from "../types";
import { Alert, Empty, Field, Loading, Modal, PageHeader, Pager } from "../ui";

function diffText(d: string | number | null, t: (k: string) => string) {
  if (d === null) return "—";
  const n = Number(d);
  if (Math.abs(n) < 0.005) return t("shifts.matched");
  return `${n > 0 ? t("shifts.increase") : t("shifts.shortage")} ${money(Math.abs(n))}`;
}

function Summary({ s }: { s: Shift }) {
  const { t } = useI18n();
  return (
    <table className="kv" style={{ width: "100%", marginBottom: 12 }}>
      <tbody>
        <tr><td>{t("shifts.openingBalance")}</td><td>{money(s.opening_cash)}</td></tr>
        <tr><td>+ {t("shifts.cashReceivedFromCustomers")}</td><td>{money(s.cash_in)}</td></tr>
        {Number(s.cash_refunds_in) > 0 && <tr><td>+ {t("shifts.cashRefundsFromSuppliers")}</td><td>{money(s.cash_refunds_in)}</td></tr>}
        <tr><td>− {t("shifts.cashPaidToSuppliers")}</td><td>{money(s.cash_out)}</td></tr>
        {Number(s.cash_refunds_out) > 0 && <tr><td>− {t("shifts.cashRefundsToCustomers")}</td><td>{money(s.cash_refunds_out)}</td></tr>}
        <tr><td><strong>{t("shifts.expectedInDrawerStrong")}</strong></td><td><strong>{money(s.expected_cash)}</strong></td></tr>
        <tr><td className="muted">{t("shifts.nonCash")}</td><td className="muted">{money(s.other_methods_in)}</td></tr>
      </tbody>
    </table>
  );
}

/** Shift bar for the POS screen: shows the open shift or offers to open one. */
export function ShiftBar({ onChange }: { onChange?: (open: boolean) => void }) {
  const cur = useFetch(() => api.get<Shift | null>("/shifts/current"), "shift-current");
  const { t } = useI18n();
  const [dialog, setDialog] = useState<"open" | "close" | null>(null);
  const [cash, setCash] = useState("");
  const [notes, setNotes] = useState("");
  const act = useAction();
  const dl = useAction();
  const [closedId, setClosedId] = useState<number | null>(null);
  const s = cur.data;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      if (dialog === "open") await api.post("/shifts/open", { opening_cash: cash || "0" });
      else if (s) setClosedId((await api.post<Shift>(`/shifts/${s.id}/close`, { counted_cash: cash, notes: notes || null })).id);
      setDialog(null);
      setCash("");
      setNotes("");
      cur.reload();
      onChange?.(dialog === "open");
    });
  };

  const counted = Number(cash);
  const preview = dialog === "close" && s && cash !== "" ? counted - Number(s.expected_cash) : null;

  return (
    <>
      <div className="card" style={{ padding: "8px 14px", marginBottom: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }} data-testid="shift-bar">
        {cur.loading && !cur.data ? (
          <span className="muted">…</span>
        ) : s ? (
          <>
            <span>{t("shifts.openedSince")} {dateTime(s.opened_at)} · {t("shifts.expectedInDrawer")} <strong>{money(s.expected_cash)}</strong></span>
            <button className="btn btn-sm" onClick={() => { act.setError(null); setCash(""); setDialog("close"); }}>{t("shifts.close")}</button>
          </>
        ) : (
          <>
            <span className="muted">{t("shifts.noOpenShift")}</span>
            <button className="btn btn-sm btn-primary" onClick={() => { act.setError(null); setCash(""); setDialog("open"); }}>{t("shifts.open")}</button>
          </>
        )}
      </div>
      {closedId !== null && !s && (
        <div className="card" style={{ padding: "8px 14px", marginBottom: 12, display: "flex", gap: 12, alignItems: "center" }}>
          <span>{t("shifts.closed")}</span>
          <button className="btn btn-sm" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/shifts/${closedId}/pdf`, `shift-${closedId}.pdf`))}>{t("shifts.reportPdf")}</button>
          <Alert>{dl.error}</Alert>
        </div>
      )}
      {dialog && (
        <Modal title={dialog === "open" ? t("shifts.open") : t("shifts.close")} onClose={() => setDialog(null)}>
          <form onSubmit={submit}>
            <Alert>{act.error}</Alert>
            {dialog === "close" && s && <Summary s={s} />}
            <Field label={dialog === "open" ? t("shifts.opening") : t("shifts.countedCash")}>
              <input type="number" min="0" step="0.01" required={dialog === "close"} autoFocus value={cash} onChange={(e) => setCash(e.target.value)} aria-label={t("shifts.countedCash")} />
            </Field>
            {preview !== null && <p data-testid="shift-diff"><strong>{diffText(preview, t)}</strong></p>}
            {dialog === "close" && (
              <Field label={t("shifts.notes")}>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </Field>
            )}
            <div className="actions">
              <button className="btn btn-primary" disabled={act.busy}>{dialog === "open" ? t("shifts.open") : t("shifts.closeShift")}</button>
              <button type="button" className="btn" onClick={() => setDialog(null)}>{t("common.cancel")}</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function AdminCloseDialog({ shift, onClose, onDone }: { shift: Shift; onClose: () => void; onDone: () => void }) {
  const [cash, setCash] = useState("");
  const [notes, setNotes] = useState("إغلاق إداري لوردية منسية");
  const { t } = useI18n();
  const act = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void act.run(async () => {
      await api.post(`/shifts/${shift.id}/close`, { counted_cash: cash, notes: notes || null });
      onDone();
    });
  };
  return (
    <Modal title={`${t("shifts.adminCloseTitle")} ${shift.username}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Alert>{act.error}</Alert>
        <Summary s={shift} />
        <Field label={t("shifts.countedCash")} hint={t("shifts.countedHint")}>
          <input type="number" min="0" step="0.01" required autoFocus value={cash} onChange={(e) => setCash(e.target.value)} aria-label={t("shifts.countedCash")} />
        </Field>
        <Field label={t("shifts.notes")}>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="actions">
          <button className="btn btn-primary" disabled={act.busy}>{t("shifts.closeShift")}</button>
          <button type="button" className="btn" onClick={onClose}>{t("common.cancel")}</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Shifts() {
  const { isManager } = useAuth();
  const { t } = useI18n();
  const list = usePagedList<Shift>("/shifts", {});
  const [closing, setClosing] = useState<Shift | null>(null);
  const dl = useAction();
  return (
    <>
      <PageHeader title={t("shifts.title")} />
      <Alert>{list.error || dl.error}</Alert>
      <div className="card table-wrap">
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data && list.data.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>{t("shifts.cashier")}</th><th>{t("shifts.opened")}</th><th>{t("shifts.closedAt")}</th><th>{t("shifts.opening")}</th><th>{t("shifts.cashIn")}</th><th>{t("shifts.cashOut")}</th><th>{t("shifts.cashRefunds")}</th><th>{t("shifts.expected")}</th><th>{t("shifts.counted")}</th><th>{t("shifts.difference")}</th><th></th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((x) => (
                <tr key={x.id}>
                  <td dir="ltr">{x.username}</td>
                  <td>{dateTime(x.opened_at)}</td>
                  <td>{x.closed_at ? dateTime(x.closed_at) : <span className="badge">{x.is_stale ? t("shifts.forgotten") : t("shifts.openShift")}</span>}</td>
                  <td>{money(x.opening_cash)}</td>
                  <td>{money(x.cash_in)}</td>
                  <td>{money(x.cash_out)}</td>
                  <td>{money(Number(x.cash_refunds_out) - Number(x.cash_refunds_in))}</td>
                  <td>{money(x.expected_cash)}</td>
                  <td>{x.counted_cash === null ? "—" : money(x.counted_cash)}</td>
                  <td>{diffText(x.difference, t)}</td>
                  <td>
                    <button className="btn btn-sm" disabled={dl.busy} onClick={() => void dl.run(() => api.download(`/shifts/${x.id}/pdf`, `shift-${x.id}.pdf`))}>
                      PDF
                    </button>
                    {isManager && x.status === "open" && (
                      <button className="btn btn-sm" onClick={() => setClosing(x)}>
                        {t("shifts.adminClose")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{t("shifts.noShifts")}</Empty>
        )}
        <Pager list={list} />
      </div>
      {closing && (
        <AdminCloseDialog
          shift={closing}
          onClose={() => setClosing(null)}
          onDone={() => {
            setClosing(null);
            list.reload();
          }}
        />
      )}
    </>
  );
}
