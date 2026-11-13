import { describe, it, expect } from "vitest";
import { discountedUnitPrice, money, num, balanceNote, roleLabel } from "./format";

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
  it("discountedUnitPrice applies line discount percent", () => {
    expect(discountedUnitPrice(100, 10)).toBe(90);
    expect(discountedUnitPrice("100", "25")).toBe(75);
    expect(discountedUnitPrice(33.5, 15)).toBe(28.48); // تقريب منزلتين
  });
  it("discountedUnitPrice clamps and tolerates bad input", () => {
    expect(discountedUnitPrice(100, 0)).toBe(100);
    expect(discountedUnitPrice(100, 100)).toBe(0);
    expect(discountedUnitPrice(100, 150)).toBe(0);   // فوق 100 → قص
    expect(discountedUnitPrice(100, -20)).toBe(100); // تحت 0 → قص
    expect(discountedUnitPrice(100, "abc")).toBe(100);
    expect(discountedUnitPrice(null, 10)).toBe(0);
  });
});
