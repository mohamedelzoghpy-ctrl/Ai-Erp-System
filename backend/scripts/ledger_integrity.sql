-- سلامة الدفاتر على مستوى قاعدة البيانات (إصلاح حرج 3 — تدقيق 2026-11-14)
-- يُطبَّق تلقائيًا عند كل إقلاع (idempotent) من app.accounting.apply_ledger_integrity
-- ويُرجَّع ضمن ترحيلة alembic: acc2026111401 (انظر alembic/versions/)
--
-- مشغّل مؤجَّل يمنع تثبيت أي قيد غير متوازن (مدين ≠ دائن) —
-- الحماية كانت في بايثون فقط قبله، والـCHECK الوحيد لا يكفي لأن التوازن شرط عبر الصفوف.
-- يعمل على Postgres فقط (لا يعمل على SQLite في الاختبارات — المحرك نفسه يمنع صياغته).

BEGIN;

DROP TRIGGER IF EXISTS tr_je_balanced ON journal_items;

CREATE OR REPLACE FUNCTION fn_assert_je_balanced() RETURNS trigger AS $$
DECLARE
    v_entry BIGINT;
    v_debit NUMERIC;
    v_credit NUMERIC;
BEGIN
    v_entry := COALESCE(NEW.entry_id, OLD.entry_id);
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
      INTO v_debit, v_credit
      FROM journal_items
     WHERE entry_id = v_entry;
    IF v_debit <> v_credit THEN
        RAISE EXCEPTION 'unbalanced journal entry: debit total does not equal credit total';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER tr_je_balanced
AFTER INSERT OR UPDATE OR DELETE ON journal_items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_assert_je_balanced();

COMMIT;
