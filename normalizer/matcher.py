"""Каскад сопоставления (§2 ТЗ): precision-first, останавливаемся на первой
уверенной ступени. Точное → синонимы → аббревиатура → лексический fuzzy →
семантика. Поверх — сужение кандидатов (§5) и доменные ловушки (§6)."""
from __future__ import annotations

from dataclasses import dataclass, field

from utils.text import clean_text

from . import traps as traps_mod
from .config import NormalizerConfig
from .embeddings import EmbeddingIndex
from .lexical import token_set_ratio
from .preprocess import preprocess


@dataclass(slots=True)
class ServiceRecord:
    """Запись целевого справочника (из repository.load_services())."""

    service_id: str
    service_name: str
    synonyms: list[str] = field(default_factory=list)
    category: str | None = None
    code: str | None = None              # внутренний код услуги (если есть в справочнике)
    tarificator_code: str | None = None  # код тарификатора (если есть)


@dataclass(slots=True)
class MatchResult:
    """Результат сопоставления. confidence/service_id = None, если не сопоставлено."""

    service_id: str | None
    confidence: float | None       # 0..1
    stage: str                     # code | exact | synonym | abbrev | fuzzy | semantic | none
    needs_review: bool = False     # попало в полосу ручной верификации
    matched_name: str | None = None  # для диагностики/логов


@dataclass(slots=True)
class _Candidate:
    service_id: str
    service_name: str       # исходное имя записи (для семантики и логов)
    norm: str               # нормализованный ключ для exact/fuzzy
    expanded: str           # нормализованный ключ с расшифрованными аббревиатурами
    traps: dict[str, str]
    category: str | None
    is_synonym: bool        # ключ пришёл из synonyms, а не из service_name


