import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api";
import { useFetch } from "../hooks";
import type { Company } from "../types";
import { Alert, Empty, Loading, PageHeader } from "../ui";

export default function SwitchCompany() {
  const { isPlatformAdmin } = useAuth();
  const navigate = useNavigate();
  const companies = useFetch(
    () => (isPlatformAdmin ? api.get<Company[]>("/platform/companies") : api.get<Company[]>("/auth/companies")),
    "switch-companies",
  );

  const switchTo = async (id: number) => {
    try {
      await api.post("/auth/switch-company", { company_id: id });
      window.location.href = "/";
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader title="اختيار الشركة" />
      <Alert>{companies.error}</Alert>
      {companies.loading && !companies.data ? <Loading /> : companies.data?.length ? (
        <div className="card table-wrap">
          <table>
            <thead><tr><th>الشركة</th><th>الرمز</th><th>الحالة</th><th /></tr></thead>
            <tbody>{companies.data.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td><td dir="ltr">{c.code}</td><td>{c.is_active ? "active" : "inactive"}</td>
                <td className="actions">
                  <button className="btn btn-sm btn-primary" onClick={() => void switchTo(c.id)}>اختيار</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <Empty>لا توجد شركات.</Empty>}
      <button className="btn" onClick={() => navigate(-1)} style={{ marginTop: 12 }}>رجوع</button>
    </>
  );
}
