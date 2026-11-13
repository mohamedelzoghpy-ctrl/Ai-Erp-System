/** اختبار منطق الصلاحيات can(): نجمة الكل · any-of · بلا صلاحية — عبر AuthProvider حقيقي بـ API وهمي. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth";
import type { User } from "./types";

// وهم وحدة الـ api: جلسة موجودة بمستخدم ذي صلاحيات محددة
vi.mock("./api", () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve({
        id: 1,
        username: "tester",
        role: "staff",
        is_platform_admin: false,
        permissions: ["sales.view", "taxes.vat.view"],
      } satisfies Partial<User> as User),
    ),
    login: vi.fn(),
    post: vi.fn(),
  },
  getToken: vi.fn(() => "fake-token"),
  setToken: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  setLicenseExpiredHandler: vi.fn(),
}));

function Probe({ codes }: { codes: string[] }) {
  const { can, isManager, isAdmin, isPlatformAdmin } = useAuth();
  return (
    <div>
      <span data-testid="can">{String(can(...codes))}</span>
      <span data-testid="manager">{String(isManager)}</span>
      <span data-testid="admin">{String(isAdmin)}</span>
      <span data-testid="platform">{String(isPlatformAdmin)}</span>
    </div>
  );
}

beforeEach(() => {
  cleanup();
});

async function renderWithAuth(codes: string[]) {
  render(
    <AuthProvider>
      <Probe codes={codes} />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("can").textContent).toBeDefined());
}

describe("can() — البوابة في الواجهة", () => {
  it("صلاحية موجودة → true", async () => {
    await renderWithAuth(["sales.view"]);
    expect(screen.getByTestId("can")).toHaveTextContent("true");
  });

  it("any-of: واحدة من عدة أكواد تكفي", async () => {
    await renderWithAuth(["nothing.here", "taxes.vat.view"]);
    expect(screen.getByTestId("can")).toHaveTextContent("true");
  });

  it("بلا صلاحية → false", async () => {
    await renderWithAuth(["eta.device.manage"]);
    expect(screen.getByTestId("can")).toHaveTextContent("false");
  });

  it("موظف (staff) ليس مديرًا ولا أدمن ولا أدمن منصة", async () => {
    await renderWithAuth(["sales.view"]);
    expect(screen.getByTestId("manager")).toHaveTextContent("false");
    expect(screen.getByTestId("admin")).toHaveTextContent("false");
    expect(screen.getByTestId("platform")).toHaveTextContent("false");
  });
});
