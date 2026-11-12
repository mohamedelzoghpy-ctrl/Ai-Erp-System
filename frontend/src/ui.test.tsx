/** اختبارات المكوّنات المشتركة (ui.tsx) — أول شبكة أمان للواجهة. */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nProvider } from "./i18n";
import {
  Alert,
  Empty,
  Loading,
  PageHeader,
  StatusBadge,
  ActiveBadge,
  PaymentBadge,
  ProductThumb,
} from "./ui";
import type { Product } from "./types";

const renderUI = (ui: React.ReactNode) => render(<I18nProvider>{ui}</I18nProvider>);

describe("Alert", () => {
  it("يرسل رسالة خطأ بدور alert", () => {
    renderUI(<Alert>فشل الاتصال</Alert>);
    expect(screen.getByRole("alert")).toHaveTextContent("فشل الاتصال");
  });
  it("رسالة معلومات بدور status", () => {
    renderUI(<Alert kind="info">تم الحفظ</Alert>);
    expect(screen.getByRole("status")).toHaveTextContent("تم الحفظ");
  });
  it("بلا محتوى → لا شيء في الصفحة", () => {
    const { container } = renderUI(<Alert>{null}</Alert>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Loading / Empty / PageHeader", () => {
  it("Loading يعرض نص التحميل", () => {
    renderUI(<Loading />);
    expect(screen.getByText("جارٍ التحميل…")).toBeInTheDocument();
  });
  it("Empty يعرض الرسالة", () => {
    renderUI(<Empty>لا بيانات</Empty>);
    expect(screen.getByText("لا بيانات")).toBeInTheDocument();
  });
  it("PageHeader يعرض العنوان والإجراءات", () => {
    renderUI(
      <PageHeader title="العملاء">
        <button>إضافة</button>
      </PageHeader>,
    );
    expect(screen.getByRole("heading", { name: "العملاء" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "إضافة" })).toBeInTheDocument();
  });
});

describe("شارات الحالة", () => {
  it("ActiveBadge: نشط/موقوف", () => {
    const { rerender } = renderUI(<ActiveBadge active />);
    expect(screen.getByText("نشط")).toBeInTheDocument();
    rerender(
      <I18nProvider>
        <ActiveBadge active={false} />
      </I18nProvider>,
    );
    expect(screen.getByText("موقوف")).toBeInTheDocument();
  });
  it("PaymentBadge: مسددة/سداد جزئي/غير مسددة/فارغة", () => {
    const { rerender, container } = renderUI(<PaymentBadge status="paid" />);
    expect(screen.getByText("مسددة")).toBeInTheDocument();
    rerender(<I18nProvider><PaymentBadge status="partial" /></I18nProvider>);
    expect(screen.getByText("سداد جزئي")).toBeInTheDocument();
    rerender(<I18nProvider><PaymentBadge status="unpaid" /></I18nProvider>);
    expect(screen.getByText("غير مسددة")).toBeInTheDocument();
    rerender(<I18nProvider><PaymentBadge status={null} /></I18nProvider>);
    expect(container.textContent).toContain("—");
  });
  it("StatusBadge يعرض شارة الحالة", () => {
    renderUI(<StatusBadge status="confirmed" />);
    expect(document.querySelector(".badge-confirmed")).not.toBeNull();
  });
});

describe("ProductThumb", () => {
  const base = { id: 1, name: "صنف" } as Product;
  it("بلا صورة → عنصر بديل 📦", () => {
    const { container } = renderUI(<ProductThumb product={base} />);
    expect(container.querySelector(".product-thumb-empty")).not.toBeNull();
  });
  it("صورة مرفوعة على الخادم → img لمسار /api/products", () => {
    const { container } = renderUI(
      <ProductThumb product={{ ...base, image_uploaded: true } as Product} />,
    );
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "/api/products/1/image");
  });
  it("فشل تحميل الصورة → يعود للبديل 📦", () => {
    const { container } = renderUI(
      <ProductThumb product={{ ...base, image_uploaded: true } as Product} />,
    );
    fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector(".product-thumb-empty")).not.toBeNull();
  });
});

// استخدام vi في الملف يضمن ترتيب الاستيرادات الصحيح لـ vitest
void vi;
