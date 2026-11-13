/**
 * طباعة حرارية ESC/POS عبر WebUSB — بدون أي مكتبة خارجية.
 *
 * العربية تُرسم على canvas (المتصفح يقوم بالتشكيل والاتجاه تلقائياً) ثم
 * تُحوَّل إلى صورة أحادية اللون وتُطبع بأمر raster (GS v 0) — الطريقة
 * الوحيدة الموثوقة للعربية على طابعات 58/80mm.
 *
 * المتصفح: Chrome/Edge فقط (WebUSB) — وبإيماءة مستخدم (زر).
 * العرض: 80mm = 576 نقطة (48 بايت/سطر) · 58mm = 384 نقطة.
 */

export interface ThermalLine {
  left?: string;   // يسار السطر (LTR — أكواد/كميات)
  right?: string;  // يمين السطر (RTL — أسماء)
  center?: string; // سطر متمركز (عناوين)
  bold?: boolean;
  big?: boolean;   // عنوان كبير
  divider?: boolean;
}

const WIDTH = 576; // 80mm
const MARGIN = 8;

/** يبني canvas الإيصال ويعيده — منفصل عن الإرسال ليكون قابل للاختبار والمعاينة. */
export function renderReceiptCanvas(lines: ThermalLine[], footer?: string): HTMLCanvasElement {
  const scale = 2; // نقاط الپرنتر خشنة — خط 2x يظهر بحجم مقروء
  const lineHeight = 30 * scale;
  const bigHeight = 40 * scale;
  const pad = 6 * scale;

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = `${16 * scale}px Tahoma, Arial, sans-serif`;
  const dir = "rtl";

  // قياس الارتفاع أولاً
  let height = pad * 2;
  for (const l of lines) {
    if (l.divider) height += lineHeight / 2;
    else if (l.big || l.center) height += bigHeight;
    else height += lineHeight;
  }
  if (footer) height += bigHeight + lineHeight;
  canvas.width = WIDTH;
  canvas.height = Math.ceil(height);

  // خلفية بيضاء + نص أسود (الطابعة تطبع الأسود)
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#000000";
  ctx.textBaseline = "middle";
  ctx.direction = dir;

  let y = pad;
  for (const l of lines) {
    if (l.divider) {
      ctx.fillRect(MARGIN, y + lineHeight / 4, WIDTH - MARGIN * 2, 2 * scale);
      y += lineHeight / 2;
      continue;
    }
    const size = l.big ? 22 * scale : l.bold ? 17 * scale : 16 * scale;
    ctx.font = `${l.bold ? "bold " : ""}${size}px Tahoma, Arial, sans-serif`;
    if (l.center !== undefined || l.big) {
      ctx.textAlign = "center";
      ctx.fillText(l.center ?? l.right ?? "", WIDTH / 2, y + (l.big ? bigHeight : lineHeight) / 2);
    } else if (l.left !== undefined && l.right !== undefined) {
      ctx.textAlign = "right";
      ctx.fillText(l.right, WIDTH - MARGIN, y + lineHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(l.left, MARGIN, y + lineHeight / 2);
    } else if (l.right !== undefined) {
      ctx.textAlign = "right";
      ctx.fillText(l.right, WIDTH - MARGIN, y + lineHeight / 2);
    } else if (l.left !== undefined) {
      ctx.textAlign = "left";
      ctx.fillText(l.left, MARGIN, y + lineHeight / 2);
    }
    y += l.big ? bigHeight : lineHeight;
  }
  if (footer) {
    ctx.font = `${14 * scale}px Tahoma, Arial, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText(footer, WIDTH / 2, y + bigHeight / 2);
  }
  return canvas;
}

/** يحول canvas إلى بايتات ESC/POS كاملة (init + صورة raster + قطع). */
export function canvasToEscPos(canvas: HTMLCanvasElement, cut = true): Uint8Array {
  const w = canvas.width;
  const h = canvas.height;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.getImageData(0, 0, w, h).data;

  // عرض البايتات = 576/8 = 72
  const rowBytes = Math.ceil(w / 8);
  const bytes: number[] = [];
  const push = (...b: number[]) => bytes.push(...b);

  push(0x1b, 0x40); // ESC @ — تهيئة
  push(0x1b, 0x74, 0x00); // codepage

  // GS v 0 — raster bit image: m=0 (normal), xL xH yL yH بترتيب صغير
  push(0x1d, 0x76, 0x30, 0x00);
  push(rowBytes & 0xff, (rowBytes >> 8) & 0xff, h & 0xff, (h >> 8) & 0xff);

  // كل سطر: بت = 0 يعني أسود (الطابعة تطبع حيث البت المسدود)
  for (let y = 0; y < h; y++) {
    const row = new Array(rowBytes).fill(0);
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      // عتبة: أغمق من 128 = حبر
      const alpha = img[i + 3];
      const lum = 0.299 * img[i] + 0.587 * img[i + 1] + 0.114 * img[i + 2];
      if (alpha > 127 && lum < 128) {
        row[x >> 3] |= 0x80 >> (x & 7);
      }
    }
    bytes.push(...row);
  }

  if (cut) {
    push(0x0a, 0x0a); // تغذية سطرين قبل القطع
    push(0x1d, 0x56, 0x42, 0x00); // GS V 66 0 — قطع جزئي
  }
  return new Uint8Array(bytes);
}

export interface UsbPrinter {
  device: any; // USBDevice — WebUSB غير مضمن في أنواع TS القياسية هنا
  endpointNumber: number;
}

/** يطلب اختيار طابعة USB ويجهزها — يجب استدعاؤها بإيماءة مستخدم (زر). */
export async function connectThermalPrinter(): Promise<UsbPrinter> {
  const usb = (navigator as any).usb;
  if (!usb) throw new Error("المتصفح لا يدعم WebUSB — استخدم Chrome/Edge، أو اطبع PDF");
  const device = await usb.requestDevice({ filters: [] }); // المُستخدم يختار الطابعة من القائمة
  await device.open();
  if (device.configuration === null) await device.selectConfiguration(1);
  // ابحث عن واجهة طباعة (class 7) أو أول واجهة بنقطة OUT
  let ifaceNumber = 0;
  let endpointNumber = 1;
  let found = false;
  for (const iface of device.configuration.interfaces) {
    for (const alt of iface.alternates) {
      const out = alt.endpoints.find((e: any) => e.direction === "out");
      if (out && (alt.interfaceClass === 7 || !found)) {
        ifaceNumber = iface.interfaceNumber;
        endpointNumber = out.endpointNumber;
        found = true;
      }
    }
  }
  await device.claimInterface(ifaceNumber);
  return { device, endpointNumber };
}

/** يرسل البيانات على شكل حزم (حجم النقل القياسي 512/64). */
export async function sendToPrinter(printer: UsbPrinter, data: Uint8Array) {
  const CHUNK = 512;
  for (let offset = 0; offset < data.length; offset += CHUNK) {
    await printer.device.transferOut(printer.endpointNumber, data.subarray(offset, offset + CHUNK));
  }
}

/** الطباعة الكاملة بإيماءة واحدة: اتصال (اختيار) + رسم + إرسال + قطع. */
export async function printThermal(lines: ThermalLine[], footer?: string): Promise<void> {
  const canvas = renderReceiptCanvas(lines, footer);
  const data = canvasToEscPos(canvas);
  const printer = await connectThermalPrinter();
  try {
    await sendToPrinter(printer, data);
  } finally {
    try { await printer.device.close(); } catch { /* لا يعطل */ }
  }
}