class Normalizer:
    """Сопоставляет сырое название услуги с записью справочника."""

    def __init__(
        self,
        services: list[ServiceRecord],
        config: NormalizerConfig | None = None,
    ) -> None:
        self.config = (config or NormalizerConfig()).validate()
        self._candidates: list[_Candidate] = []
        self._exact: dict[str, _Candidate] = {}
        self._synonym: dict[str, _Candidate] = {}
        self._by_code: dict[str, ServiceRecord] = {}
        self._build(services)

        self._embeddings = EmbeddingIndex(self.config.embedding_model) if self.config.use_embeddings else None
        if self._embeddings and self._embeddings.available:
            self._embeddings.build([c.service_name for c in self._candidates])
        else:
            self._embeddings = None

    @classmethod
    def from_xlsx(cls, path, config: NormalizerConfig | None = None) -> "Normalizer":
        """Собрать нормализатор из Excel-справочника (портир. из B).

        Колонки подбираются гибко по нескольким возможным заголовкам;
        service_id генерится через uuid5, если его нет в файле.
        """
        from .catalog import load_services_from_xlsx

        return cls(load_services_from_xlsx(path), config)

    # -- построение индекса ------------------------------------------------
    def _prep(self, text: object):
        return preprocess(
            text,
            abbreviations_path=str(self.config.abbreviations_path),
            stopwords_path=str(self.config.stopwords_path),
            use_lemmatization=self.config.use_lemmatization,
        )

    def _build(self, services: list[ServiceRecord]) -> None:
        for svc in services:
            for code in (svc.code, svc.tarificator_code):
                if code and str(code).strip():
                    self._by_code.setdefault(str(code).strip().lower(), svc)
            entries = [(svc.service_name, False)] + [(s, True) for s in (svc.synonyms or [])]
            for text, is_syn in entries:
                if not text or not str(text).strip():
                    continue
                pr = self._prep(text)
                if not pr.normalized_name:
                    continue
                cand = _Candidate(
                    service_id=svc.service_id,
                    service_name=svc.service_name,
                    norm=pr.normalized_name,
                    expanded=pr.expanded_name,
                    traps=pr.traps,
                    category=svc.category,
                    is_synonym=is_syn,
                )
                self._candidates.append(cand)
                table = self._synonym if is_syn else self._exact
                table.setdefault(pr.normalized_name, cand)
                # точное совпадение справочника по расшифрованной форме тоже индексируем
                self._exact.setdefault(pr.expanded_name, cand)

    # -- сужение кандидатов (blocking, §5) --------------------------------
    def _block(self, category: str | None) -> list[_Candidate]:
        if not category:
            return self._candidates
        key = category.strip().lower()
        subset = [c for c in self._candidates if (c.category or "").strip().lower() == key]
        return subset or self._candidates

    # -- основной API ------------------------------------------------------
    def match(
        self,
        raw_name: str,
        category: str | None = None,
        source_code: str | None = None,
    ) -> MatchResult:
        # Ступень 0: код услуги из источника — точнее любого текста (портир. из B).
        if source_code:
            hit = self._by_code.get(str(source_code).strip().lower())
            if hit is not None:
                return MatchResult(
                    hit.service_id, self.config.code_score, "code", False, hit.service_name
                )

        pr = self._prep(raw_name)
        if not pr.normalized_name:
            return MatchResult(None, None, "none")

        candidates = self._block(category)
        in_scope = {id(c) for c in candidates}

        # Ступень 1-2: точное совпадение ключа (service_name / synonyms)
        hit = self._exact.get(pr.normalized_name) or self._synonym.get(pr.normalized_name)
        if hit and id(hit) in in_scope:
            stage = "synonym" if hit.is_synonym else "exact"
            score = self.config.synonym_score if hit.is_synonym else self.config.exact_score
            return self._finalize(hit, score, stage, pr)

        # Ступень 3: аббревиатура → ключ (после расшифровки)
        if pr.abbrev_applied and pr.expanded_name != pr.normalized_name:
            hit = self._exact.get(pr.expanded_name) or self._synonym.get(pr.expanded_name)
            if hit and id(hit) in in_scope:
                return self._finalize(hit, self.config.abbrev_score, "abbrev", pr)

        # Ступень 4-5: fuzzy (+ семантика, если эмбеддинги активны)
        return self._score_candidates(pr, candidates)

    def _score_candidates(self, pr, candidates: list[_Candidate]) -> MatchResult:
        cfg = self.config
        sims = None
        if self._embeddings is not None:
            query = clean_text(pr.expanded_name or pr.normalized_name)
            # порядок sims совпадает с порядком self._candidates
            sims = self._embeddings.similarities(query)
        emb_pos = {id(c): i for i, c in enumerate(self._candidates)} if sims is not None else {}

        best: _Candidate | None = None
        best_score = 0.0
        best_stage = "fuzzy"
        for cand in candidates:
            lex = max(
                token_set_ratio(pr.normalized_name, cand.norm),
                token_set_ratio(pr.expanded_name, cand.expanded),
            ) if cfg.use_fuzzy else 0.0

            if sims is not None:
                cos = float(sims[emb_pos[id(cand)]])
                score = cfg.lexical_weight * lex + cfg.semantic_weight * cos
                stage = "semantic"
            else:
                score = lex
                stage = "fuzzy"

            if score > best_score:
                best, best_score, best_stage = cand, score, stage

        if best is None:
            return MatchResult(None, None, "none")
        return self._finalize(best, best_score, best_stage, pr)

    # -- ловушки + пороги --------------------------------------------------
    def _finalize(self, cand: _Candidate, score: float, stage: str, pr) -> MatchResult:
        if traps_mod.has_conflict(pr.traps, cand.traps):
            score *= self.config.trap_penalty
        score = round(min(score, 1.0), 3)
        cfg = self.config

        if score >= cfg.auto_threshold:
            return MatchResult(cand.service_id, score, stage, False, cand.service_name)
        if score <= cfg.unmatched_threshold:
            return MatchResult(None, None, "none", False, None)
        # между порогами — очередь ручной верификации
        return MatchResult(cand.service_id, score, stage, True, cand.service_name)

    # -- пост-обработка уже загруженных (Вариант B, §Интерфейс) -----------
    def run_over_unmatched(
        self,
        repository,
        *,
        limit: int | None = None,
        write: bool = True,
        write_review: bool = True,
    ) -> dict[str, int]:
        """Пройти price_item где service_id IS NULL и проставить совпадения.

        repository должен предоставлять iter_unmatched() и update_match().
        Возвращает счётчики: auto / review / unmatched / total.
        """
        stats = {"auto": 0, "review": 0, "unmatched": 0, "total": 0}
        for item in repository.iter_unmatched(limit=limit):
            stats["total"] += 1
            res = self.match(
                item["service_name_raw"],
                source_code=item.get("service_code_source"),
            )
            if res.service_id and not res.needs_review:
                stats["auto"] += 1
                if write:
                    repository.update_match(item["item_id"], res.service_id, res.confidence)
            elif res.service_id and res.needs_review:
                stats["review"] += 1
                if write and write_review:
                    repository.update_match(item["item_id"], res.service_id, res.confidence)
            else:
                stats["unmatched"] += 1
        return stats
