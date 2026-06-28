/* MedArchive — консоль оператора. Чистый JS, без зависимостей. */
"use strict";

// Адрес API. По умолчанию — тот же origin (когда UI раздаёт сам FastAPI).
// Если страница открыта иначе (preview-панель, file://, другой порт) — берём
// ?api=… из URL, либо пробуем localhost:8000 / :8011 (см. resolveApi()).
const PARAM_API = new URLSearchParams(location.search).get("api");
let API = (PARAM_API ?? (location.protocol === "file:" ? "http://localhost:8000" : "")).replace(/\/$/, "");

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

async function api(path, opts) {
  let res;
  try {
    res = await fetch(API + path, opts);
  } catch (e) {
    // fetch упал до ответа — сервер недоступен (не запущен / не тот origin).
    const err = new Error("сервер не отвечает");
    err.network = true;
    throw err;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    const err = new Error(detail);
    err.status = res.status;   // сервер ответил, но с ошибкой (напр. 500 — проблема БД на бэкенде)
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// ── Утилиты форматирования ─────────────────────────────
const fmtMoney = (v) =>
  v == null ? null : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v);

function priceCell(resident, nonresident, best = false) {
  if (resident == null && nonresident == null) return `<span class="muted">—</span>`;
  const r = resident != null ? `<span class="price${best ? " best" : ""}">${fmtMoney(resident)}<span class="cur">₸</span></span>` : "";
  const n = nonresident != null ? `<div class="price muted" style="font-size:12px">нерезидент ${fmtMoney(nonresident)} ₸</div>` : "";
  return (r || `<span class="muted">—</span>`) + n;
}

function fmtDate(d) {
  if (!d) return "—";
  try { return new Date(d).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return d; }
}

// Сигнатурный измеритель уверенности (trgm 0..1)
function meter(score) {
  if (score == null) return `<span class="muted" style="font-family:var(--font-mono);font-size:12px">— не оценено</span>`;
  const on = Math.max(0, Math.min(5, Math.round(score * 5)));
  const mod = score >= 0.85 ? "" : score >= 0.6 ? " meter--warn" : " meter--low";
  const segs = Array.from({ length: 5 }, (_, i) =>
    `<span class="meter-seg${i < on ? " on" : ""}"></span>`).join("");
  return `<span class="meter${mod}"><span class="meter-bars">${segs}</span><span class="meter-val">${(score * 100).toFixed(0)}%</span></span>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ── Тосты ──────────────────────────────────────────────
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<span>${kind === "ok" ? "✓" : kind === "err" ? "✕" : "ℹ"}</span><span>${esc(msg)}</span>`;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(() => el.remove(), 300); }, 3200);
}

// ── Навигация по видам ─────────────────────────────────
const loaders = {};
function show(view) {
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.dataset.view === view));
  location.hash = view;
  loaders[view]?.();
}
$("#nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".nav-item");
  if (btn) show(btn.dataset.view);
});

// ── Дашборд ────────────────────────────────────────────
loaders.dashboard = async () => {
  let s;
  try { s = await api("/stats"); }
  catch (e) {
    if (e.status >= 500)
      return toast("Сервер ответил ошибкой (бэкенд/БД). Проверьте, что uvicorn запущен из .venv.", "err");
    return toast("Нет связи с API: " + e.message, "err");
  }
  setBadges(s);

  const cards = [
    { label: "Документов обработано", value: s.documents_total, sub: `партнёров: ${s.partners} · услуг в справочнике: ${s.services}` },
    { label: "Успешная нормализация", value: s.auto_match_pct + "%", sub: `${s.items_matched} из ${s.items_total} позиций`, tone: s.auto_match_pct >= 80 ? "" : "warn" },
    { label: "В очереди на сопоставление", value: s.items_unmatched, sub: "ждут ручной разметки", tone: s.items_unmatched ? "warn" : "" },
    { label: "На верификации", value: s.items_unverified, sub: "сопоставлено, не подтверждено", tone: s.items_unverified ? "rose" : "" },
  ];
  $("#statGrid").innerHTML = cards.map((c) => `
    <div class="stat" ${c.tone ? `data-tone="${c.tone}"` : ""}>
      <div class="stat-label">${c.label}</div>
      <div class="stat-value">${c.value}</div>
      <div class="stat-sub">${c.sub}</div>
    </div>`).join("");

  const byStatus = s.documents_by_status || {};
  const maxDoc = Math.max(1, ...Object.values(byStatus));
  $("#docStatus").innerHTML = Object.keys(byStatus).length
    ? Object.entries(byStatus).map(([k, n]) => `
      <div class="sbar">
        <span class="sbar-name">${esc(k)}</span>
        <span class="sbar-track"><span class="sbar-fill" data-s="${esc(k)}" style="width:${(n / maxDoc) * 100}%"></span></span>
        <span class="sbar-num">${n}</span>
      </div>`).join("")
    : `<p class="muted">Документы ещё не загружены.</p>`;

  const p = s.auto_match_pct;
  $("#normHealth").innerHTML = `
    <div class="ring" style="--p:${p}"><div class="ring-inner"><div class="ring-pct">${p}%</div><div class="ring-cap">авто-матч</div></div></div>
    <div class="norm-legend">
      <div><span class="dot teal"></span> Сопоставлено автоматически <b>${s.items_matched}</b></div>
      <div><span class="dot amber"></span> В очереди (unmatched) <b>${s.items_unmatched}</b></div>
      <div><span class="dot line"></span> Всего активных позиций <b>${s.items_total}</b></div>
    </div>`;
};

