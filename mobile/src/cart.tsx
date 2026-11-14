/** سلة الأوردر الحالي — حالة عالمية بسيطة (Context) + العميل المختار. */
import React, { createContext, useContext, useMemo, useState } from "react";

export interface CartItem { product_id: number; name: string; unit: string; unit_price: number; quantity: number; }
export interface SelectedCustomer { id: number; name: string; }

interface CartCtx {
  items: CartItem[];
  add: (item: Omit<CartItem, "quantity">, qty?: number) => void;
  setQty: (product_id: number, qty: number) => void;
  remove: (product_id: number) => void;
  clear: () => void;
  total: number;
  customer: SelectedCustomer | null;
  setCustomer: (c: SelectedCustomer | null) => void;
}

const Ctx = createContext<CartCtx | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartItem[]>([]);
  const [customer, setCustomer] = useState<SelectedCustomer | null>(null);
  const value = useMemo<CartCtx>(() => {
    const total = items.reduce((s, it) => s + it.unit_price * it.quantity, 0);
    return {
      items,
      total,
      customer,
      setCustomer,
      add: (item, qty = 1) =>
        setItems((rows) => {
          const found = rows.find((r) => r.product_id === item.product_id);
          if (found) return rows.map((r) => (r.product_id === item.product_id ? { ...r, quantity: r.quantity + qty } : r));
          return [...rows, { ...item, quantity: qty }];
        }),
      setQty: (product_id, qty) =>
        setItems((rows) => (qty <= 0 ? rows.filter((r) => r.product_id !== product_id) : rows.map((r) => (r.product_id === product_id ? { ...r, quantity: qty } : r)))),
      remove: (product_id) => setItems((rows) => rows.filter((r) => r.product_id !== product_id)),
      clear: () => setItems([]),
    };
  }, [items, customer]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCart() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCart خارج CartProvider");
  return ctx;
}
