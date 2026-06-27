# normalizer/ — нормализатор услуг (ТЗ 4.3)

Сопоставляет сырое название услуги из прайса с записью справочника `service`.
Реализует [docs/NORMALIZER_SPEC.md](../docs/NORMALIZER_SPEC.md): предобработку (§1),
каскад из 5 ступеней (§2), эмбеддинги (§3), два порога (§4), blocking (§5),
доменные ловушки (§6), оценочный стенд (§7), обратную связь (§8).

## Зависимости опциональны
Модуль работает на чистой стандартной библиотеке. Тяжёлые пакеты только
повышают точность и подхватываются автоматически, если установлены:

| пакет | ступень | без него |
|-------|---------|----------|
| `rapidfuzz` | лексический fuzzy (4) | фолбэк на `difflib` |
| `pymorphy3` | лемматизация (§1) | лёгкий стеммер окончаний |
| `sentence-transformers` + `numpy` | семантика (5) | ступень выключена |

## Использование

### Вариант A — на этапе загрузки (рекомендуется)
```python
import normalizer
res = normalizer.match("ОАК (1 кат.)", category="лаборатория")
# res.service_id / res.confidence / res.stage / res.needs_review
```
`normalizer.match()` лениво строит индекс из `repository.load_services()`.
После обновления справочника вызовите `normalizer.reset()`.

### Без БД (тесты, оффлайн)
```python
from normalizer import Normalizer, ServiceRecord
norm = Normalizer([ServiceRecord("s1", "Общий анализ крови", "лаборатория", ["ОАК"])])
norm.match("ОАК")
```

### Справочник из Excel
```python
from normalizer import Normalizer
norm = Normalizer.from_xlsx("services.xlsx")   # колонки подбираются гибко
```
Распознаёт заголовки (рус./англ.): название, категория, `Code`/`TarificatrCode`,
`service_id`, синонимы. Если `service_id` нет — генерится стабильный uuid5.

### Матч по коду услуги (ступень 0)
Если у позиции есть код источника и он совпадает с `code`/`tarificator_code`
записи справочника — это точнее любого текста, возвращается сразу:
```python
norm.match(raw_name, source_code=item.service_code_source)  # stage="code", conf=0.99
```
`run_over_unmatched` подставляет `service_code_source` автоматически. Индекс
кодов наполняется только если в `ServiceRecord` заданы коды (например, из
`from_xlsx`); в текущей БД-схеме `service` внутреннего кода нет, поэтому при
загрузке из repository ступень 0 просто спит.

### Вариант B — пост-обработка уже загруженных
```python
import normalizer, repository
norm = normalizer.build_from_repository(repository)
stats = norm.run_over_unmatched(repository)   # {'auto':.., 'review':.., 'unmatched':..}
```

## Пороги
`auto >= 0.90` → автосопоставление; `<= 0.70` → `service_id = NULL` (очередь
`/unmatched`); между — `needs_review=True` (очередь верификации). Меняются через
`NormalizerConfig` или env: `NORM_AUTO_THRESHOLD`, `NORM_UNMATCHED_THRESHOLD`,
`NORM_LEXICAL_WEIGHT`, `NORM_SEMANTIC_WEIGHT`, `NORM_EMBEDDING_MODEL`.

## Обратная связь (§8)
Подтверждение оператора (`POST /verify`) → `repository.add_synonym(service_id, raw)`
дописывает синоним в `service.synonyms` — система улучшается со временем.

## Оценочный стенд (§7)
```bash
python -m eval.normalizer_eval                 # на образце eval/*.json|csv
python -m eval.normalizer_eval --auto 0.85     # покрутить пороги
```
Боевой gold-набор — 200–300 пар «raw → service_id» в `eval/gold_sample.csv`
(сейчас лежит небольшой образец, чтобы стенд работал из коробки).

## Пополняемые словари
- `abbreviations.json` — аббревиатура → расшифровка;
- `stopwords.json` — стоп-слова (убираются только как самостоятельные токены).