function setBadges(s) {
  const u = $('[data-badge="unmatched"]'), v = $('[data-badge="unverified"]');
  u.textContent = s.items_unmatched; u.toggleAttribute("data-zero", !s.items_unmatched);
  v.textContent = s.items_unverified; v.toggleAttribute("data-zero", !s.items_unverified);
}

// ── Поиск услуги ───────────────────────────────────────
let searchTimer;
$("#searchInput").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (q.length < 2) { $("#searchResults").innerHTML = ""; return; }
  searchTimer = setTimeout(() => runSearch(q), 220);
});

async function runSearch(q) {
  const box = $("#searchResults");
  box.innerHTML = `<div class="skeleton"><span class="spin">⟳</span> Ищем…</div>`;
  let hits;
  try { hits = await api(`/search?q=${encodeURIComponent(q)}`); }
  catch (e) { box.innerHTML = `<div class="skeleton">Ошибка поиска: ${esc(e.message)}</div>`; return; }
  if (!hits.length) {
    box.innerHTML = `<div class="empty"><div class="empty-mark">⌕</div><p>Ничего не нашли по «${esc(q)}». Попробуйте короче или другое написание.</p></div>`;
    return;
  }
  box.innerHTML = hits.map((h) => `
    <div class="svc-card" data-sid="${h.service_id}">
      <div class="svc-head">
        <div><div class="svc-title">${esc(h.service_name)}</div>
        ${h.category ? `<div class="svc-cat">${esc(h.category)}</div>` : ""}</div>
        ${meter(h.score)}
        <span class="svc-toggle">показать клиники ▾</span>
      </div>
      <div class="offers" hidden></div>
    </div>`).join("");
}

$("#searchResults").addEventListener("click", async (e) => {
  const head = e.target.closest(".svc-head"); if (!head) return;
  const card = head.closest(".svc-card");
  const offers = $(".offers", card);
  const toggle = $(".svc-toggle", head);
  if (!offers.hidden) { offers.hidden = true; toggle.textContent = "показать клиники ▾"; return; }
  toggle.textContent = "скрыть ▴"; offers.hidden = false;
  offers.innerHTML = `<div class="skeleton"><span class="spin">⟳</span> Загружаем клиники…</div>`;
  let rows;
  try { rows = await api(`/services/${card.dataset.sid}/partners`); }
  catch (e2) { offers.innerHTML = `<div class="skeleton">Ошибка: ${esc(e2.message)}</div>`; return; }
  if (!rows.length) { offers.innerHTML = `<div class="skeleton">Пока ни одна клиника не предлагает эту услугу.</div>`; return; }
  offers.innerHTML = `<table class="otable"><thead><tr>
      <th>Клиника</th><th>Город</th><th>Цена резидент</th><th>Уверенность</th><th>Актуально</th></tr></thead><tbody>
    ${rows.map((r, i) => `<tr>
      <td><a class="link" data-pid="${r.partner_id}">${esc(r.name)}</a>${r.contact_phone ? `<div class="muted" style="font-size:12px">${esc(r.contact_phone)}</div>` : ""}</td>
      <td class="muted">${esc(r.city || "—")}</td>
      <td>${priceCell(r.price_resident_kzt, r.price_nonresident_kzt, i === 0)}</td>
      <td>${meter(r.match_confidence)}</td>
      <td class="muted price">${fmtDate(r.effective_date)}</td>
    </tr>`).join("")}</tbody></table>`;
});

