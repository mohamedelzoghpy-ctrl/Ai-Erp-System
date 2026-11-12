import { describe, it, expect } from "vitest";
import { money, num, balanceNote, roleLabel } from "./format";

describe("format helpers", () => {
  it("money formats with 2 decimals and currency", () => {
    expect(money(12.5)).toMatch(/12\.50/);
    expect(money(12.5)).toContain("ج.م"); // العربية الافتراضية
    expect(money(null)).toContain("0.00");
  });
  it("num formats integers", () => {
    expect(num(1000)).toBeTruthy();
  });
  it("balanceNote describes customer debt", () => {
    expect(balanceNote("customer", 5)).toBe("مستحق على العميل");
    expect(balanceNote("customer", -3)).toBe("رصيد دائن للعميل");
    expect(balanceNote("customer", 0)).toBe("مسدّد");
  });
  it("english labels when lang=en", () => {
    expect(balanceNote("customer", 5, "en")).toBe("Due from customer");
    expect(roleLabel("admin", "en")).toBe("Admin");
    expect(roleLabel("staff")).toBe("موظف");
  });
});
