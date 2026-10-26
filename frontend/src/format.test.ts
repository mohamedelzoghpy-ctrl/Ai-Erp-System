import { describe, it, expect } from "vitest";
import { money, num, balanceNote, ROLE_LABEL } from "./format";

describe("format helpers", () => {
  it("money formats with 2 decimals and currency", () => {
    expect(money(12.5)).toMatch(/12\.50/);
    expect(money(12.5)).toContain("ج.م");
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
  it("ROLE_LABEL has all roles", () => {
    expect(ROLE_LABEL.admin).toBe("مدير عام");
    expect(ROLE_LABEL.staff).toBe("موظف");
  });
});