// клик по клинике из поиска → карточка партнёра
$("#searchResults").addEventListener("click", (e) => {
  const link = e.target.closest("a.link[data-pid]");
  if (link) { show("partners"); openPartner(link.dataset.pid); }
});

// ── Партнёры ───────────────────────────────────────────
let partnersCache = [];
loaders.partners = async () => {
  if (partnersCache.length) return;
  const list = $("#partnerList");
  list.innerHTML = `<div class="skeleton"><span class="spin">⟳</span></div>`;
  try { partnersCache = await api("/partners?limit=200"); }
  catch (e) { list.innerHTML = `<div class="skeleton">Ошибка: ${esc(e.message)}</div>`; return; }
  renderPartnerList();
};

function renderPartnerList() {
  $("#partnerList").innerHTML = partnersCache.length
    ? partnersCache.map((p) => `
      <button class="pcard" data-pid="${p.partner_id}">
        <div class="pcard-name">${esc(p.name)}</div>
        <div class="pcard-city">${esc(p.city || "—")}</div>
      </button>`).join("")
    : `<p class="muted">Партнёров пока нет. Загрузите архив.</p>`;
}

$("#partnerList").addEventListener("click", (e) => {
  const card = e.target.closest(".pcard");
  if (card) openPartner(card.dataset.pid);
});

