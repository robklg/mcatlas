"use strict";
(() => {
  const CATALOG = window.MCATLAS_CATALOG;
  const NOTES = window.MCATLAS_ANNOTATIONS || {};
  const $ = (sel) => document.querySelector(sel);
  const DAY_MS = 86400000;
  const WEEK_MS = 7 * DAY_MS;

  // ---------- language: interface texts from i18n.js, formats from Intl ----------
  const I18N = window.MCATLAS_I18N;
  const LANG_KEY = "mcatlas-lang";
  function storedLang() { try { return localStorage.getItem(LANG_KEY); } catch { return null; } }
  const known = (l) => (l && I18N[l] ? l : null);
  // The viewer's own choice, else the default from mcatlas's config, else English.
  let lang = known(storedLang()) || known(window.MCATLAS_LANG) || "en";
  let NUM; let DEC; let DATE; let MONTH; let NOTE_DATE; let PLURAL;
  function setFormats() {
    const loc = I18N[lang].locale;
    NUM = new Intl.NumberFormat(loc);
    DEC = new Intl.NumberFormat(loc, { maximumFractionDigits: 1 });
    DATE = new Intl.DateTimeFormat(loc, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    MONTH = new Intl.DateTimeFormat(loc, { month: "short", timeZone: "UTC" });
    NOTE_DATE = new Intl.DateTimeFormat(loc, { dateStyle: "medium", timeStyle: "short" });
    PLURAL = new Intl.PluralRules(loc);
  }
  setFormats();
  // t("days", { n: 3 }) → "3 dagen"; numbers in {…} are formatted for the language.
  function t(key, vars = {}) {
    let v = I18N[lang][key] ?? I18N.en[key] ?? key;
    if (typeof v === "object") v = v[PLURAL.select(vars.n ?? 0)] ?? v.other;
    return v.replace(/\{(\w+)\}/g, (m, k) => {
      if (!(k in vars)) return m;
      return typeof vars[k] === "number" ? NUM.format(vars[k]) : String(vars[k]);
    });
  }
  function applyStaticTexts() {
    document.documentElement.lang = lang;
    for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
    for (const el of document.querySelectorAll("[data-i18n-placeholder]")) el.placeholder = t(el.dataset.i18nPlaceholder);
    for (const el of document.querySelectorAll("[data-i18n-title]")) el.title = t(el.dataset.i18nTitle);
    for (const el of document.querySelectorAll("[data-i18n-aria-label]")) el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
    $("#lang").value = lang;
  }
  applyStaticTexts();

  const blockName = (id) => id.replace(/^minecraft:/, "").replaceAll("_", " ");
  const modeName = (m) => t(`mode_${m}`);
  const generatorName = (g) => t(`gen_${g}`);
  const formatName = (f) => (f === "anvil" ? null : t(`format_${f}`));

  // ---------- 3D maps (BlueMap); the viewer only works through `mcatlas serve` ----------
  const SERVED = location.protocol.startsWith("http");
  // `mcatlas serve` also serves the atlas under atlas/ when it has been exported.
  if (SERVED) {
    fetch("atlas/index.html", { method: "HEAD" }).then((r) => {
      if (r.ok) for (const id of ["atlas-link", "timeline-link"]) document.getElementById(id).hidden = false;
    }, () => {});
  }
  const rendersOf = (w) => (CATALOG.renders || {})[w.world_id] || [];
  function firstImage(w) {
    for (const m of rendersOf(w)) for (const path of Object.values(m.images)) return path;
    return null;
  }
  function view3d(m, i) {
    const a = m.areas[i];
    const y = m.heights[i] ?? a.y;
    const side = Math.max(a.box[2] - a.box[0], a.box[3] - a.box[1]);
    const distance = Math.round(Math.min(Math.max(side * 1.3, 80), 2000));
    return `3d/#${m.map_id}:${a.x}:${y}:${a.z}:${distance}:0:0.5:0:0:perspective`;
  }
  function siteView(w, k) {
    for (const m of rendersOf(w)) {
      const i = m.areas.findIndex((a) => a.site === k);
      if (i >= 0) return [m, i];
    }
    return null;
  }

  // ---------- small DOM helper (text only: never innerHTML with data) ----------
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  const SVG_NS = "http://www.w3.org/2000/svg";
  function s(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    return node;
  }

  // ---------- theme ----------
  function storedTheme() { try { return localStorage.getItem("mcatlas-theme"); } catch { return null; } }
  function applyTheme(th) {
    if (th) document.documentElement.setAttribute("data-theme", th);
    else document.documentElement.removeAttribute("data-theme");
  }
  applyTheme(storedTheme());
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("mcatlas-theme", next); } catch { /* storage unavailable */ }
  });

  if (!CATALOG) {
    $("#summary").textContent = t("no_catalog");
    return;
  }

  // ---------- time axis shared by every strip ----------
  const parseDay = (d) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
  const fmtDay = (d) => DATE.format(new Date(parseDay(d)));
  const firstMs = CATALOG.first_day ? parseDay(CATALOG.first_day) : Date.UTC(2020, 0, 1);
  const lastMs = CATALOG.last_day ? parseDay(CATALOG.last_day) : firstMs + 365 * DAY_MS;
  // Align bins to Mondays so a column is always one calendar week.
  const axisStart = firstMs - ((new Date(firstMs).getUTCDay() + 6) % 7) * DAY_MS;
  const binCount = Math.max(1, Math.ceil((lastMs - axisStart + DAY_MS) / WEEK_MS));
  const years = [];
  for (let y = new Date(axisStart).getUTCFullYear() + 1; Date.UTC(y, 0, 1) <= lastMs; y++) {
    years.push({ year: y, frac: (Date.UTC(y, 0, 1) - axisStart) / (binCount * WEEK_MS) });
  }

  // ---------- notes (annotations) ----------
  function setNote(w, note) {
    w._note = note && (note.title || note.note || note.tags.length || note.rating) ? note : null;
    const n = w._note;
    w._search = n ? `${w._baseSearch} ${[n.title, n.note, ...n.tags].join(" ").toLocaleLowerCase()}` : w._baseSearch;
  }
  let notesWritable = false;
  async function checkNotesApi() {
    if (!location.protocol.startsWith("http")) return;
    try {
      const r = await fetch("api/status", { headers: { "X-Mcatlas": "1" } });
      notesWritable = r.ok && (await r.json()).notes === true;
    } catch { notesWritable = false; }
    if (notesWritable && $("#detail").open && openWorld) openDetail(openWorld);
  }

  // ---------- derive per-world fields once ----------
  const byId = new Map();
  for (const w of CATALOG.worlds) {
    byId.set(w.world_id, w);
    const days = Object.entries(w.activity.days || {}).map(([d, sig]) => ({ d, t: parseDay(d), sig }));
    days.sort((a, b) => a.t - b.t);
    w._days = days;
    const bins = new Array(binCount).fill(null);
    for (const day of days) {
      const i = Math.floor((day.t - axisStart) / WEEK_MS);
      if (i < 0 || i >= binCount) continue;
      (bins[i] ||= []).push(day);
    }
    w._bins = bins;
    const m = /^(\d+)\.(\d+)/.exec(w.version_name || "");
    w._family = m ? `${m[1]}.${m[2]}` : (w.version_name ? "family_other" : "family_unknown");
    w._playerNames = w.players.map((p) => p.name || p.uuid.slice(0, 8));
    const topBlocks = w.build ? w.build.top_blocks.map(([id]) => blockName(id)) : [];
    w._downloaded = Object.keys(w.activity.history || {}).length > 0;
    w._texts = [];
    w._textSearch = "";
    w._baseSearch = [w.name, w.folder_name, w.level_name, w.relpath, ...w._playerNames, ...topBlocks]
      .filter(Boolean).join(" ").toLocaleLowerCase();
    setNote(w, NOTES[w.world_id] || null);
  }
  const familyName = (f) => (f.startsWith("family_") ? t(f) : f);
  // A "copy" is a world that shares ≥90% history with a higher-scored one.
  for (const w of CATALOG.worlds) {
    w._copyOf = null;
    for (const r of w.related) {
      const other = byId.get(r.world_id);
      if (!other || r.similarity < 0.9) continue;
      const otherWins = other.importance.score > w.importance.score ||
        (other.importance.score === w.importance.score && other.world_id < w.world_id);
      if (otherWins) { w._copyOf = other; break; }
    }
  }

  // ---------- formatting ----------
  function bytes(n) {
    if (n < 1024) return `${n} B`;
    const units = ["kB", "MB", "GB", "TB"];
    let v = n / 1024; let u = 0;
    while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
    return `${DEC.format(v)} ${units[u]}`;
  }
  function period(w) {
    const a = w.activity;
    if (!a.first_day) return t("no_dates");
    if (a.first_day === a.last_day) return fmtDay(a.first_day);
    return `${fmtDay(a.first_day)} – ${fmtDay(a.last_day)}`;
  }
  const hours = (x) => t("hours", { x: DEC.format(x) });
  const dayMonth = (ms) => DATE.formatToParts(new Date(ms)).filter((p) => p.type !== "year")
    .map((p) => p.value).join("").replace(/[\s,]+$/, "");

  // ---------- time range: worlds with activity between two days ----------
  const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10);
  const hasRange = () => state.from !== null || state.to !== null;
  const inRange = (ms) => (state.from === null || ms >= state.from) && (state.to === null || ms <= state.to);
  // A week column counts as inside when any of its days is.
  const binInRange = (i) => {
    const start = axisStart + i * WEEK_MS;
    return (state.to === null || start <= state.to) && (state.from === null || start + WEEK_MS - DAY_MS >= state.from);
  };
  const daysInRange = (w) => (hasRange() ? w._days.filter((d) => inRange(d.t)).length : w.activity.distinct_days);

  // ---------- activity strip (single series, sequential blue) ----------
  function strip(w, cls, height) {
    const wrap = h("div", { class: "strip-wrap", style: "position:relative" });
    const W = 1000; const H = height; const gap = 2;
    const bw = W / binCount;
    const svg = s("svg", { class: cls, viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
      "aria-label": t("strip_aria", { n: w.activity.distinct_days, period: period(w) }) });
    for (const y of years) {
      svg.append(s("line", { x1: y.frac * W, x2: y.frac * W, y1: 0, y2: H, stroke: "var(--grid)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    }
    svg.append(s("line", { x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5, stroke: "var(--baseline)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    w._bins.forEach((bin, i) => {
      if (!bin) return;
      const hgt = Math.max(3, ((H - 2) * bin.length) / 7);
      const fill = binInRange(i) ? "var(--accent)" : "var(--presence)";
      svg.append(s("rect", { x: i * bw + gap / 2, y: H - 1 - hgt, width: Math.max(1.5, bw - gap), height: hgt, fill, rx: 1 }));
    });
    svg.addEventListener("mousemove", (ev) => {
      const box = svg.getBoundingClientRect();
      const i = Math.floor(((ev.clientX - box.left) / box.width) * binCount);
      showWeekTip(axisStart + i * WEEK_MS, w._bins[i], ev);
    });
    svg.addEventListener("mouseleave", hideTip);
    wrap.append(svg);
    return wrap;
  }

  const tip = $("#tooltip");
  function showWeekTip(start, days, ev) {
    tip.replaceChildren(
      h("div", null, t("week_of", { date: DATE.format(new Date(start)) })),
      days
        ? h("div", null, `${t("active_days", { n: days.length })}: `, days.map((d) => dayMonth(d.t)).join(", "))
        : h("div", { class: "muted" }, t("no_activity")),
    );
    placeTip(ev);
  }
  // An open <dialog> sits in the browser's top layer, above any z-index: while it is open the
  // tooltip has to live inside it to be visible.
  function placeTip(ev) {
    const dlg = $("#detail");
    const host = dlg.open ? dlg : document.body;
    if (tip.parentNode !== host) host.append(tip);
    tip.hidden = false;
    tip.style.left = `${Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${ev.clientY + 14}px`;
  }
  function hideTip() { tip.hidden = true; }

  // ---------- zoomed strip: only the chosen range (table view) ----------
  const DAY_ZOOM = 124;  // up to about four months, one column per day
  function zoomAxis() {
    const from = state.from ?? firstMs;
    const to = state.to ?? lastMs;
    const days = Math.round((to - from) / DAY_MS) + 1;
    if (days <= DAY_ZOOM) return { daily: true, start: from, end: to, count: days };
    const lo = Math.max(0, Math.floor((from - axisStart) / WEEK_MS));
    const hi = Math.min(binCount - 1, Math.floor((to - axisStart) / WEEK_MS));
    return { daily: false, lo, start: axisStart + lo * WEEK_MS, end: to, count: Math.max(1, hi - lo + 1) };
  }
  const axisSpan = (ax) => (ax.daily ? ax.count * DAY_MS : ax.count * WEEK_MS);
  // Month starts (or year starts, for long ranges) inside the axis, as fractions of its width.
  function axisMarks(ax) {
    const span = axisSpan(ax);
    const byYear = span > 900 * DAY_MS;
    const marks = [];
    const d = new Date(ax.start);
    for (let y = d.getUTCFullYear(), m = d.getUTCMonth() + 1; ; m++) {
      if (m > 11) { m = 0; y++; }
      const ms = Date.UTC(y, m, 1);
      if (ms >= ax.start + span) break;  // a boundary at the very end marks nothing
      if (byYear && m !== 0) continue;
      marks.push({ frac: (ms - ax.start) / span, label: m === 0 || byYear ? String(y) : MONTH.format(new Date(ms)) });
    }
    return marks;
  }
  function zoomTicks(ax) {
    const row = h("div", { class: "zoom-ticks" });
    const marks = axisMarks(ax);
    const every = Math.ceil(marks.length / 8);  // keep labels from colliding
    marks.forEach((mk, n) => {
      if (n % every === 0 && mk.frac < 0.97) row.append(h("span", { style: `left:${(mk.frac * 100).toFixed(2)}%` }, mk.label));
    });
    return row;
  }
  const SIGNALS = ["chunk_saves", "advancements", "file_saves"];
  function zoomStrip(w, ax, height) {
    const W = 1000; const H = height;
    const bw = W / ax.count; const gap = ax.count > 300 ? 0.5 : 1.5;
    const svg = s("svg", { class: "strip", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
      "aria-label": t("zoom_aria", { n: daysInRange(w) }) });
    for (const mk of axisMarks(ax)) {
      svg.append(s("line", { x1: mk.frac * W, x2: mk.frac * W, y1: 0, y2: H, stroke: "var(--grid)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    }
    svg.append(s("line", { x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5, stroke: "var(--baseline)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    const cols = new Array(ax.count).fill(null);
    for (const d of w._days) {
      if (!inRange(d.t)) continue;
      const i = Math.floor((d.t - ax.start) / (ax.daily ? DAY_MS : WEEK_MS));
      if (i >= 0 && i < ax.count) (cols[i] ||= []).push(d);
    }
    cols.forEach((col, i) => {
      if (!col) return;
      const hgt = ax.daily ? H - 3 : Math.max(3, ((H - 2) * col.length) / 7);
      svg.append(s("rect", { x: i * bw + gap / 2, y: H - 1 - hgt, width: Math.max(1, bw - gap), height: hgt, fill: "var(--accent)", rx: 1 }));
    });
    svg.addEventListener("mousemove", (ev) => {
      const box = svg.getBoundingClientRect();
      const i = Math.min(ax.count - 1, Math.max(0, Math.floor(((ev.clientX - box.left) / box.width) * ax.count)));
      const col = cols[i];
      const start = ax.start + i * (ax.daily ? DAY_MS : WEEK_MS);
      if (!ax.daily) { showWeekTip(start, col, ev); return; }
      const sig = col ? col[0].sig : null;
      const evidence = sig ? SIGNALS.filter((k) => sig[k]).map((k) => `${NUM.format(sig[k])} ${t(`sig_${k}`)}`) : [];
      tip.replaceChildren(h("div", null, DATE.format(new Date(start))),
        sig ? h("div", null, evidence.join(", ") || t("last_played_only")) : h("div", { class: "muted" }, t("no_activity")));
      placeTip(ev);
    });
    svg.addEventListener("mouseleave", hideTip);
    return h("div", { class: "strip-wrap", style: "position:relative" }, svg);
  }

  function icon(w, cls) {
    if (w.has_icon) {
      return h("img", { class: cls || "icon", src: `icons/${w.world_id}.png`, alt: "", loading: "lazy" });
    }
    const flat = firstImage(w);
    if (flat) return h("img", { class: `${cls || "icon"} flat`, src: flat, alt: "", loading: "lazy" });
    return h("div", { class: cls || "icon", "aria-hidden": "true" }, (w.name || "?").trim().charAt(0).toUpperCase());
  }

  function badges(w) {
    const list = [];
    if (w.version_name) list.push(h("span", { class: "badge" }, w.version_name));
    if (w.game_mode !== null && w.game_mode !== undefined) list.push(h("span", { class: "badge" }, modeName(w.game_mode)));
    if (w.generator && w.generator !== "default") list.push(h("span", { class: "badge" }, generatorName(w.generator)));
    if (formatName(w.format)) list.push(h("span", { class: "badge warn" }, formatName(w.format)));
    if (w.hardcore) list.push(h("span", { class: "badge" }, "Hardcore"));
    if (w.modded) list.push(h("span", { class: "badge" }, "Mods"));
    if (w.afk_suspect) list.push(h("span", { class: "badge warn", title: t("badge_afk_title", { h: hours(w.hours_per_session) }) }, t("badge_afk")));
    if (w._copyOf) list.push(h("span", { class: "badge", title: t("badge_copy_title", { name: w._copyOf.folder_name }) }, t("badge_copy")));
    if (Object.keys(w.activity.history || {}).length) {
      list.push(h("span", { class: "badge", title: t("badge_history_title") }, t("badge_history")));
    }
    return h("div", { class: "badges" }, list);
  }

  // ---------- controls ----------
  const state = { from: null, to: null, q: "", sort: "importance", version: "", mode: "", player: "", generator: "", underground: "", hideCopies: false, hideDownloaded: false, onlyNoted: false, view: "cards" };

  const uniq = (xs) => [...new Set(xs)].sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
  // (Re)fill a filter menu after its first "all" option, keeping the current choice.
  function fillSelect(sel, values, label) {
    const keep = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    for (const v of values) sel.append(h("option", { value: v }, label ? label(v) : v));
    sel.value = keep;
  }
  function fillFilters() {
    fillSelect($("#f-version"), uniq(CATALOG.worlds.map((w) => w._family)), familyName);
    fillSelect($("#f-mode"), uniq(CATALOG.worlds.map((w) => w.game_mode).filter((m) => m !== null)), modeName);
    fillSelect($("#f-player"), uniq(CATALOG.worlds.flatMap((w) => w._playerNames)));
    fillSelect($("#f-generator"), uniq(CATALOG.worlds.map((w) => w.generator)), generatorName);
  }
  fillFilters();

  const extraDays = (w) => (w.days_upper ? w.days_upper - w.activity.distinct_days : 0);
  function daysText(w) {
    const base = t("days", { n: w.activity.distinct_days });
    return extraDays(w) > 0 ? t("days_max", { days: base, n: w.days_upper }) : base;
  }
  const daysRange = (w) => (extraDays(w) > 0
    ? `${NUM.format(w.activity.distinct_days)}–${NUM.format(w.days_upper)}` : NUM.format(w.activity.distinct_days));

  const UNDERGROUND = {
    mostly: (p) => p !== null && p !== undefined && p >= 50,
    some: (p) => p !== null && p !== undefined && p >= 20,
    little: (p) => p !== null && p !== undefined && p < 10,
  };
  const SORTS = {
    importance: (w) => -w.importance.score,
    last: (w) => -(w.activity.last_day ? parseDay(w.activity.last_day) : 0),
    first: (w) => (w.activity.first_day ? parseDay(w.activity.first_day) : Infinity),
    days: (w) => -w.activity.distinct_days,
    sessions: (w) => -w.sessions,
    hidden: (w) => -extraDays(w),
    span: (w) => -w.activity.span_days,
    play: (w) => -w.play_hours,
    used: (w) => -w.items_used,
    size: (w) => -w.size_bytes,
    chunks: (w) => -w.chunks,
    built: (w) => -(w.build ? w.build.built : -1),
    below: (w) => -(w.build && w.build.pct_below !== null ? w.build.pct_below : -1),
    name: (w) => w.name.toLocaleLowerCase(),
    inRange: (w) => -daysInRange(w),
  };

  // `ignoreRange`: every other filter, for the overview timeline that picks the range.
  function visibleWorlds(ignoreRange = false) {
    const terms = queryTerms();
    const key = SORTS[state.sort];
    return CATALOG.worlds
      .filter((w) => ignoreRange || !hasRange() || w._days.some((d) => inRange(d.t)))
      .filter((w) => terms.every((q) => w._search.includes(q) || w._textSearch.includes(q)))
      .filter((w) => !state.version || w._family === state.version)
      .filter((w) => !state.mode || String(w.game_mode) === state.mode)
      .filter((w) => !state.player || w._playerNames.includes(state.player))
      .filter((w) => !state.generator || w.generator === state.generator)
      .filter((w) => !state.hideCopies || !w._copyOf)
      .filter((w) => !state.hideDownloaded || !w._downloaded)
      .filter((w) => !state.onlyNoted || w._note)
      .filter((w) => !state.underground || UNDERGROUND[state.underground](w.build && w.build.pct_below))
      .sort((a, b) => {
        const ka = key(a); const kb = key(b);
        if (ka < kb) return -1;
        if (ka > kb) return 1;
        return a.name.localeCompare(b.name);
      });
  }

  // ---------- texts: signs, books, names, commands (loaded after the page) ----------
  const kindName = (k) => t(`kind_${k}`);
  function textSummary(w) {
    const parts = Object.entries(w.text_counts || {}).sort((a, b) => b[1] - a[1])
      .map(([k, n]) => t(`count_${k}`, { n }));
    return parts.length ? t("texts_line", { list: parts.join(", ") }) : null;
  }
  const queryTerms = () => state.q.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  function textMatches(w) {
    const terms = queryTerms();
    if (!terms.length) return [];
    return w._texts.filter((x) => { if (x[7]) return false; const low = x[1].toLocaleLowerCase(); return terms.some((q) => low.includes(q)); });
  }
  function textHit(w) {
    const terms = queryTerms();
    if (!terms.length || terms.every((q) => w._search.includes(q))) return null;
    return textMatches(w)[0] || null;
  }
  function snippet(text) {
    const flat = text.replace(/\s+/g, " ");
    const terms = queryTerms();
    const low = flat.toLocaleLowerCase();
    const at = Math.max(0, ...terms.map((q) => low.indexOf(q)));
    const start = Math.max(0, at - 40);
    return `${start ? "…" : ""}${flat.slice(start, start + 140)}${flat.length > start + 140 ? "…" : ""}`;
  }
  function loadTexts() {
    const el = document.createElement("script");
    el.src = "data/texts.js";
    el.onload = () => {
      const all = window.MCATLAS_TEXTS || {};
      for (const w of CATALOG.worlds) {
        w._texts = all[w.world_id] || [];
        // Texts of a downloaded map's makers stay visible in the detail view, not in search.
        w._textSearch = w._texts.filter((x) => !x[7]).map((x) => x[1]).join("\n").toLocaleLowerCase();
      }
      render();
      if ($("#detail").open && openWorld) openDetail(openWorld);
    };
    document.head.append(el);
  }

  // ---------- views ----------
  function card(w) {
    const facts = h("div", { class: "facts" },
      hasRange() ? [h("b", { class: "in-range" }, t("days_in_range", { n: daysInRange(w) })), " · "] : null,
      h("b", { title: t("days_note") }, daysText(w)), " · ",
      period(w),
      w.play_hours ? [" · ", h("b", null, hours(w.play_hours))] : null,
      w.items_used ? [" · ", t("items", { n: w.items_used })] : null,
      w.build && w.build.built ? [" · ", h("b", null, t("blocks_built", { n: w.build.built })),
        w.build.pct_below !== null ? ` (${t("pct_underground", { p: DEC.format(w.build.pct_below) })})` : null] : null,
      " · ", bytes(w.size_bytes));
    const names = w._playerNames.length ? t("players_line", { list: w._playerNames.join(", ") }) : null;
    const hit = textHit(w);
    return h("article", { class: "card", tabindex: 0, role: "button", "aria-label": t("open_world", { name: w.name }),
      onclick: () => openDetail(w), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(w); } } },
      icon(w),
      h("div", null,
        h("div", { class: "name" }, w.name),
        w.name !== w.folder_name ? h("div", { class: "folder" }, w.folder_name) : null,
        badges(w)),
      facts,
      strip(w, "strip", 28),
      w._note ? h("div", { class: "note-line" }, h("b", null, w._note.title || t("note")),
        w._note.rating ? ` ${"★".repeat(w._note.rating)}` : null,
        w._note.tags.length ? h("span", { class: "folder" }, ` · ${w._note.tags.join(", ")}`) : null) : null,
      hit ? h("div", { class: "hit" }, `${kindName(hit[0])}: `, h("q", null, snippet(hit[1]))) : null,
      textSummary(w) ? h("div", { class: "people" }, textSummary(w)) : null,
      names ? h("div", { class: "people" }, names) : null);
  }

  function table(worlds) {
    const ax = hasRange() ? zoomAxis() : null;
    const cols = [
      ["col_name", "name"], ["col_days", "days"], ["col_period", "first"], ["col_play", "play"],
      ["col_items", "used"], ["col_size", "size"], ["col_version", null], ["col_activity", null],
    ];
    const head = h("tr", null, cols.map(([label, key]) => h("th", {
      onclick: key ? () => { state.sort = key; $("#sort").value = key; render(); } : null,
      "aria-sort": key && state.sort === key ? "descending" : null,
    }, label === "col_activity" && ax
      ? [t(ax.daily ? "activity_per_day" : "activity_per_week"), zoomTicks(ax)]
      : t(label))));
    const rows = worlds.map((w) => h("tr", { onclick: () => openDetail(w) },
      h("td", null, w.name, w.name !== w.folder_name ? h("div", { class: "folder" }, w.folder_name) : null),
      h("td", { class: "num", title: t("days_note") }, daysRange(w)),
      h("td", null, period(w)),
      h("td", { class: "num" }, w.play_hours ? hours(w.play_hours) : "–"),
      h("td", { class: "num" }, w.items_used ? NUM.format(w.items_used) : "–"),
      h("td", { class: "num" }, bytes(w.size_bytes)),
      h("td", null, w.version_name || "–"),
      h("td", null, ax ? zoomStrip(w, ax, 20) : strip(w, "strip", 20))));
    return h("table", { class: "worlds" }, h("thead", null, head), h("tbody", null, rows));
  }

  function render() {
    const worlds = visibleWorlds();
    const list = $("#list");
    list.className = state.view === "cards" ? "cards" : "";
    if (!worlds.length) {
      list.replaceChildren(h("p", { class: "empty" }, t("empty")));
    } else if (state.view === "cards") {
      list.replaceChildren(...worlds.map(card));
    } else {
      list.replaceChildren(table(worlds));
    }
    renderTimeline();
    const range = hasRange() ? t("summary_range", { range: rangeText() }) : "";
    const span = CATALOG.first_day ? ` · ${fmtDay(CATALOG.first_day)} – ${fmtDay(CATALOG.last_day)}` : "";
    const ignored = (CATALOG.ignored_file_days || []).length
      ? t("summary_ignored", { days: CATALOG.ignored_file_days.map(fmtDay).join(", ") }) : "";
    $("#summary").textContent = `${t("summary", { shown: worlds.length, total: CATALOG.worlds.length })}${range}${span}${ignored}`;
  }

  // ---------- overview timeline: pick a range by dragging ----------
  function rangeText() {
    const from = state.from === null ? null : DATE.format(new Date(state.from));
    const to = state.to === null ? null : DATE.format(new Date(state.to));
    if (from && to) return t("range_both", { from, to });
    return from ? t("range_from", { from }) : t("range_to", { to });
  }
  function setRange(from, to) {
    if (from !== null && to !== null && from > to) [from, to] = [to, from];
    state.from = from; state.to = to;
    $("#t-from").value = from === null ? "" : isoDay(from);
    $("#t-to").value = to === null ? "" : isoDay(to);
    $("#t-clear").hidden = !hasRange();
  }
  function setHash() {
    const p = new URLSearchParams();
    if (state.from !== null) p.set("from", isoDay(state.from));
    if (state.to !== null) p.set("to", isoDay(state.to));
    if ($("#detail").open && openWorld) p.set("w", openWorld.world_id);
    const hash = p.toString();
    history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
  }
  let dragging = null;
  function renderTimeline() {
    const W = 1000; const H = 56; const gap = 1;
    const bw = W / binCount;
    const counts = new Array(binCount).fill(0);
    for (const w of visibleWorlds(true)) w._bins.forEach((bin, i) => { if (bin) counts[i]++; });
    const max = Math.max(1, ...counts);
    const svg = s("svg", { class: "overview", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
      "aria-label": t("timeline_aria") });
    for (const y of years) {
      svg.append(s("line", { x1: y.frac * W, x2: y.frac * W, y1: 0, y2: H, stroke: "var(--grid)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    }
    const band = s("rect", { y: 0, height: H, fill: "var(--accent-soft)", opacity: 0.6 });
    svg.append(band);
    const bars = counts.map((n, i) => {
      if (!n) return null;
      const hgt = Math.max(2, ((H - 2) * n) / max);
      const bar = s("rect", { x: i * bw + gap / 2, y: H - 1 - hgt, width: Math.max(1, bw - gap), height: hgt, rx: 1 });
      svg.append(bar);
      return bar;
    });
    svg.append(s("line", { x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5, stroke: "var(--baseline)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }));
    const paint = () => {
      const on = hasRange();
      let lo = binCount; let hi = -1;
      bars.forEach((bar, i) => {
        const inside = binInRange(i);
        if (inside) { lo = Math.min(lo, i); hi = Math.max(hi, i); }
        if (bar) bar.setAttribute("fill", !on || inside ? "var(--accent)" : "var(--presence)");
      });
      band.setAttribute("visibility", on && hi >= lo ? "visible" : "hidden");
      if (hi >= lo) { band.setAttribute("x", lo * bw); band.setAttribute("width", (hi - lo + 1) * bw); }
    };
    paint();
    const binAt = (ev) => {
      const box = svg.getBoundingClientRect();
      return Math.min(binCount - 1, Math.max(0, Math.floor(((ev.clientX - box.left) / box.width) * binCount)));
    };
    const weekRange = (a, b) => setRange(axisStart + Math.min(a, b) * WEEK_MS, axisStart + Math.max(a, b) * WEEK_MS + WEEK_MS - DAY_MS);
    svg.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      svg.setPointerCapture(ev.pointerId);
      dragging = binAt(ev);
      weekRange(dragging, dragging);
      paint();
      hideTip();
    });
    svg.addEventListener("pointermove", (ev) => {
      if (dragging !== null) { weekRange(dragging, binAt(ev)); paint(); return; }
      const i = binAt(ev);
      tip.replaceChildren(
        h("div", null, t("week_of", { date: DATE.format(new Date(axisStart + i * WEEK_MS)) })),
        counts[i] ? h("div", null, t("worlds_active", { n: counts[i] })) : h("div", { class: "muted" }, t("no_activity")));
      placeTip(ev);
    });
    const finish = () => { if (dragging === null) return; dragging = null; setHash(); render(); };
    svg.addEventListener("pointerup", finish);
    svg.addEventListener("pointercancel", finish);
    svg.addEventListener("pointerleave", hideTip);
    $("#t-chart").replaceChildren(svg, monthTicks());
  }

  // ---------- detail ----------
  function stat(label, value) {
    return h("div", { class: "stat" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value));
  }
  function kv(pairs) {
    return h("dl", { class: "kv" }, pairs.filter(([, v]) => v !== null && v !== undefined && v !== "")
      .flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
  }
  function monthTicks() {
    const row = h("div", { style: "position:relative;height:16px;font-size:11px;color:var(--muted)" });
    const start = new Date(axisStart);
    const months = (binCount * WEEK_MS) / (30.44 * 86400000);
    const every = months > 30 ? 12 : months > 12 ? 3 : 1;  // keep labels from colliding
    for (let y = start.getUTCFullYear(), m = start.getUTCMonth() + 1; ; m++) {
      if (m > 11) { m = 0; y++; }
      const ms = Date.UTC(y, m, 1);
      if (ms > lastMs) break;
      if (m % every !== 0) continue;
      const frac = (ms - axisStart) / (binCount * WEEK_MS);
      const label = m === 0 ? String(y) : MONTH.format(new Date(ms));
      row.append(h("span", { style: `position:absolute;left:${(frac * 100).toFixed(2)}%;transform:translateX(-50%)` }, label));
    }
    return row;
  }

  function historyNote(w) {
    const hist = Object.keys(w.activity.history || {}).sort();
    const notes = [];
    if (hist.length) {
      notes.push(t("history_note", { days: t("days", { n: hist.length }), first: fmtDay(hist[0]), last: fmtDay(hist[hist.length - 1]) }));
    }
    if (w.foreign_players) {
      notes.push(t("foreign_note", { n: w.foreign_players, h: hours(Math.max(0, w.play_hours_all - w.play_hours)) }));
    }
    return notes.length ? h("p", { class: "folder" }, notes.join(" ")) : null;
  }

  // ---------- build (tier 2): what was built, and where ----------
  const DIMS = ["overworld", "the_nether", "the_end"];
  const dimName = (k) => (DIMS.includes(k.replace(/^minecraft:/, "")) ? t(`dim_${k.replace(/^minecraft:/, "")}`) : k.replace(/^minecraft:/, ""));
  const STRUCTURES = [
    "mineshaft", "village", "ancient_city", "dungeon", "stronghold", "pillager_outpost", "ruined_portal",
    "ocean_ruin", "shipwreck", "buried_treasure", "desert_pyramid", "jungle_pyramid", "igloo", "swamp_hut",
    "mansion", "monument", "fortress", "bastion", "end_city", "trail_ruins", "trial_chambers",
  ];
  const structureName = (k) => {
    const known = STRUCTURES.find((name) => k.startsWith(name));
    return known ? t(`struct_${known}`) : k.replaceAll("_", " ");
  };
  const pct = (x) => (x === null || x === undefined ? "–" : `${DEC.format(x)}%`);

  function loadMap(id) {
    const maps = (window.MCATLAS_MAPS = window.MCATLAS_MAPS || {});
    if (maps[id]) return Promise.resolve(maps[id]);
    return new Promise((resolve) => {
      const el = document.createElement("script");
      el.src = `data/maps/${encodeURIComponent(id)}.js`;
      el.onload = () => resolve(maps[id] || null);
      el.onerror = () => resolve(null);
      document.head.append(el);
    });
  }

  const SEEN_KEY = "mcatlas-seen-sites";
  function seenSites() { try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]")); } catch { return new Set(); } }
  function setSeen(key, on) {
    const seen = seenSites();
    if (on) seen.add(key); else seen.delete(key);
    try { localStorage.setItem(SEEN_KEY, JSON.stringify([...seen])); } catch { /* storage unavailable */ }
  }
  const siteKey = (w, site) => `${w.world_id}:${site.dimension}:${site.x}:${site.z}`;
  const tpCommand = (site) => `/execute in ${site.dimension} run tp @s ${site.x} ${site.max_y + 2} ${site.z}`;

  function copyButton(text) {
    return h("button", { type: "button", class: "ghost small", onclick: (e) => {
      const btn = e.currentTarget;
      const done = () => { btn.textContent = t("copied"); setTimeout(() => { btn.textContent = t("copy"); }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => { btn.textContent = t("copy_failed"); });
    } }, t("copy"));
  }

  // Chunks in groups: builds far apart (a /fill at z = 10 million next to the base at spawn)
  // cannot share one map, every chunk would be smaller than a pixel. Chunks closer than
  // MAP_GAP chunks to each other end up in the same group.
  const MAP_GAP = 32;
  const MAP_PANELS = 8;
  function chunkGroups(dimMap) {
    const n = dimMap.x.length;
    const parent = Array.from({ length: n }, (_, i) => i);
    const find = (i) => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
    const cells = new Map();
    const cellOf = (x, z) => `${Math.floor(x / MAP_GAP)},${Math.floor(z / MAP_GAP)}`;
    for (let i = 0; i < n; i++) {
      const key = cellOf(dimMap.x[i], dimMap.z[i]);
      if (cells.has(key)) parent[find(i)] = find(cells.get(key)); else cells.set(key, i);
    }
    for (const [key, i] of cells) {
      const [cx, cz] = key.split(",").map(Number);
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
        const j = cells.get(`${cx + dx},${cz + dz}`);
        if (j !== undefined) parent[find(i)] = find(j);
      }
    }
    const groups = new Map();
    for (let i = 0; i < n; i++) {
      const root = find(i);
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root).push(i);
    }
    const built = (g) => g.reduce((sum, i) => sum + dimMap.built[i], 0);
    return [...groups.values()].sort((a, c) => built(c) - built(a) || c.length - a.length);
  }

  function bounds(dimMap, idx) {
    let x0 = Infinity; let x1 = -Infinity; let z0 = Infinity; let z1 = -Infinity;
    for (const i of idx) {
      x0 = Math.min(x0, dimMap.x[i]); x1 = Math.max(x1, dimMap.x[i]);
      z0 = Math.min(z0, dimMap.z[i]); z1 = Math.max(z1, dimMap.z[i]);
    }
    return { x0, x1, z0, z1 };
  }

  // numbered: [[site, number in the table], ...] for the sites inside this map.
  function drawMap(dimMap, idx, numbered, maxBuilt) {
    const byChunk = new Map(idx.map((i) => [`${dimMap.x[i]},${dimMap.z[i]}`, i]));
    const { x0, x1, z0, z1 } = bounds(dimMap, idx);
    const extent = Math.max(x1 - x0 + 1, z1 - z0 + 1);
    const r = Math.max(1.2, extent / 45);
    const pad = Math.ceil(r) + 2; // room for site numbers at the edge
    const vx = x0 - pad; const vz = z0 - pad;
    const vw = x1 - x0 + 1 + 2 * pad; const vh = z1 - z0 + 1 + 2 * pad;
    const svg = s("svg", { class: "chunk-map", viewBox: `${vx} ${vz} ${vw} ${vh}`, role: "img",
      "aria-label": t("map_aria", { dim: dimName(dimMap.key), n: idx.length }) });
    svg.append(s("rect", { x: vx, y: vz, width: vw, height: vh, fill: "var(--surface-2)" }));
    const logMax = Math.log1p(maxBuilt);
    for (const i of idx) {
      const b = dimMap.built[i];
      const cell = { x: dimMap.x[i], y: dimMap.z[i], width: 1, height: 1 };
      if (b >= 8) {
        const level = Math.log1p(b) / logMax;
        svg.append(s("rect", { ...cell, fill: "var(--accent)", "fill-opacity": (0.45 + 0.55 * level).toFixed(2) }));
      } else {
        svg.append(s("rect", { ...cell, fill: "var(--presence)" }));
      }
    }
    for (const [site, number] of numbered) {
      const cx = site.x / 16; const cz = site.z / 16;
      svg.append(s("circle", { cx, cy: cz, r, fill: "var(--surface)", stroke: "var(--ink)", "stroke-width": r / 5 }));
      const label = s("text", { x: cx, y: cz, "font-size": r * 1.2, "text-anchor": "middle", "dominant-baseline": "central", fill: "var(--ink)", "font-weight": 600 });
      label.textContent = String(number);
      svg.append(label);
    }
    svg.addEventListener("mousemove", (ev) => {
      const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());
      const cx = Math.floor(pt.x); const cz = Math.floor(pt.y);
      const i = byChunk.get(`${cx},${cz}`);
      const lines = [h("div", null, t("chunk_tip", { cx: String(cx), cz: String(cz), x0: String(cx * 16), x1: String(cx * 16 + 15), z0: String(cz * 16), z1: String(cz * 16 + 15) }))];
      if (i === undefined) lines.push(h("div", { class: "muted" }, t("chunk_nothing")));
      else {
        const b = dimMap.built[i];
        lines.push(h("div", null, b ? t("chunk_built", { b, below: dimMap.below[i] }) : t("nothing_built")));
        if (dimMap.minutes[i]) lines.push(h("div", { class: "muted" }, t("minutes_nearby", { n: dimMap.minutes[i] })));
      }
      tip.replaceChildren(...lines);
      placeTip(ev);
    });
    svg.addEventListener("mouseleave", hideTip);
    return svg;
  }

  // One map when everything is close together; otherwise a small map per group, the groups
  // with the most building first, each captioned with where it lies.
  function dimensionMaps(dimMap, sites) {
    const all = dimMap.x.map((_, i) => i);
    const maxBuilt = Math.max(1, ...dimMap.built);
    const numbered = sites.map(([site, number]) => [site, number]);
    const groups = chunkGroups(dimMap);
    const whole = bounds(dimMap, all);
    const span = Math.max(whole.x1 - whole.x0, whole.z1 - whole.z0) + 1;
    if (groups.length === 1 || span <= 4 * MAP_GAP) return [drawMap(dimMap, all, numbered, maxBuilt)];
    const shown = groups.filter((g, k) => k < MAP_PANELS && (k === 0 || g.some((i) => dimMap.built[i] >= 8)));
    const rest = groups.length - shown.length;
    const panels = shown.map((g) => {
      const box = bounds(dimMap, g);
      const inside = numbered.filter(([site]) => {
        const cx = Math.floor(site.x / 16); const cz = Math.floor(site.z / 16);
        return cx >= box.x0 - MAP_GAP && cx <= box.x1 + MAP_GAP && cz >= box.z0 - MAP_GAP && cz <= box.z1 + MAP_GAP;
      });
      const label = inside.length ? `${t("panel_sites", { n: inside.length, list: inside.map(([, n]) => n).join(", ") })} · ` : "";
      return h("figure", { class: "map-panel" },
        drawMap(dimMap, g, inside, maxBuilt),
        h("figcaption", null, `${label}x ${NUM.format(box.x0 * 16)} … ${NUM.format(box.x1 * 16 + 15)}, z ${NUM.format(box.z0 * 16)} … ${NUM.format(box.z1 * 16 + 15)}`));
    });
    return [
      h("p", { class: "folder" }, t("far_apart")),
      h("div", { class: "map-panels" }, panels),
      rest > 0 ? h("p", { class: "folder" }, t("more_spots", { n: rest })) : null,
    ];
  }

  function layerProfile(b) {
    const entries = Object.entries(b.by_section).map(([k, v]) => [Number(k), v]).sort((a, c) => c[0] - a[0]);
    if (!entries.length) return null;
    const max = Math.max(...entries.map(([, v]) => v));
    return h("div", { class: "layers", role: "img", "aria-label": t("layers_aria") },
      entries.map(([sec, v]) => h("div", { class: "layer", title: t("layer_title", { a: String(sec * 16), b: String(sec * 16 + 15), n: v }) },
        h("span", { class: "label" }, `y ${sec * 16}`),
        h("span", { class: "bar-track" }, h("span", { class: "bar", style: `width:${Math.max(0.5, (100 * v) / max).toFixed(1)}%` })),
        h("span", { class: "num" }, NUM.format(v)))));
  }

  function notCounted(b) {
    const notes = [];
    if (b.history_built) notes.push(t("nc_history", { n: b.history_built }));
    if (b.modded) notes.push(t("nc_modded", { n: b.modded, list: b.modded_blocks.slice(0, 4).map(([id]) => id.split(":")[1].replaceAll("_", " ")).join(", ") }));
    if (b.excluded_dimensions.length) notes.push(t("nc_excluded", { n: b.excluded_dimensions.length }));
    return notes.length ? h("p", { class: "folder" }, t("not_counted", { list: notes.join("; ") })) : null;
  }

  // What a flat map shows, from the build data itself (not from the 3D marker texts).
  function areaTitle(a) { return a.site === null || a.site === undefined ? t("spawn") : t("site_n", { n: a.site + 1 }); }
  function areaDetail(w, a) {
    const site = a.site === null || a.site === undefined || !w.build ? null : w.build.sites[a.site];
    if (!site) return null;
    const built = t("blocks_built", { n: site.built });
    return site.pct_below === null ? built : `${built}, ${t("pct_underground", { p: DEC.format(site.pct_below) })}`;
  }

  function viewsSection(w) {
    const items = [];
    for (const m of rendersOf(w)) {
      for (const [i, path] of Object.entries(m.images)) {
        const a = m.areas[i];
        const where = m.dimension === "minecraft:overworld" ? "" : ` · ${dimName(m.dimension)}`;
        const title = `${areaTitle(a)}${where}`;
        const detail = areaDetail(w, a);
        const img = h("img", { src: path, alt: t("top_view_of", { what: title }), loading: "lazy" });
        const link = SERVED ? view3d(m, i) : path;
        items.push(h("figure", { class: "view" },
          h("a", { href: link, target: "_blank", rel: "noopener", title: SERVED ? t("open_3d") : t("open_image") }, img),
          h("figcaption", null, h("b", null, title), detail ? ` · ${detail}` : null,
            SERVED ? [" · ", h("a", { href: link, target: "_blank", rel: "noopener" }, t("open_3d_link"))] : null)));
      }
    }
    if (!items.length) return null;
    return [h("h3", null, t("views_h")), h("div", { class: "views" }, items),
      h("p", { class: "folder" }, t("views_note"), SERVED ? t("views_3d") : t("views_serve"))];
  }

  // In-game maps: a mosaic per dimension with every filled map in its place, then loose maps.
  function mapsSection(w) {
    const m = w.in_game_maps;
    if (!m) return null;
    const base = `ingame/${w.world_id}/`;
    const figure = (src, title, detail) => h("figure", { class: "view" },
      h("a", { href: src, target: "_blank", rel: "noopener", title: t("open_image") },
        h("img", { src, alt: title, loading: "lazy" })),
      h("figcaption", null, h("b", null, title), detail ? ` · ${detail}` : null));
    const mosaics = m.mosaics.map((s) => figure(base + s.image, `${t("ingame_all")} · ${dimName(s.dimension)}`,
      `${t("ingame_placed", { n: s.maps })}, ${t("ingame_px", { n: s.blocks_per_pixel })}`));
    const loose = m.shown.filter((s) => s.image).map((s) => figure(base + s.image, t("ingame_map", { id: String(s.id) }),
      [t("ingame_around", { x: String(s.x), z: String(s.z) }),
        s.dimension === "minecraft:overworld" ? null : dimName(s.dimension),
        t("ingame_px", { n: 2 ** s.scale }),
        s.locked ? t("ingame_locked") : null].filter(Boolean).join(" · ")));
    const newest = loose.length && loose.length < m.filled ? t("ingame_newest", { n: loose.length }) : "";
    return [h("h3", null, t("ingame_h")),
      h("p", { class: "folder" }, t("ingame_intro", { n: m.total, f: m.filled }) + newest),
      mosaics.length ? h("div", { class: "views mosaics" }, mosaics) : null,
      loose.length ? h("div", { class: "views ingame" }, loose) : null];
  }

  function buildSection(w) {
    const b = w.build;
    if (!b) {
      const why = w.generator === "debug" ? t("why_debug") : w.format === "anvil" ? t("why_not_analyzed") : t("why_format");
      return [h("h3", null, t("building_h")), h("p", { class: "folder" }, why)];
    }
    const seen = seenSites();
    const mapBox = h("div", { class: "map-box" }, h("p", { class: "folder" }, t("map_loading")));
    const siteRows = b.sites.map((site, k) => {
      const key = siteKey(w, site);
      return h("tr", null,
        h("td", null, h("label", { class: "check" }, h("input", { type: "checkbox", checked: seen.has(key),
          onchange: (e) => setSeen(key, e.target.checked) }), ` ${k + 1}`)),
        h("td", null, `${site.dimension === "minecraft:overworld" ? "" : `${dimName(site.dimension)} `}x ${site.x}, z ${site.z}`),
        h("td", { class: "num" }, NUM.format(site.built)),
        h("td", { class: "num" }, pct(site.pct_below)),
        h("td", { class: "num" }, `${site.min_y} … ${site.max_y}`),
        h("td", { class: "num" }, site.chunks),
        h("td", { class: "num" }, site.hours_nearby ? hours(site.hours_nearby) : "–"),
        h("td", null, h("code", null, tpCommand(site)), " ", copyButton(tpCommand(site))),
        SERVED ? h("td", null, (() => {
          const view = siteView(w, k);
          return view ? h("a", { href: view3d(...view), target: "_blank", rel: "noopener" }, "3D") : "–";
        })()) : null);
    });
    const sitesTable = b.sites.length ? h("table", { class: "plain sites" },
      h("thead", null, h("tr", null, ["sc_seen", "sc_where", "sc_blocks", "sc_underground", "sc_height", "sc_chunks", "sc_nearby", "sc_teleport"]
        .map((c, i) => h("th", { class: i >= 2 && i <= 6 ? "num" : null }, t(c))), SERVED ? h("th", null, "3D") : null)),
      h("tbody", null, siteRows)) : h("p", { class: "folder" }, t("no_sites"));

    loadMap(w.world_id).then((data) => {
      const dims = data ? data.dimensions.filter((d) => d.x.length) : [];
      if (!dims.length) { mapBox.replaceChildren(h("p", { class: "folder" }, t("no_map_data"))); return; }
      let current = dims.find((d) => d.key === (b.main_dimension || "minecraft:overworld")) || dims[0];
      const show = () => {
        const sites = b.sites.map((x, k) => [x, k + 1]).filter(([x]) => x.dimension === current.key);
        const picker = dims.length > 1 ? h("div", { class: "map-dims" }, dims.map((d) => h("button", {
          type: "button", class: d === current ? "ghost small active" : "ghost small",
          onclick: () => { current = d; show(); } }, dimName(d.key)))) : null;
        mapBox.replaceChildren(...[picker, ...dimensionMaps(current, sites), h("p", { class: "folder" }, t("map_legend"))].filter(Boolean));
      };
      show();
    });

    const blocks = b.top_blocks.length ? h("div", { class: "chips" }, b.top_blocks.map(([id, n]) =>
      h("span", { class: "badge" }, `${blockName(id)} `, h("b", null, NUM.format(n))))) : null;
    const structs = Object.entries(b.structures);
    return [
      h("h3", null, t("building_h")),
      h("div", { class: "stats" },
        stat(t("stat_built"), t("n_blocks", { n: b.built })),
        stat(t("stat_underground"), pct(b.pct_below)),
        stat(t("stat_built_chunks"), NUM.format(b.built_chunks)),
        stat(t("sites_h"), NUM.format(b.sites.length))),
      h("p", { class: "folder" }, t("build_explain")),
      notCounted(b),
      h("h3", null, t("where_h")), mapBox,
      h("h3", null, t("sites_h")), sitesTable,
      h("p", { class: "folder" }, t("seen_note")),
      layerProfile(b) ? [h("h3", null, t("height_profile")), layerProfile(b)] : null,
      blocks ? [h("h3", null, t("top_blocks_h")), blocks] : null,
      structs.length ? h("p", { class: "folder" }, t("structures_line"),
        structs.map(([k, v]) => `${structureName(k)} (${t("n_chunks", { n: v })})`).join(", "),
        b.structure_built ? t("structures_total", { n: b.structure_built }) : ".") : null,
    ];
  }

  function textSection(w) {
    if (!w._texts.length) return null;
    const matches = new Set(textMatches(w));
    const ordered = [...w._texts].sort((a, b) => (matches.has(b) - matches.has(a)) || (a[7] - b[7]) || a[0].localeCompare(b[0]));
    const makers = w._texts.filter((x) => x[7]).length;
    const rows = ordered.map((x) => {
      const [kind, text, holder, dim, px, py, pz] = x;
      const where = px === null ? holder : `${holder} · ${dim && dim !== "minecraft:overworld" ? `${dimName(dim)} ` : ""}${px}, ${py}, ${pz}`;
      const tp = px === null ? null : `/execute in ${dim || "minecraft:overworld"} run tp @s ${px} ${py + 1} ${pz}`;
      return h("tr", { class: matches.has(x) ? "match" : null },
        h("td", null, kindName(kind), x[7] ? h("div", { class: "folder" }, t("from_makers")) : null),
        h("td", { class: "text" }, text.length > 400 ? h("details", null, h("summary", null, snippet(text)), text) : text),
        h("td", null, where),
        h("td", null, tp ? copyButton(tp) : null));
    });
    const tbl = h("table", { class: "plain texts" },
      h("thead", null, h("tr", null, ["tc_kind", "tc_text", "tc_where", "tc_teleport"].map((c) => h("th", null, t(c))))),
      h("tbody", null, rows));
    return [h("h3", null, t("texts_h", { n: w._texts.length })),
      matches.size ? h("p", { class: "folder" }, t("texts_match", { n: matches.size })) : null,
      makers ? h("p", { class: "folder" }, t("texts_makers", { n: makers })) : null,
      w._texts.length > 60 ? h("details", { open: matches.size > 0 }, h("summary", null, t("texts_all", { n: w._texts.length })), tbl) : tbl];
  }

  function noteView(w) {
    const n = w._note;
    const box = h("section", { class: "note-box" });
    const edit = () => box.replaceChildren(...noteEditor(w));
    const editButton = notesWritable
      ? h("button", { type: "button", class: "ghost small", onclick: edit }, n ? t("edit_note") : t("add_note"))
      : null;
    if (!n) {
      box.append(h("div", { class: "note-head" }, h("span", { class: "folder" }, notesWritable ? t("no_note_yet") : t("no_note_how")),
        editButton));
      return box;
    }
    box.append(
      h("div", { class: "note-head" },
        h("div", null, h("b", null, n.title || t("note")), n.rating ? ` ${"★".repeat(n.rating)}` : null),
        editButton),
      n.tags.length ? h("div", { class: "badges" }, n.tags.map((tag) => h("span", { class: "badge" }, tag))) : null,
      n.note ? h("div", { class: "note-text" }, n.note) : null,
      n.updated ? h("div", { class: "folder" }, t("note_updated", { date: NOTE_DATE.format(new Date(n.updated)) })) : null);
    return box;
  }

  function noteEditor(w) {
    const n = w._note || { title: "", note: "", tags: [], rating: null };
    const title = h("input", { type: "text", value: n.title, maxlength: 200, placeholder: t("ph_title") });
    const tags = h("input", { type: "text", value: n.tags.join(", "), placeholder: t("ph_tags") });
    const rating = h("select", null, h("option", { value: "" }, "–"),
      [1, 2, 3, 4, 5].map((r) => h("option", { value: r, selected: n.rating === r }, "★".repeat(r))));
    const text = h("textarea", { rows: 6, placeholder: t("ph_note") });
    text.value = n.note;
    const status = h("span", { class: "folder" });
    const save = h("button", { type: "button", class: "primary", onclick: async () => {
      save.disabled = true; status.textContent = t("saving");
      const body = {
        title: title.value.trim(), note: text.value,
        tags: tags.value.split(",").map((x) => x.trim()).filter(Boolean),
        rating: rating.value ? Number(rating.value) : null,
      };
      try {
        const r = await fetch(`api/notes/${encodeURIComponent(w.world_id)}`, {
          method: "POST", headers: { "Content-Type": "application/json", "X-Mcatlas": "1" }, body: JSON.stringify(body) });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || r.statusText);
        setNote(w, data.annotation);
        render();
        openDetail(w);
      } catch (e) {
        status.textContent = t("not_saved", { msg: e.message });
        save.disabled = false;
      }
    } }, t("save"));
    const cancel = h("button", { type: "button", class: "ghost", onclick: () => openDetail(w) }, t("cancel"));
    return [
      h("label", { class: "field" }, t("f_title"), title),
      h("label", { class: "field" }, t("f_tags"), tags),
      h("label", { class: "field" }, t("f_rating"), rating),
      h("label", { class: "field" }, t("f_note"), text),
      h("div", { class: "note-actions" }, save, cancel, status),
      h("p", { class: "folder" }, t("note_stored")),
    ];
  }

  let openWorld = null;
  function openDetail(w) {
    openWorld = w;
    const a = w.activity;
    const body = $("#detail-body");
    const close = h("button", { class: "ghost close", type: "button", onclick: closeDetail }, t("close"));
    const comps = Object.entries(w.importance.components)
      .map(([k, v]) => `${t(`imp_${k}`)} ${DEC.format(v)}`)
      .join(" + ");

    const players = w.players.length ? h("table", { class: "plain" },
      h("thead", null, h("tr", null, ["pc_player", "pc_play", "pc_sessions", "pc_items", "pc_adv", "pc_mode", "pc_position"]
        .map((c, i) => h("th", { class: i && i < 5 ? "num" : null }, t(c))))),
      h("tbody", null, w.players.map((p) => h("tr", null,
        h("td", { title: p.uuid }, p.name || t("unknown_player", { id: p.uuid.slice(0, 8) })),
        h("td", { class: "num" }, p.play_hours ? hours(p.play_hours) : "–"),
        h("td", { class: "num" }, p.sessions ?? "–"),
        h("td", { class: "num" }, p.items_used ? NUM.format(p.items_used) : "–"),
        h("td", { class: "num" }, p.advancements || "–"),
        h("td", null, p.game_mode !== null && p.game_mode !== undefined ? modeName(p.game_mode) : "–"),
        h("td", null, p.position ? `${(p.dimension || "").replace("minecraft:", "")} ${p.position.map((x) => Math.round(x)).join(", ")}` : "–"))))) : h("p", { class: "folder" }, t("no_players"));

    const dims = w.dimensions.length ? h("table", { class: "plain" },
      h("thead", null, h("tr", null, h("th", null, t("dc_dimension")), h("th", { class: "num" }, t("dc_chunks")), h("th", { class: "num" }, t("dc_regions")), h("th", null, t("dc_area")))),
      h("tbody", null, w.dimensions.map((d) => h("tr", null,
        h("td", null, d.key.replace("minecraft:", "")),
        h("td", { class: "num" }, NUM.format(d.chunks)),
        h("td", { class: "num" }, d.region_files),
        h("td", null, d.bbox_chunks ? `x ${d.bbox_chunks[0] * 16} … ${d.bbox_chunks[2] * 16 + 15}, z ${d.bbox_chunks[1] * 16} … ${d.bbox_chunks[3] * 16 + 15}` : "–"))))) : null;

    const dayRows = w._days.slice().reverse().map((d) => h("tr", null,
      h("td", null, fmtDay(d.d)),
      h("td", { class: "num" }, d.sig.chunk_saves || "–"),
      h("td", { class: "num" }, d.sig.file_saves || "–"),
      h("td", { class: "num" }, d.sig.advancements || "–"),
      h("td", null, d.sig.last_played ? t("last_played_only") : "")));

    const related = w.related.length ? h("ul", null, w.related.map((r) => h("li", null,
      h("a", { class: "rel", onclick: () => { const o = byId.get(r.world_id); if (o) openDetail(o); } }, r.folder_name),
      ` — ${t("related_share", { p: String(Math.round(r.similarity * 100)) })}`))) : null;

    body.replaceChildren(...[
      h("div", { class: "detail-head" },
        icon(w, "icon"),
        h("div", null,
          h("h2", { id: "detail-title" }, w.name),
          h("div", { class: "folder" }, w.relpath),
          badges(w)),
        close),
      noteView(w),
      viewsSection(w),
      h("div", { class: "stats" },
        stat(t("st_days"), daysRange(w)),
        stat(t("st_period"), a.span_days ? t("st_period_value", { n: a.span_days }) : "–"),
        stat(t("st_months"), NUM.format(a.active_months)),
        stat(w.foreign_players ? t("st_play_own") : t("st_play"), w.play_hours ? hours(w.play_hours) : "–"),
        stat(t("st_sessions"), w.sessions ? NUM.format(w.sessions) : "–"),
        stat(t("st_items"), w.items_used ? NUM.format(w.items_used) : "–"),
        stat(t("st_chunks"), NUM.format(w.chunks)),
        stat(t("st_size"), bytes(w.size_bytes))),
      h("h3", null, t("activity_per_week")),
      strip(w, "big-strip", 90),
      monthTicks(),
      h("p", { class: "folder" }, t("activity_explain", { period: period(w) }), t("lower_bound"),
        extraDays(w) > 0 ? t("sessions_upper", { s: w.sessions, d: w.days_upper }) : null),
      historyNote(w),
      buildSection(w),
      mapsSection(w),
      textSection(w),
      h("h3", null, t("properties_h")),
      kv([
        [t("kv_version"), w.version_name ? `${w.version_name}${w.data_version ? ` ${t("kv_data", { n: String(w.data_version) })}` : ""}` : null],
        [t("kv_mode"), w.game_mode !== null && w.game_mode !== undefined ? modeName(w.game_mode) : null],
        [t("kv_type"), `${generatorName(w.generator)}${w.generator_detail ? ` — ${w.generator_detail}` : ""}`],
        [t("kv_cheats"), w.cheats === null ? null : (w.cheats ? t("on") : t("off"))],
        [t("kv_seed"), w.seed !== null && w.seed !== undefined ? String(w.seed) : null],
        [t("kv_last_played"), w.last_played ? DATE.format(new Date(w.last_played)) : null],
        [t("kv_datapacks"), w.datapacks.length ? w.datapacks.join(", ") : null],
        [t("kv_session"), w.hours_per_session ? `${t("kv_session_value", { h: hours(w.hours_per_session) })}${w.afk_suspect ? t("kv_afk") : ""}` : null],
        [t("kv_maps"), w.map_items || null],
        [t("kv_files"), `${NUM.format(w.files)} (${bytes(w.size_bytes)})`],
        [t("kv_score"), `${DEC.format(w.importance.score)} = ${comps}`],
        [t("kv_source"), `${w.source_id}: ${w.relpath}`],
      ]),
      h("h3", null, t("players_h")), players,
      dims ? [h("h3", null, t("dims_h")), dims] : null,
      related ? [h("h3", null, t("related_h")), related] : null,
      w._days.length ? h("details", null, h("summary", null, t("all_days", { n: w._days.length })),
        h("table", { class: "plain" },
          h("thead", null, h("tr", null, h("th", null, t("dayc_day")), h("th", { class: "num" }, t("dayc_chunks")),
            h("th", { class: "num" }, t("dayc_files")), h("th", { class: "num" }, t("dayc_adv")), h("th", null, ""))),
          h("tbody", null, dayRows))) : null,
      w.errors.length ? [h("h3", null, t("errors_h")), h("div", { class: "errors" }, w.errors.join("\n"))] : null,
    ].flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
    const dlg = $("#detail");
    if (!dlg.open) dlg.showModal();
    dlg.scrollTop = 0;
    setHash();
  }
  // Tidy up after the world closes: the tooltip back to the page, the world out of the URL.
  function afterClose() { hideTip(); document.body.append(tip); setHash(); }
  function closeDetail() { $("#detail").close(); afterClose(); }
  $("#detail").addEventListener("close", afterClose);  // also Esc, which closes it natively
  $("#detail").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeDetail(); });

  // ---------- wiring ----------
  $("#lang").addEventListener("change", (e) => {
    lang = known(e.target.value) || "en";
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* storage unavailable */ }
    setFormats();
    applyStaticTexts();
    fillFilters();
    render();
    if ($("#detail").open && openWorld) openDetail(openWorld);
  });
  $("#q").addEventListener("input", (e) => { state.q = e.target.value; render(); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
  $("#f-version").addEventListener("change", (e) => { state.version = e.target.value; render(); });
  $("#f-mode").addEventListener("change", (e) => { state.mode = e.target.value; render(); });
  $("#f-player").addEventListener("change", (e) => { state.player = e.target.value; render(); });
  $("#f-generator").addEventListener("change", (e) => { state.generator = e.target.value; render(); });
  $("#f-copies").addEventListener("change", (e) => { state.hideCopies = e.target.checked; render(); });
  $("#f-noted").addEventListener("change", (e) => { state.onlyNoted = e.target.checked; render(); });
  $("#f-downloaded").addEventListener("change", (e) => { state.hideDownloaded = e.target.checked; render(); });
  $("#f-underground").addEventListener("change", (e) => { state.underground = e.target.value; render(); });
  for (const btn of document.querySelectorAll(".view-toggle button")) {
    btn.addEventListener("click", () => {
      state.view = btn.dataset.view;
      for (const b of document.querySelectorAll(".view-toggle button")) b.classList.toggle("active", b === btn);
      render();
    });
  }

  // The table header sticks just below the (sticky) controls, however many rows they wrap to.
  const controls = document.querySelector(".controls");
  const stickBelowControls = () => document.documentElement.style.setProperty("--controls-height", `${controls.offsetHeight}px`);
  stickBelowControls();
  if (window.ResizeObserver) new ResizeObserver(stickBelowControls).observe(controls);

  const dayInput = (el) => (/^\d{4}-\d{2}-\d{2}$/.test(el.value) ? parseDay(el.value) : null);
  for (const el of [$("#t-from"), $("#t-to")]) {
    if (CATALOG.first_day) { el.min = CATALOG.first_day; el.max = CATALOG.last_day; }
    el.addEventListener("change", () => { setRange(dayInput($("#t-from")), dayInput($("#t-to"))); setHash(); render(); });
  }
  $("#t-clear").addEventListener("click", () => { setRange(null, null); setHash(); render(); });

  // #from=…&to=… (older links used the Dutch #van=…&tot=…), #q=… and #w=<world id>.
  const params = new URLSearchParams(location.hash.slice(1));
  const hashDay = (...keys) => {
    const v = keys.map((k) => params.get(k)).find(Boolean) || "";
    return /^\d{4}-\d{2}-\d{2}$/.test(v) ? parseDay(v) : null;
  };
  setRange(hashDay("from", "van"), hashDay("to", "tot"));
  if (params.get("q")) { state.q = params.get("q"); $("#q").value = state.q; }
  render();
  loadTexts();
  checkNotesApi();
  const wanted = params.get("w");
  if (wanted && byId.has(wanted)) openDetail(byId.get(wanted));
})();
