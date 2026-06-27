-- ============================================================
-- Миграция 001 — идемпотентность загрузчика (Этап 1 PIPELINE_PLAN)
-- ============================================================
-- Применение:  psql "$DATABASE_URL" -f sql/migrations/001_loader_idempotency.sql
--
-- Закрывает два пробела, из-за которых повторный прогон плодил дубли:
--   1) NULL в effective_date: обычный UNIQUE считает NULL != NULL, поэтому
--      позиции без даты не конфликтовали и дублировались при каждом прогоне.
--   2) У price_document не было ключа дедупа — каждый прогон вставлял новый
--      документ даже для того же файла.
-- ============================================================

-- 1. Дедуп позиций с устойчивостью к NULL-дате.
--    COALESCE-сентинел => (partner, name, NULL) и (partner, name, NULL)
--    считаются дубликатом. Дата '0001-01-01' в прайсах не встречается.
DROP INDEX IF EXISTS uq_item_dedup;
CREATE UNIQUE INDEX IF NOT EXISTS uq_item_dedup
    ON price_item (
        partner_id,
        service_name_raw,
        (COALESCE(effective_date, DATE '0001-01-01'))
    )
    WHERE is_active = TRUE;

-- 2. Идемпотентность документа: один и тот же файл одной клиники = один документ.
--    Ключ (partner_id, file_name) стабилен между прогонами, в т.ч. при повторной
--    распаковке ZIP во временную папку (file_path там меняется, file_name — нет).
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_file
    ON price_document (partner_id, file_name);