async function openPartner(pid) {
  $$(".pcard").forEach((c) => c.classList.toggle("is-active", c.dataset.pid === pid));
  const p = partnersCache.find((x) => x.partner_id === pid) || {};
  const detail = $("#partnerDetail");
  detail.innerHTML = `<div class="skeleton"><span class="spin">⟳</span></div>`;
  let rows;
  try { rows = await api(`/partners/${pid}/services`); }
  catch (e) { detail.innerHTML = `<div class="skeleton">Ошибка: ${esc(e.message)}</div>`; return; }
  const dates = rows.map((r) => r.effective_date).filter(Boolean).sort();
  detail.innerHTML = `
    <div class="detail-head">
      <h2>${esc(p.name || "Партнёр")}</h2>
      <div class="contacts">
        ${p.city ? `<span><span class="ic">⌖</span>${esc(p.city)}</span>` : ""}
        ${p.address ? `<span><span class="ic">⌂</span>${esc(p.address)}</span>` : ""}
        ${p.contact_phone ? `<span><span class="ic">✆</span>${esc(p.contact_phone)}</span>` : ""}
        ${p.contact_email ? `<span><span class="ic">✉</span>${esc(p.contact_email)}</span>` : ""}
        <span class="muted">Прайс актуален на ${fmtDate(dates[dates.length - 1])}</span>
      </div>
    </div>
    <table class="otable"><thead><tr>
        <th>Услуга</th><th>Резидент</th><th>Нерезидент</th><th>Статус</th></tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td>${r.service_name ? `<b>${esc(r.service_name)}</b>` : `<span class="muted">${esc(r.service_name_raw)}</span>`}
            ${r.service_name && r.service_name_raw !== r.service_name ? `<div class="muted" style="font-size:12px;font-family:var(--font-mono)">из: ${esc(r.service_name_raw)}</div>` : ""}</td>
        <td>${priceCell(r.price_resident_kzt, null)}</td>
        <td>${priceCell(r.price_nonresident_kzt, null)}</td>
        <td>${r.service_id ? meter(r.match_confidence) : `<span class="badge amber">не сопоставлено</span>`}</td>
      </tr>`).join("")}
    </tbody></table>`;
}

// ── Очередь сопоставления (unmatched) ──────────────────
loaders.match = async () => {
  const box = $("#matchQueue");
  box.innerHTML = `<div class="skeleton"><span class="spin">⟳</span> Загружаем очередь…</div>`;
  let items;
  try { items = await api("/unmatched?limit=200"); }
  catch (e) { box.innerHTML = `<div class="skeleton">Ошибка: ${esc(e.message)}</div>`; return; }
  $("#matchMeta").textContent = `${items.length} позиций в очереди`;
  if (!items.length) {
    box.innerHTML = emptyCelebrate("Очередь пуста", "Все позиции сопоставлены со справочником. Отличная работа.");
    return;
  }
  box.innerHTML = items.map(matchCard).join("");
  items.forEach((it) => loadCandidates(it.item_id, it.service_name_raw));
};

function matchCard(it) {
  return `<div class="lcard" data-item="${it.item_id}" data-raw="${esc(it.service_name_raw)}">
    <div class="lc-raw">
      <div class="lc-tag">Из документа · сырое название</div>
      <div class="lc-rawname">${esc(it.service_name_raw)}</div>
      ${it.service_code_source ? `<div class="lc-facts"><span class="fact"><span class="k">код источника</span><b>${esc(it.service_code_source)}</b></span></div>` : ""}
    </div>
    <div class="lc-act">
      <div class="lc-tag">Кандидаты из справочника</div>
      <div class="cand-list" data-cands><div class="cand-empty"><span class="spin">⟳</span> подбираем…</div></div>
      <div class="act-row">
        <button class="soft-btn" data-act="pick" style="flex:1">Выбрать вручную…</button>
      </div>
    </div>
  </div>`;
}

async function loadCandidates(itemId, raw) {
  const card = $(`.lcard[data-item="${itemId}"]`); if (!card) return;
  const box = $("[data-cands]", card);
  let cands = [];
  try { cands = await api(`/suggest?q=${encodeURIComponent(raw)}&limit=5`); } catch {}
  box.innerHTML = cands.length
    ? cands.map((c) => `
      <button class="cand" data-sid="${c.service_id}" data-sim="${c.sim}">
        <span class="cand-name">${esc(c.service_name)}${c.category ? `<span class="muted" style="font-size:11px"> · ${esc(c.category)}</span>` : ""}</span>
        ${meter(c.sim)}
      </button>`).join("")
    : `<div class="cand-empty">Похожих услуг не нашлось — выберите вручную.</div>`;
}

// ── Очередь верификации (review) ───────────────────────
loaders.review = async () => {
  const box = $("#reviewQueue");
  box.innerHTML = `<div class="skeleton"><span class="spin">⟳</span> Загружаем очередь…</div>`;
  let items;
  try { items = await api("/review?limit=200"); }
  catch (e) { box.innerHTML = `<div class="skeleton">Ошибка: ${esc(e.message)}</div>`; return; }
  $("#reviewMeta").textContent = `${items.length} позиций ожидают подтверждения`;
  if (!items.length) {
    box.innerHTML = emptyCelebrate("Нечего проверять", "Все сопоставленные позиции подтверждены.");
    return;
  }
  box.innerHTML = items.map(reviewCard).join("");
}

function reviewCard(it) {
  const anom = it.verification_note ? 1 : 0;
  const orig = it.price_original != null && it.currency_original && it.currency_original !== "KZT"
    ? `<span class="fact"><span class="k">оригинал</span><b>${fmtMoney(it.price_original)} ${esc(it.currency_original)}</b></span>` : "";
  return `<div class="lcard" data-item="${it.item_id}" data-anom="${anom}" data-raw="${esc(it.service_name_raw)}">
    <div class="lc-raw">
      <div class="lc-tag">Позиция прайса · ${esc(it.partner_name || "партнёр")}${it.city ? " · " + esc(it.city) : ""}</div>
      <div class="lc-rawname">${esc(it.service_name_raw)}</div>
      <div class="lc-facts">
        <span class="fact"><span class="k">резидент</span><b>${it.price_resident_kzt != null ? fmtMoney(it.price_resident_kzt) + " ₸" : "—"}</b></span>
        <span class="fact"><span class="k">нерезидент</span><b>${it.price_nonresident_kzt != null ? fmtMoney(it.price_nonresident_kzt) + " ₸" : "—"}</b></span>
        ${orig}
        <span class="fact"><span class="k">актуально</span><b>${fmtDate(it.effective_date)}</b></span>
      </div>
      ${it.verification_note ? `<div class="note"><span class="ic">⚠</span><span>${esc(it.verification_note)}</span></div>` : ""}
    </div>
    <div class="lc-act">
      <div class="lc-tag">Предложенное сопоставление</div>
      <div class="proposed"><b>${esc(it.service_name || "—")}</b><span class="arrow">←</span><span class="muted">${esc(it.service_name_raw)}</span></div>
      <div>${meter(it.match_confidence)}</div>
      <div class="act-row">
        <button class="ok-btn" data-act="confirm">✓ Подтвердить</button>
        <button class="soft-btn" data-act="pick">Изменить</button>
        <button class="danger-btn" data-act="reject">Отклонить</button>
      </div>
    </div>
  </div>`;
}

// ── Делегирование действий в карточках очередей ────────
async function handleLedgerClick(e) {
  const card = e.target.closest(".lcard"); if (!card) return;
  const itemId = card.dataset.item;
  const raw = card.dataset.raw;

  const cand = e.target.closest(".cand");
  if (cand) return applyMatch(itemId, cand.dataset.sid, parseFloat(cand.dataset.sim), raw, card);

  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "pick") return openPicker(itemId, raw, card);
  if (act === "confirm") return doVerify(itemId, true, raw, card);
  if (act === "reject") return doVerify(itemId, false, null, card);
}
$("#matchQueue").addEventListener("click", handleLedgerClick);
$("#reviewQueue").addEventListener("click", handleLedgerClick);

async function applyMatch(itemId, sid, confidence, raw, card) {
  try {
    await api("/match", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, service_id: sid, confidence }) });
    toast("Сопоставлено: " + raw, "ok");
    removeCard(card, "match");
  } catch (e) { toast("Не удалось сохранить: " + e.message, "err"); }
}

async function doVerify(itemId, verified, note, card) {
  try {
    await api("/verify", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, verified, note }) });
    toast(verified ? "Подтверждено" : "Отклонено — вернулось в сопоставление", verified ? "ok" : "");
    removeCard(card, "review");
  } catch (e) { toast("Ошибка: " + e.message, "err"); }
}

function removeCard(card, view) {
  card.style.transition = "opacity .2s, transform .2s";
  card.style.opacity = "0"; card.style.transform = "translateX(12px)";
  setTimeout(() => {
    const container = card.parentElement;
    card.remove();
    refreshStats();
    if (container && !container.querySelector(".lcard")) loaders[view]();
  }, 200);
}

// ── Модал выбора услуги из справочника ─────────────────
let pickerCtx = null, pickerTimer;
function openPicker(itemId, raw, card) {
  pickerCtx = { itemId, raw, card, isReview: card.closest('[data-view="review"]') != null };
  $("#pickerModal").hidden = false;
  const input = $("#pickerInput");
  input.value = raw; input.focus(); input.select();
  pickerSearch(raw);
}
function closePicker() { $("#pickerModal").hidden = true; pickerCtx = null; }
$("#pickerClose").addEventListener("click", closePicker);
$("#pickerModal").addEventListener("click", (e) => { if (e.target.id === "pickerModal") closePicker(); });
$("#pickerInput").addEventListener("input", (e) => {
  clearTimeout(pickerTimer);
  pickerTimer = setTimeout(() => pickerSearch(e.target.value.trim()), 200);
});

async function pickerSearch(q) {
  const list = $("#pickerList");
  if (q.length < 2) { list.innerHTML = `<div class="cand-empty">Введите минимум 2 символа.</div>`; return; }
  list.innerHTML = `<div class="cand-empty"><span class="spin">⟳</span></div>`;
  let cands = [];
  try { cands = await api(`/suggest?q=${encodeURIComponent(q)}&limit=20`); } catch {}
  if (!cands.length) {
    list.innerHTML = `<div class="cand-empty">Ничего не нашли. Уточните запрос.</div>`; return;
  }
  list.innerHTML = cands.map((c) => `
    <button class="cand" data-sid="${c.service_id}" data-sim="${c.sim}">
      <span class="cand-name">${esc(c.service_name)}${c.category ? `<span class="muted" style="font-size:11px"> · ${esc(c.category)}</span>` : ""}</span>
      ${meter(c.sim)}
    </button>`).join("");
}
$("#pickerList").addEventListener("click", async (e) => {
  const cand = e.target.closest(".cand"); if (!cand || !pickerCtx) return;
  const { itemId, raw, card } = pickerCtx;
  closePicker();
  await applyMatch(itemId, cand.dataset.sid, parseFloat(cand.dataset.sim), raw, card);
  if (pickerCtx?.isReview) loaders.review();
});

// ── Загрузка архива ────────────────────────────────────
const fileInput = $("#fileInput"), dz = $("#dropzone");
let chosenFile = null;
function setFile(f) {
  chosenFile = f;
  $("#dzTitle").textContent = f ? f.name : "Перетащите ZIP или нажмите, чтобы выбрать";
  $("#uploadBtn").disabled = !f;
}
fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("drag")));
dz.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });

$("#uploadBtn").addEventListener("click", async () => {
  if (!chosenFile) return;
  const btn = $("#uploadBtn");
  btn.disabled = true; btn.innerHTML = `<span class="spin">⟳</span> Обрабатываем — это может занять время…`;
  const fd = new FormData();
  fd.append("file", chosenFile);
  const norm = $("#normChk").checked;
  let r;
  try { r = await api(`/upload?normalize=${norm}`, { method: "POST", body: fd }); }
  catch (e) {
    $("#uploadResult").innerHTML = `<div class="note"><span class="ic">⚠</span><span>${esc(e.message)}</span></div>`;
    btn.innerHTML = "Обработать архив"; btn.disabled = false; return;
  }
  const pr = r.parse_report || {}, sr = r.save_report || {}, ns = r.normalize_stats;
  $("#uploadResult").innerHTML = `
    <div class="row"><span>Документов разобрано</span><b>${pr.documents_total ?? "—"}${pr.documents_error ? ` (ошибок ${pr.documents_error})` : ""}</b></div>
    <div class="row"><span>Позиций извлечено</span><b>${pr.items_total ?? "—"}</b></div>
    <div class="row"><span>Записано в БД</span><b>${sr.items_inserted ?? "—"}</b></div>
    ${ns ? `<div class="row"><span>Авто-нормализация</span><b>${ns.auto}/${ns.total}</b></div>
           <div class="row"><span>В очередь на ревью</span><b>${(ns.review || 0) + (ns.unmatched || 0)}</b></div>` : ""}`;
  toast("Архив обработан", "ok");
  btn.innerHTML = "Обработать архив"; btn.disabled = false;
  setFile(null); fileInput.value = "";
  partnersCache = [];
  loaders.documents();
  refreshStats();
});

// ── Загрузка справочника услуг ─────────────────────────
const catInput = $("#catInput"), catDz = $("#catDropzone");
let catFile = null;
function setCatFile(f) {
  catFile = f;
  $("#catTitle").textContent = f ? f.name : "Загрузить справочник (XLSX)";
  $("#catBtn").disabled = !f;
}
catInput.addEventListener("change", () => setCatFile(catInput.files[0]));
["dragover", "dragenter"].forEach((ev) => catDz.addEventListener(ev, (e) => { e.preventDefault(); catDz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => catDz.addEventListener(ev, () => catDz.classList.remove("drag")));
catDz.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) setCatFile(e.dataTransfer.files[0]); });

$("#catBtn").addEventListener("click", async () => {
  if (!catFile) return;
  const btn = $("#catBtn");
  btn.disabled = true; btn.innerHTML = `<span class="spin">⟳</span> Загружаем справочник…`;
  const fd = new FormData(); fd.append("file", catFile);
  let r;
  try { r = await api("/catalog", { method: "POST", body: fd }); }
  catch (e) {
    $("#catResult").innerHTML = `<div class="note"><span class="ic">⚠</span><span>${esc(e.message)}</span></div>`;
    btn.innerHTML = "Загрузить справочник"; btn.disabled = false; return;
  }
  $("#catResult").innerHTML = `
    <div class="row"><span>Получено услуг</span><b>${r.received}</b></div>
    <div class="row"><span>Добавлено</span><b>${r.inserted}</b></div>
    <div class="row"><span>Обновлено</span><b>${r.updated}</b></div>`;
  toast("Справочник загружен", "ok");
  btn.innerHTML = "Загрузить справочник"; btn.disabled = false;
  setCatFile(null); catInput.value = "";
  showCatalogStat(); refreshStats();
});

async function showCatalogStat() {
  try {
    const s = await api("/stats");
    $("#catalogStat").innerHTML = `В справочнике сейчас <b>${s.services}</b> услуг.`;
  } catch { $("#catalogStat").textContent = ""; }
}

loaders.upload = () => { loaders.documents(); showCatalogStat(); };
loaders.documents = async () => {
  const box = $("#docTable");
  let docs;
  try { docs = await api("/documents?limit=100"); }
  catch (e) { box.innerHTML = `<div class="skeleton">${esc(e.message)}</div>`; return; }
  box.innerHTML = docs.length
    ? docs.map((d) => `<div class="doc-row">
        <span class="doc-name" title="${esc(d.file_name)}">${esc(d.file_name)}</span>
        <span class="muted">${d.items} поз. · ${esc(d.partner_name || "—")}</span>
        <span class="pill ${esc(d.parse_status || "")}">${esc(d.parse_status || "—")}</span>
      </div>`).join("")
    : `<p class="muted">Документов пока нет. Загрузите архив слева.</p>`;
};

// ── Общие хелперы ──────────────────────────────────────
function emptyCelebrate(title, text) {
  return `<div class="empty celebrate"><div class="empty-mark">✓</div><p><b style="color:var(--ink);font-size:16px">${esc(title)}</b><br>${esc(text)}</p></div>`;
}
async function refreshStats() {
  try { setBadges(await api("/stats")); } catch {}
}

// ── Состояние API ──────────────────────────────────────
async function ping() {
  const dot = $("#dbdot");
  try { await api("/health"); dot.className = "db-dot ok"; dot.title = `API на связи${API ? " · " + API : ""}`; return true; }
  catch { dot.className = "db-dot bad"; dot.title = "Нет связи с API"; return false; }
}

// Найти рабочий адрес API: текущий → localhost:8000 → :8011.
// Нужно, когда консоль открыта не с того же origin, что и FastAPI.
async function resolveApi() {
  const tried = new Set([API]);
  const candidates = [API, "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8011"];
  for (const base of candidates) {
    const url = base.replace(/\/$/, "");
    if (tried.has(url) && url !== API) continue;
    tried.add(url);
    try {
      const r = await fetch(url + "/health", { signal: AbortSignal.timeout(2500) });
      if (r.ok) { API = url; return true; }
    } catch {}
  }
  return false;
}

function apiBanner() {
  const origin = location.origin === "null" ? "файл (file://)" : location.origin;
  toast("Нет связи с API. Откройте консоль по адресу самого сервера, напр. http://localhost:8000/", "err");
  $("#stage").querySelector('.view.is-active')?.insertAdjacentHTML("afterbegin", `
    <div class="note" style="margin-bottom:18px">
      <span class="ic">⚠</span>
      <span>Консоль открыта как <b>${esc(origin)}</b>, но API там не отвечает.
      Запустите <code>uvicorn main:app --port 8000</code> и откройте
      <b>http://localhost:8000/</b>, либо добавьте <code>?api=http://localhost:8000</code> к адресу.</span>
    </div>`);
}

// ── Горячие клавиши: 1–6 — переключение разделов ───────
const ORDER = ["dashboard", "search", "partners", "match", "review", "upload"];
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) {
    if (e.key === "Escape" && !$("#pickerModal").hidden) closePicker();
    return;
  }
  if (e.key === "Escape" && !$("#pickerModal").hidden) return closePicker();
  const n = parseInt(e.key, 10);
  if (n >= 1 && n <= ORDER.length) show(ORDER[n - 1]);
});

$("#refresh").addEventListener("click", () => { partnersCache = []; const v = location.hash.slice(1) || "dashboard"; loaders[v]?.(); ping(); toast("Обновлено"); });

// ── Старт ──────────────────────────────────────────────
(async function boot() {
  const start = location.hash.slice(1) && ORDER.includes(location.hash.slice(1)) ? location.hash.slice(1) : "dashboard";
  const ok = await resolveApi();
  await ping();
  show(start);
  if (ok) refreshStats();   // бейджи очередей актуальны при старте с любой вкладки
  else apiBanner();
  setInterval(ping, 20000);
})();
