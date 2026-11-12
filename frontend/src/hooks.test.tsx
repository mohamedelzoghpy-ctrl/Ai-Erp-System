/** اختبارات الـ hooks المشتركة: useFetch (جلب/خطأ/إعادة) وuseAction (busy/error). */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useFetch, useAction } from "./hooks";

describe("useFetch", () => {
  it("يجلب البيانات وينهي التحميل", async () => {
    const fn = vi.fn(() => Promise.resolve([1, 2, 3]));
    const { result } = renderHook(() => useFetch<number[]>(fn, "k1"));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual([1, 2, 3]);
    expect(result.current.error).toBeNull();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("يلتقط رسالة الخطأ من الوعد المرفوض", async () => {
    const { result } = renderHook(() =>
      useFetch(() => Promise.reject(new Error("انقطع الاتصال")), "k2"),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("انقطع الاتصال");
  });

  it("reload يعيد الجلب مرة أخرى", async () => {
    const fn = vi.fn(() => Promise.resolve("v1"));
    const { result } = renderHook(() => useFetch<string>(fn, "k3"));
    await waitFor(() => expect(result.current.data).toBe("v1"));
    act(() => {
      result.current.reload();
    });
    await waitFor(() => expect(fn).toHaveBeenCalledTimes(2));
    expect(result.current.data).toBe("v1");
  });
});

describe("useAction", () => {
  it("run يعيد قيمة الدالة ويهبط busy في النهاية", async () => {
    const { result } = renderHook(() => useAction());
    expect(result.current.busy).toBe(false);
    await act(async () => {
      const v = await result.current.run(() => Promise.resolve("تم"));
      expect(v).toBe("تم");
    });
    expect(result.current.busy).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("يلتقط الخطأ ويضبطه بدل رميه", async () => {
    const { result } = renderHook(() => useAction());
    await act(async () => {
      await result.current.run(() => Promise.reject(new Error("مرفوض")));
    });
    expect(result.current.busy).toBe(false);
    expect(result.current.error).toBe("مرفوض");
  });

  it("setError يفرغ الخطأ يدويًا", async () => {
    const { result } = renderHook(() => useAction());
    await act(async () => {
      await result.current.run(() => Promise.reject(new Error("x")));
    });
    act(() => result.current.setError(null));
    expect(result.current.error).toBeNull();
  });
});
