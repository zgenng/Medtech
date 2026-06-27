-- Тестовые данные, чтобы сразу проверить эндпоинты до готовых парсеров.
-- Применение:  psql -h localhost -p 5433 -U arman -d arman -f seed.sql

-- Услуги справочника
INSERT INTO service (service_name, synonyms, category) VALUES
  ('Общий анализ крови', '["ОАК","клинический анализ крови","CBC"]', 'лаборатория'),
  ('УЗИ брюшной полости', '["ультразвуковое исследование брюшной полости","UZI"]', 'диагностика'),
  ('Консультация терапевта', '["приём терапевта","осмотр терапевта"]', 'консультация')
ON CONFLICT DO NOTHING;

-- Партнёры
INSERT INTO partner (name, city, contact_phone) VALUES
  ('Клиника Самал', 'Алматы', '+7 727 000 0000'),
  ('Медцентр Астана', 'Астана', '+7 717 000 0000')
ON CONFLICT DO NOTHING;

-- Документ + позиции (привязываем к первой клинике и услуге)
WITH p AS (SELECT partner_id FROM partner WHERE name = 'Клиника Самал' LIMIT 1),
     d AS (
       INSERT INTO price_document (partner_id, file_name, file_format, parse_status, effective_date)
       SELECT partner_id, 'samal_2025.xlsx', 'xlsx', 'done', CURRENT_DATE FROM p
       RETURNING doc_id, partner_id
     ),
     s_oak AS (SELECT service_id FROM service WHERE service_name = 'Общий анализ крови' LIMIT 1)
INSERT INTO price_item
   (doc_id, partner_id, service_name_raw, service_id, price_resident_kzt, price_nonresident_kzt, effective_date, is_verified, match_confidence)
SELECT d.doc_id, d.partner_id, 'ОАК (клинический анализ крови)', s_oak.service_id, 3500, 4200, CURRENT_DATE, TRUE, 0.97
FROM d, s_oak
UNION ALL
-- несопоставленная позиция (service_id NULL) — попадёт в очередь /unmatched
SELECT d.doc_id, d.partner_id, 'Анализ крови развёрнутый', NULL, 5000, 6000, CURRENT_DATE, FALSE, NULL
FROM d;
