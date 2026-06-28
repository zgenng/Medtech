-- 003 · Целевой справочник услуг (ТЗ 2.2 / 3.4)
-- Поля из xlsx-справочника организаторов: Специальность, Code, Name_ru, TarificatrCode.
-- Идемпотентно: можно применять к уже расширенной БД.

ALTER TABLE service ADD COLUMN IF NOT EXISTS specialty         TEXT;  -- "Специальность" (напр. Акушер-гинеколог)
ALTER TABLE service ADD COLUMN IF NOT EXISTS code              TEXT;  -- "Code" из справочника
ALTER TABLE service ADD COLUMN IF NOT EXISTS tarificator_code  TEXT;  -- "TarificatrCode" (напр. A02.004.000)

-- Поиск по специальности (блокинг при сопоставлении) и по коду тарификатора.
CREATE INDEX IF NOT EXISTS idx_service_specialty  ON service(specialty);
CREATE INDEX IF NOT EXISTS idx_service_tarif       ON service(tarificator_code);

-- Уникальность имени услуги — ключ апсерта загрузчика справочника.
-- (создаётся в schema.sql; здесь — страховка для старых БД)
CREATE UNIQUE INDEX IF NOT EXISTS uq_service_name ON service(service_name);
