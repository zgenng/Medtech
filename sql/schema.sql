-- ============================================================
-- MedArchive — схема базы данных (PostgreSQL)
-- Кейс 2: обработка архива прайсов клиник-партнёров
-- ============================================================
-- Применение:  psql -h localhost -p 5433 -U arman -d arman -f schema.sql
-- ============================================================

-- Расширения --------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- нечёткий/полнотекстовый поиск

-- ENUM-типы ---------------------------------------------------
DO $$ BEGIN
    CREATE TYPE file_format_t AS ENUM ('pdf', 'docx', 'xlsx', 'scan_pdf');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE parse_status_t AS ENUM ('pending', 'processing', 'done', 'error', 'needs_review');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE currency_t AS ENUM ('KZT', 'USD', 'RUB');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================
-- 3.4  Услуга справочника (Service) — целевой справочник
-- ============================================================
CREATE TABLE IF NOT EXISTS service (
    service_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name  TEXT NOT NULL,
    synonyms      JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["синоним1", "синоним2"]
    category      TEXT,                                 -- лаборатория / диагностика / консультация / процедура
    icd_code      TEXT,                                 -- код по МКБ (опционально)
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

-- ============================================================
-- 3.1  Партнёр (Partner) — клиника
-- ============================================================
CREATE TABLE IF NOT EXISTS partner (
    partner_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name           TEXT NOT NULL,
    city           TEXT,
    address        TEXT,
    bin            VARCHAR(12),               -- БИН (опционально, для дедупликации)
    contact_email  TEXT,
    contact_phone  TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 3.2  Прайс-документ (PriceDocument)
-- ============================================================
CREATE TABLE IF NOT EXISTS price_document (
    doc_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    partner_id     UUID REFERENCES partner(partner_id) ON DELETE SET NULL,
    file_name      TEXT NOT NULL,
    file_format    file_format_t,
    effective_date DATE,                       -- дата вступления прайса в силу
    parsed_at      TIMESTAMPTZ,
    parse_status   parse_status_t NOT NULL DEFAULT 'pending',
    parse_log      TEXT,
    raw_content    TEXT,                        -- сырой извлечённый текст (для аудита)
    file_path      TEXT,                        -- путь к сохранённому оригиналу (не удаляется)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 3.3  Позиция прайса (PriceItem)
-- ============================================================
CREATE TABLE IF NOT EXISTS price_item (
    item_id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_id                UUID REFERENCES price_document(doc_id) ON DELETE CASCADE,
    partner_id            UUID REFERENCES partner(partner_id) ON DELETE SET NULL,  -- денормализовано для скорости
    service_name_raw      TEXT NOT NULL,        -- название как в документе
    service_code_source   TEXT,                 -- код услуги из источника (если есть)
    service_id            UUID REFERENCES service(service_id) ON DELETE SET NULL,  -- нормализованная услуга (nullable)
    price_resident_kzt    NUMERIC(14,2),
    price_nonresident_kzt NUMERIC(14,2),
    price_original        NUMERIC(14,2),
    currency_original     currency_t DEFAULT 'KZT',
    is_verified           BOOLEAN NOT NULL DEFAULT FALSE,
    verification_note     TEXT,
    match_confidence      NUMERIC(4,3),         -- уверенность автосопоставления 0..1
    effective_date        DATE,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,  -- актуальная версия цены
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Индексы
-- ============================================================
-- Поиск партнёров по услуге и наоборот
CREATE INDEX IF NOT EXISTS idx_item_service   ON price_item(service_id);
CREATE INDEX IF NOT EXISTS idx_item_partner   ON price_item(partner_id);
CREATE INDEX IF NOT EXISTS idx_item_doc       ON price_item(doc_id);
CREATE INDEX IF NOT EXISTS idx_item_active     ON price_item(is_active);
-- Очередь несопоставленных (service_id IS NULL)
CREATE INDEX IF NOT EXISTS idx_item_unmatched ON price_item(service_id) WHERE service_id IS NULL;
-- Статус обработки документов (дашборд/очередь)
CREATE INDEX IF NOT EXISTS idx_doc_status     ON price_document(parse_status);
CREATE INDEX IF NOT EXISTS idx_doc_partner    ON price_document(partner_id);
-- Нечёткий поиск по названиям (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_item_raw_trgm  ON price_item USING gin (service_name_raw gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_service_name_trgm ON service USING gin (service_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_partner_city   ON partner(city);

-- ============================================================
-- Уникальность для дедупликации позиций
-- (та же клиника + та же услуга + та же дата = дубликат)
-- ============================================================
CREATE UNIQUE INDEX IF NOT EXISTS uq_item_dedup
    ON price_item(partner_id, service_name_raw, effective_date)
    WHERE is_active = TRUE;
