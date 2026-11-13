/** قاعدة محلية (SQLite): كاش المزامنة + طابور الأوردرات الأوفلاين. */
import * as SQLite from "expo-sqlite";

export const db = SQLite.openDatabaseSync("mozad.db");

export function initDb() {
  db.execSync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY, sku TEXT, name TEXT, unit TEXT,
      sale_price TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS customers (
      id INTEGER PRIMARY KEY, name TEXT, phone TEXT,
      credit_limit TEXT, price_list_id INTEGER, balance TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS price_list_items (
      price_list_id INTEGER, product_id INTEGER, unit_price TEXT,
      PRIMARY KEY (price_list_id, product_id)
    );
    CREATE TABLE IF NOT EXISTS pending_orders (
      client_ref TEXT PRIMARY KEY, payload TEXT NOT NULL,
      created_at TEXT NOT NULL, attempts INTEGER DEFAULT 0, last_error TEXT
    );
    CREATE TABLE IF NOT EXISTS synced_orders (
      order_id INTEGER PRIMARY KEY, client_ref TEXT, total TEXT,
      status TEXT, synced_at TEXT
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
  `);
}

export function getMeta(key: string): string | null {
  const rows = db.getAllSync("SELECT value FROM meta WHERE key = ?", [key]) as { value: string }[];
  return rows.length ? rows[0].value : null;
}

export function setMeta(key: string, value: string) {
  db.runSync("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [key, value]);
}

export interface ProductRow {
  id: number; sku: string; name: string; unit: string; sale_price: string;
}

export function upsertProducts(rows: (ProductRow & { updated_at: string })[]) {
  db.withTransactionSync(() => {
    for (const p of rows) {
      db.runSync(
        `INSERT INTO products (id, sku, name, unit, sale_price, updated_at) VALUES (?,?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET sku=excluded.sku, name=excluded.name, unit=excluded.unit,
         sale_price=excluded.sale_price, updated_at=excluded.updated_at`,
        [p.id, p.sku, p.name, p.unit, p.sale_price, p.updated_at]
      );
    }
  });
}

export function upsertCustomers(rows: any[]) {
  db.withTransactionSync(() => {
    for (const c of rows) {
      db.runSync(
        `INSERT INTO customers (id, name, phone, credit_limit, price_list_id, balance, updated_at)
         VALUES (?,?,?,?,?,?,?)
         ON CONFLICT(id) DO UPDATE SET name=excluded.name, phone=excluded.phone,
         credit_limit=excluded.credit_limit, price_list_id=excluded.price_list_id,
         balance=excluded.balance, updated_at=excluded.updated_at`,
        [c.id, c.name, c.phone ?? null, c.credit_limit ?? null, c.price_list_id ?? null, c.balance ?? "0", c.updated_at]
      );
    }
  });
}

export function upsertPriceListItems(items: any[]) {
  db.withTransactionSync(() => {
    for (const it of items) {
      db.runSync(
        `INSERT INTO price_list_items (price_list_id, product_id, unit_price) VALUES (?,?,?)
         ON CONFLICT(price_list_id, product_id) DO UPDATE SET unit_price=excluded.unit_price`,
        [it.price_list_id, it.product_id, it.unit_price]
      );
    }
  });
}

export function listProducts(term: string): ProductRow[] {
  if (term.trim()) {
    return db.getAllSync(
      "SELECT * FROM products WHERE name LIKE ? OR sku LIKE ? ORDER BY name LIMIT 300",
      [`%${term}%`, `%${term}%`]
    ) as ProductRow[];
  }
  return db.getAllSync("SELECT * FROM products ORDER BY name LIMIT 300") as ProductRow[];
}

export function listCustomers(term: string): any[] {
  if (term.trim()) {
    return db.getAllSync(
      "SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? ORDER BY name LIMIT 300",
      [`%${term}%`, `%${term}%`]
    );
  }
  return db.getAllSync("SELECT * FROM customers ORDER BY name LIMIT 300");
}

/** سعر فعلي للعرض: قائمة أسعار العميل إن وُجدت وإلا سعر البيع. */
export function priceFor(product: ProductRow, priceListId: number | null): string {
  if (priceListId) {
    const rows = db.getAllSync(
      "SELECT unit_price FROM price_list_items WHERE price_list_id = ? AND product_id = ?",
      [priceListId, product.id]
    ) as { unit_price: string }[];
    if (rows.length) return rows[0].unit_price;
  }
  return product.sale_price;
}

export function queueOrder(clientRef: string, payload: object) {
  db.runSync(
    "INSERT INTO pending_orders (client_ref, payload, created_at, attempts, last_error) VALUES (?,?,?,0,NULL)",
    [clientRef, JSON.stringify(payload), new Date().toISOString()]
  );
}

export function listPendingOrders(): { client_ref: string; payload: string; attempts: number; last_error: string | null }[] {
  return db.getAllSync("SELECT client_ref, payload, attempts, last_error FROM pending_orders ORDER BY created_at");
}

export function removePendingOrder(clientRef: string) {
  db.runSync("DELETE FROM pending_orders WHERE client_ref = ?", [clientRef]);
}

export function bumpPendingOrder(clientRef: string, error: string) {
  db.runSync(
    "UPDATE pending_orders SET attempts = attempts + 1, last_error = ? WHERE client_ref = ?",
    [error, clientRef]
  );
}

export function recordSyncedOrder(orderId: number, clientRef: string, total: string, status: string) {
  db.runSync(
    "INSERT OR REPLACE INTO synced_orders (order_id, client_ref, total, status, synced_at) VALUES (?,?,?,?,?)",
    [orderId, clientRef, total, status, new Date().toISOString()]
  );
}

export function listSyncedOrders(): any[] {
  return db.getAllSync("SELECT * FROM synced_orders ORDER BY synced_at DESC LIMIT 200");
}
