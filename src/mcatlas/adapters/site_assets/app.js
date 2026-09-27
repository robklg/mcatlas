"use strict";
(() => {
  const CATALOG = window.MCATLAS_CATALOG;
  const NOTES = window.MCATLAS_ANNOTATIONS || {};
  const $ = (sel) => document.querySelector(sel);
  const NUM = new Intl.NumberFormat("nl-NL");
  const DEC = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 1 });
  const DATE = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const MONTH = new Intl.DateTimeFormat("nl-NL", { month: "short", timeZone: "UTC" });
  const DAY_MS = 86400000;
  const WEEK_MS = 7 * DAY_MS;

  const blockName = (id) => id.replace(/^minecraft:/, "").replaceAll("_", " ");
  const MODES = { 0: "Overleven", 1: "Creatief", 2: "Avontuur", 3: "Toeschouwer" };
  const GENERATORS = {
    default: "Normaal", flat: "Superflat", void: "Leeg (void)", amplified: "Amplified",
    large_biomes: "Grote biomen", single_biome: "Eén bioom", debug: "Debug",
    custom: "Aangepast", unknown: "Onbekend",
  };
  const FORMATS = {
    anvil: null, mcregion: "Oud formaat (Beta)", no_terrain: "Geen terrein",
    no_level_dat: "Geen level.dat", empty: "Lege map",
  };

  // ---------- 3D maps (BlueMap); the viewer only works through `mcatlas serve` ----------
  const SERVED = location.protocol.startsWith("http");
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
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute("data-theme", t);
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
    $("#summary").textContent = "Geen catalogus gevonden (data/catalog.js ontbreekt).";
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
    w._search = n ? `${w._baseSearch} ${[n.title, n.note, ...n.tags].join(" ").toLocaleLowerCase("nl")}` : w._baseSearch;
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
    w._family = m ? `${m[1]}.${m[2]}` : (w.version_name ? "snapshot/overig" : "onbekend");
    w._playerNames = w.players.map((p) => p.name || p.uuid.slice(0, 8));
    const topBlocks = w.build ? w.build.top_blocks.map(([id]) => blockName(id)) : [];
    w._downloaded = Object.keys(w.activity.history || {}).length > 0;
    w._baseSearch = null;
    w._texts = [];
    w._textSearch = "";
    w._baseSearch = [w.name, w.folder_name, w.level_name, w.relpath, ...w._playerNames, ...topBlocks]
      .filter(Boolean).join(" ").toLocaleLowerCase("nl");
    setNote(w, NOTES[w.world_id] || null);
  }
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
    if (!a.first_day) return "geen datums";
    if (a.first_day === a.last_day) return fmtDay(a.first_day);
    return `${fmtDay(a.first_day)} – ${fmtDay(a.last_day)}`;
  }
  const hours = (x) => `${DEC.format(x)} u`;

  // ---------- time range: worlds with activity between two days ----------
  const isoDay = (t) => new Date(t).toISOString().slice(0, 10);
  const hasRange = () => state.from !== null || state.to !== null;
  const inRange = (t) => (state.from === null || t >= state.from) && (state.to === null || t <= state.to);
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
      "aria-label": `Activiteit per week: ${w.activity.distinct_days} actieve dagen, ${period(w)}` });
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
      showBinTip(w, i, ev);
    });
    svg.addEventListener("mouseleave", hideTip);
    wrap.append(svg);
    return wrap;
  }

  const tip = $("#tooltip");
  function showBinTip(w, i, ev) {
    const start = axisStart + i * WEEK_MS;
    const bin = w._bins[i];
    tip.replaceChildren(
      h("div", null, `Week van ${DATE.format(new Date(start))}`),
      bin
        ? h("div", null, `${bin.length} actieve ${bin.length === 1 ? "dag" : "dagen"}: `,
            bin.map((d) => DATE.format(new Date(d.t)).replace(/ \d{4}$/, "")).join(", "))
        : h("div", { class: "muted" }, "geen activiteit"),
    );
    tip.hidden = false;
    const x = Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${x}px`;
    tip.style.top = `${ev.clientY + 14}px`;
  }
  function hideTip() { tip.hidden = true; }

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
    if (w.game_mode !== null && w.game_mode !== undefined) list.push(h("span", { class: "badge" }, MODES[w.game_mode]));
    if (w.generator && w.generator !== "default") list.push(h("span", { class: "badge" }, GENERATORS[w.generator] || w.generator));
    if (FORMATS[w.format]) list.push(h("span", { class: "badge warn" }, FORMATS[w.format]));
    if (w.hardcore) list.push(h("span", { class: "badge" }, "Hardcore"));
    if (w.modded) list.push(h("span", { class: "badge" }, "Mods"));
    if (w.afk_suspect) list.push(h("span", { class: "badge warn", title: `Gemiddeld ${hours(w.hours_per_session)} per sessie: het spel heeft waarschijnlijk lang aan gestaan, dus de speeltijd is te hoog` }, "mogelijk AFK"));
    if (w._copyOf) list.push(h("span", { class: "badge", title: `Deelt geschiedenis met ${w._copyOf.folder_name}` }, "kopie"));
    if (Object.keys(w.activity.history || {}).length) {
      list.push(h("span", { class: "badge", title: "Bevat activiteit van vóór onze spelers, bijvoorbeeld van de makers van een gedownloade map" }, "met voorgeschiedenis"));
    }
    return h("div", { class: "badges" }, list);
  }

  // ---------- controls ----------
  const state = { from: null, to: null, q: "", sort: "importance", version: "", mode: "", player: "", generator: "", underground: "", hideCopies: false, hideDownloaded: false, onlyNoted: false, view: "cards" };

  function fillSelect(sel, values, label) {
    for (const v of values) sel.append(h("option", { value: v }, label ? label(v) : v));
  }
  const uniq = (xs) => [...new Set(xs)].sort((a, b) => String(a).localeCompare(String(b), "nl", { numeric: true }));
  fillSelect($("#f-version"), uniq(CATALOG.worlds.map((w) => w._family)));
  fillSelect($("#f-mode"), uniq(CATALOG.worlds.map((w) => w.game_mode).filter((m) => m !== null)), (m) => MODES[m]);
  fillSelect($("#f-player"), uniq(CATALOG.worlds.flatMap((w) => w._playerNames)));
  fillSelect($("#f-generator"), uniq(CATALOG.worlds.map((w) => w.generator)), (g) => GENERATORS[g] || g);

  const DAYS_NOTE = "Ondergrens: dagen met een datum als bewijs. Bovengrens: het aantal sessies (leave_game), want elke speeldag heeft er minstens één.";
  const extraDays = (w) => (w.days_upper ? w.days_upper - w.activity.distinct_days : 0);
  function daysText(w, unit) {
    const n = w.activity.distinct_days;
    const base = unit ? `${NUM.format(n)} ${n === 1 ? "dag" : "dagen"}` : NUM.format(n);
    return extraDays(w) > 0 ? `${base} (max. ~${NUM.format(w.days_upper)})` : base;
  }

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
    name: (w) => w.name.toLocaleLowerCase("nl"),
    inRange: (w) => -daysInRange(w),
  };

  // `ignoreRange`: every other filter, for the overview timeline that picks the range.
  function visibleWorlds(ignoreRange = false) {
    const terms = state.q.toLocaleLowerCase("nl").split(/\s+/).filter(Boolean);
    const key = SORTS[state.sort];
    return CATALOG.worlds
      .filter((w) => ignoreRange || !hasRange() || w._days.some((d) => inRange(d.t)))
      .filter((w) => terms.every((t) => w._search.includes(t) || w._textSearch.includes(t)))
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
        return a.name.localeCompare(b.name, "nl");
      });
  }

  // ---------- texts: signs, books, names, commands (loaded after the page) ----------
  const TEXT_KINDS = { sign: "bordje", book: "boek", name: "naam", command: "commando" };
  const TEXT_PLURAL = { sign: "bordjes", book: "boeken", name: "namen", command: "commando's" };
  function textSummary(w) {
    const parts = Object.entries(w.text_counts || {}).sort((a, b) => b[1] - a[1])
      .map(([k, n]) => `${NUM.format(n)} ${n === 1 ? TEXT_KINDS[k] : TEXT_PLURAL[k]}`);
    return parts.length ? `Teksten: ${parts.join(", ")}` : null;
  }
  const queryTerms = () => state.q.toLocaleLowerCase("nl").split(/\s+/).filter(Boolean);
  function textMatches(w) {
    const terms = queryTerms();
    if (!terms.length) return [];
    return w._texts.filter((t) => { if (t[7]) return false; const low = t[1].toLocaleLowerCase("nl"); return terms.some((q) => low.includes(q)); });
  }
  function textHit(w) {
    const terms = queryTerms();
    if (!terms.length || terms.every((q) => w._search.includes(q))) return null;
    return textMatches(w)[0] || null;
  }
  function snippet(text) {
    const flat = text.replace(/\s+/g, " ");
    const terms = queryTerms();
    const low = flat.toLocaleLowerCase("nl");
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
        w._textSearch = w._texts.filter((t) => !t[7]).map((t) => t[1]).join("\n").toLocaleLowerCase("nl");
      }
      render();
      if ($("#detail").open && openWorld) openDetail(openWorld);
    };
    document.head.append(el);
  }

  // ---------- views ----------
  function card(w) {
    const facts = h("div", { class: "facts" },
      hasRange() ? [h("b", { class: "in-range" }, `${NUM.format(daysInRange(w))} ${daysInRange(w) === 1 ? "dag" : "dagen"} in de gekozen periode`), " · "] : null,
      h("b", { title: DAYS_NOTE }, daysText(w, true)), " · ",
      period(w),
      w.play_hours ? [" · ", h("b", null, hours(w.play_hours))] : null,
      w.items_used ? [" · ", NUM.format(w.items_used), " items"] : null,
      w.build && w.build.built ? [" · ", h("b", null, `${NUM.format(w.build.built)} blokken gebouwd`),
        w.build.pct_below !== null ? ` (${DEC.format(w.build.pct_below)}% onder de grond)` : null] : null,
      " · ", bytes(w.size_bytes));
    const names = w._playerNames.length ? `Spelers: ${w._playerNames.join(", ")}` : null;
    const hit = textHit(w);
    return h("article", { class: "card", tabindex: 0, role: "button", "aria-label": `Open ${w.name}`,
      onclick: () => openDetail(w), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(w); } } },
      icon(w),
      h("div", null,
        h("div", { class: "name" }, w.name),
        w.name !== w.folder_name ? h("div", { class: "folder" }, w.folder_name) : null,
        badges(w)),
      facts,
      strip(w, "strip", 28),
      w._note ? h("div", { class: "note-line" }, h("b", null, w._note.title || "Notitie"),
        w._note.rating ? ` ${"★".repeat(w._note.rating)}` : null,
        w._note.tags.length ? h("span", { class: "folder" }, ` · ${w._note.tags.join(", ")}`) : null) : null,
      hit ? h("div", { class: "hit" }, `${TEXT_KINDS[hit[0]]}: `, h("q", null, snippet(hit[1]))) : null,
      textSummary(w) ? h("div", { class: "people" }, textSummary(w)) : null,
      names ? h("div", { class: "people" }, names) : null);
  }

  function table(worlds) {
    const cols = [
      ["Naam", "name"], ["Dagen", "days"], ["Periode", "first"], ["Speeltijd", "play"],
      ["Items", "used"], ["Grootte", "size"], ["Versie", null], ["Activiteit", null],
    ];
    const head = h("tr", null, cols.map(([label, key]) => h("th", {
      onclick: key ? () => { state.sort = key; $("#sort").value = key; render(); } : null,
      "aria-sort": key && state.sort === key ? "descending" : null,
    }, label)));
    const rows = worlds.map((w) => h("tr", { onclick: () => openDetail(w) },
      h("td", null, w.name, w.name !== w.folder_name ? h("div", { class: "folder" }, w.folder_name) : null),
      h("td", { class: "num", title: DAYS_NOTE }, extraDays(w) > 0 ? `${NUM.format(w.activity.distinct_days)}–${NUM.format(w.days_upper)}` : NUM.format(w.activity.distinct_days)),
      h("td", null, period(w)),
      h("td", { class: "num" }, w.play_hours ? hours(w.play_hours) : "–"),
      h("td", { class: "num" }, w.items_used ? NUM.format(w.items_used) : "–"),
      h("td", { class: "num" }, bytes(w.size_bytes)),
      h("td", null, w.version_name || "–"),
      h("td", null, strip(w, "strip", 20))));
    return h("table", { class: "worlds" }, h("thead", null, head), h("tbody", null, rows));
  }

  function render() {
    const worlds = visibleWorlds();
    const list = $("#list");
    list.className = state.view === "cards" ? "cards" : "";
    if (!worlds.length) {
      list.replaceChildren(h("p", { class: "empty" }, "Geen werelden gevonden met deze filters."));
    } else if (state.view === "cards") {
      list.replaceChildren(...worlds.map(card));
    } else {
      list.replaceChildren(table(worlds));
    }
    renderTimeline();
    const total = CATALOG.worlds.length;
    const range = hasRange() ? ` actief ${rangeText()}` : "";
    const span = CATALOG.first_day ? ` · ${fmtDay(CATALOG.first_day)} – ${fmtDay(CATALOG.last_day)}` : "";
    const ignored = (CATALOG.ignored_file_days || []).length
      ? ` · bestandsdatums van ${CATALOG.ignored_file_days.map(fmtDay).join(", ")} genegeerd (archiefkopie)` : "";
    $("#summary").textContent = `${worlds.length} van ${total} werelden${range}${span}${ignored}`;
  }

  // ---------- overview timeline: pick a range by dragging ----------
  function rangeText() {
    if (state.from !== null && state.to !== null) return `van ${DATE.format(new Date(state.from))} tot en met ${DATE.format(new Date(state.to))}`;
    return state.from !== null ? `vanaf ${DATE.format(new Date(state.from))}` : `tot en met ${DATE.format(new Date(state.to))}`;
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
    if (state.from !== null) p.set("van", isoDay(state.from));
    if (state.to !== null) p.set("tot", isoDay(state.to));
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
      "aria-label": "Aantal werelden met activiteit per week; sleep om een periode te kiezen" });
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
        h("div", null, `Week van ${DATE.format(new Date(axisStart + i * WEEK_MS))}`),
        counts[i] ? h("div", null, `${counts[i]} ${counts[i] === 1 ? "wereld" : "werelden"} actief`) : h("div", { class: "muted" }, "geen activiteit"));
      tip.hidden = false;
      tip.style.left = `${Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8)}px`;
      tip.style.top = `${ev.clientY + 14}px`;
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
      const t = Date.UTC(y, m, 1);
      if (t > lastMs) break;
      if (m % every !== 0) continue;
      const frac = (t - axisStart) / (binCount * WEEK_MS);
      const label = m === 0 ? String(y) : MONTH.format(new Date(t));
      row.append(h("span", { style: `position:absolute;left:${(frac * 100).toFixed(2)}%;transform:translateX(-50%)` }, label));
    }
    return row;
  }

  function historyNote(w) {
    const hist = Object.keys(w.activity.history || {}).sort();
    const notes = [];
    if (hist.length) {
      notes.push(`Voorgeschiedenis: ${hist.length} ${hist.length === 1 ? "dag" : "dagen"} activiteit tussen ${fmtDay(hist[0])} en ${fmtDay(hist[hist.length - 1])}, ` +
        "van vóór onze eerste advancement (waarschijnlijk de makers van deze map). Die tellen niet mee.");
    }
    if (w.foreign_players) {
      notes.push(`${w.foreign_players} onbekende ${w.foreign_players === 1 ? "speler" : "spelers"} met samen ${hours(Math.max(0, w.play_hours_all - w.play_hours))} speeltijd; ` +
        "die telt niet mee in de score zolang er eigen spelers zijn.");
    }
    return notes.length ? h("p", { class: "folder" }, notes.join(" ")) : null;
  }

  // ---------- build (tier 2): what was built, and where ----------
  const DIMS = { "minecraft:overworld": "Bovenwereld", "minecraft:the_nether": "Nether", "minecraft:the_end": "End" };
  const dimName = (k) => DIMS[k] || k.replace(/^minecraft:/, "");
  const STRUCTURES = [
    [/^mineshaft/, "mijnschacht"], [/^village/, "dorp"], [/^ancient_city/, "oude stad"], [/^dungeon/, "kerker"],
    [/^stronghold/, "fort"], [/^pillager_outpost/, "plunderaarsbuitenpost"], [/^ruined_portal/, "verwoest portaal"],
    [/^ocean_ruin/, "oceaanruïne"], [/^shipwreck/, "scheepswrak"], [/^buried_treasure/, "begraven schat"],
    [/^desert_pyramid/, "woestijntempel"], [/^jungle_pyramid/, "jungletempel"], [/^igloo/, "iglo"],
    [/^swamp_hut/, "heksenhut"], [/^mansion/, "landhuis"], [/^monument/, "oceaanmonument"],
    [/^fortress/, "Netherfort"], [/^bastion/, "bastion"], [/^end_city/, "Endstad"], [/^trail_ruins/, "spoorruïnes"],
    [/^trial_chambers/, "beproevingskamers"],
  ];
  const structureName = (k) => (STRUCTURES.find(([re]) => re.test(k)) || [null, k.replaceAll("_", " ")])[1];
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
      const done = () => { btn.textContent = "gekopieerd"; setTimeout(() => { btn.textContent = "kopieer"; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => { btn.textContent = "lukt niet"; });
    } }, "kopieer");
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
      "aria-label": `Kaart van ${dimName(dimMap.key)}: ${idx.length} chunks met bouwwerk of aanwezigheid` });
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
      const t = s("text", { x: cx, y: cz, "font-size": r * 1.2, "text-anchor": "middle", "dominant-baseline": "central", fill: "var(--ink)", "font-weight": 600 });
      t.textContent = String(number);
      svg.append(t);
    }
    svg.addEventListener("mousemove", (ev) => {
      const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());
      const cx = Math.floor(pt.x); const cz = Math.floor(pt.y);
      const i = byChunk.get(`${cx},${cz}`);
      const lines = [h("div", null, `Chunk ${cx}, ${cz} · blokken x ${cx * 16}…${cx * 16 + 15}, z ${cz * 16}…${cz * 16 + 15}`)];
      if (i === undefined) lines.push(h("div", { class: "muted" }, "niets gebouwd, niet (lang) geweest"));
      else {
        const b = dimMap.built[i];
        lines.push(h("div", null, b ? `${NUM.format(b)} blokken gebouwd, waarvan ${NUM.format(dimMap.below[i])} onder de grond` : "niets gebouwd"));
        if (dimMap.minutes[i]) lines.push(h("div", { class: "muted" }, `${NUM.format(dimMap.minutes[i])} min spelers in de buurt`));
      }
      tip.replaceChildren(...lines);
      tip.hidden = false;
      tip.style.left = `${Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8)}px`;
      tip.style.top = `${ev.clientY + 14}px`;
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
      const label = inside.length ? `Plek ${inside.map(([, n]) => n).join(", ")} · ` : "";
      return h("figure", { class: "map-panel" },
        drawMap(dimMap, g, inside, maxBuilt),
        h("figcaption", null, `${label}x ${NUM.format(box.x0 * 16)} … ${NUM.format(box.x1 * 16 + 15)}, z ${NUM.format(box.z0 * 16)} … ${NUM.format(box.z1 * 16 + 15)}`));
    });
    return [
      h("p", { class: "folder" }, `Deze plekken liggen ver uit elkaar, daarom een kaartje per gebied (elk op eigen schaal).`),
      h("div", { class: "map-panels" }, panels),
      rest > 0 ? h("p", { class: "folder" }, `Plus ${NUM.format(rest)} ${rest === 1 ? "plekje" : "plekjes"} waar alleen even iemand is geweest.`) : null,
    ];
  }

  function layerProfile(b) {
    const entries = Object.entries(b.by_section).map(([k, v]) => [Number(k), v]).sort((a, c) => c[0] - a[0]);
    if (!entries.length) return null;
    const max = Math.max(...entries.map(([, v]) => v));
    return h("div", { class: "layers", role: "img", "aria-label": "Gebouwde blokken per hoogtelaag" },
      entries.map(([sec, v]) => h("div", { class: "layer", title: `y ${sec * 16} … ${sec * 16 + 15}: ${NUM.format(v)} blokken` },
        h("span", { class: "label" }, `y ${sec * 16}`),
        h("span", { class: "bar-track" }, h("span", { class: "bar", style: `width:${Math.max(0.5, (100 * v) / max).toFixed(1)}%` })),
        h("span", { class: "num" }, NUM.format(v)))));
  }

  function notCounted(b) {
    const notes = [];
    if (b.history_built) notes.push(`${NUM.format(b.history_built)} blokken in chunks van vóór onze spelers (de makers van de map)`);
    if (b.modded) notes.push(`${NUM.format(b.modded)} blokken uit mods (${b.modded_blocks.slice(0, 4).map(([id]) => id.split(":")[1].replaceAll("_", " ")).join(", ")}…)`);
    if (b.excluded_dimensions.length) notes.push(`${b.excluded_dimensions.length} gegenereerde dimensie(s) van 20w14∞ (willekeurige blokken)`);
    return notes.length ? h("p", { class: "folder" }, `Niet meegeteld: ${notes.join("; ")}.`) : null;
  }

  function viewsSection(w) {
    const items = [];
    for (const m of rendersOf(w)) {
      for (const [i, path] of Object.entries(m.images)) {
        const a = m.areas[i];
        const where = m.dimension === "minecraft:overworld" ? "" : ` · ${dimName(m.dimension)}`;
        const title = `${a.label.charAt(0).toUpperCase()}${a.label.slice(1)}${where}`;
        const img = h("img", { src: path, alt: `Bovenaanzicht van ${title.toLowerCase()}`, loading: "lazy" });
        const link = SERVED ? view3d(m, i) : path;
        items.push(h("figure", { class: "view" },
          h("a", { href: link, target: "_blank", rel: "noopener", title: SERVED ? "Open in 3D" : "Open het plaatje" }, img),
          h("figcaption", null, h("b", null, title), a.detail && a.detail !== "spawn" ? ` · ${a.detail}` : null,
            SERVED ? [" · ", h("a", { href: link, target: "_blank", rel: "noopener" }, "open in 3D")] : null)));
      }
    }
    if (!items.length) return null;
    return [h("h3", null, "Bovenaanzicht"), h("div", { class: "views" }, items),
      h("p", { class: "folder" }, "Platte kaart per bouwplek (1 pixel is 1 blok, noorden is boven), gemaakt met BlueMap. ",
        SERVED ? "Klik op een kaart om rond te kijken in 3D." : "Rondkijken in 3D kan als je de catalogus opent met mcatlas serve.")];
  }

  function buildSection(w) {
    const b = w.build;
    if (!b) {
      const why = w.generator === "debug" ? "Een debugwereld toont alle blokken; er is niets gebouwd."
        : w.format === "anvil" ? "Nog niet diep geanalyseerd (mcatlas analyze --tier 2)."
          : "Niet te analyseren voor dit wereldformaat.";
      return [h("h3", null, "Bouwwerk"), h("p", { class: "folder" }, why)];
    }
    const seen = seenSites();
    const mapBox = h("div", { class: "map-box" }, h("p", { class: "folder" }, "Kaart laden…"));
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
      h("thead", null, h("tr", null, ["Bekeken", "Waar", "Blokken", "Onder de grond", "Hoogte (y)", "Chunks", "Tijd in de buurt", "Teleport", ...(SERVED ? ["3D"] : [])]
        .map((c, i) => h("th", { class: i >= 2 && i <= 6 ? "num" : null }, c)))),
      h("tbody", null, siteRows)) : h("p", { class: "folder" }, "Geen bouwplekken gevonden.");

    loadMap(w.world_id).then((data) => {
      const dims = data ? data.dimensions.filter((d) => d.x.length) : [];
      if (!dims.length) { mapBox.replaceChildren(h("p", { class: "folder" }, "Geen kaartgegevens.")); return; }
      let current = dims.find((d) => d.key === (b.main_dimension || "minecraft:overworld")) || dims[0];
      const show = () => {
        const sites = b.sites.map((x, k) => [x, k + 1]).filter(([x]) => x.dimension === current.key);
        const picker = dims.length > 1 ? h("div", { class: "map-dims" }, dims.map((d) => h("button", {
          type: "button", class: d === current ? "ghost small active" : "ghost small",
          onclick: () => { current = d; show(); } }, dimName(d.key)))) : null;
        mapBox.replaceChildren(...[picker, ...dimensionMaps(current, sites), h("p", { class: "folder" },
          "Elk vakje is een chunk (16×16 blokken); noorden is boven. Blauw: gebouwd (donkerder = meer). ",
          "Grijs: spelers zijn er geweest zonder te bouwen. Nummers: bouwplekken uit de tabel.")].filter(Boolean));
      };
      show();
    });

    const blocks = b.top_blocks.length ? h("div", { class: "chips" }, b.top_blocks.map(([id, n]) =>
      h("span", { class: "badge" }, `${blockName(id)} `, h("b", null, NUM.format(n))))) : null;
    const structs = Object.entries(b.structures);
    return [
      h("h3", null, "Bouwwerk"),
      h("div", { class: "stats" },
        stat("Gebouwd", `${NUM.format(b.built)} blokken`),
        stat("Onder de grond", pct(b.pct_below)),
        stat("Bebouwde chunks", NUM.format(b.built_chunks)),
        stat("Bouwplekken", NUM.format(b.sites.length))),
      h("p", { class: "folder" },
        "Gebouwd = blokken die de wereldgenerator niet zelf plaatst (1 blok = 1 m³). Bouwen met natuurlijke blokken ",
        "(steen, aarde, stammen) telt niet mee, en blokken van dorpen, mijnschachten en kerkers ook niet; ",
        "typische dorpsblokken (planken, keien, hooi…) tellen alleen waar spelers minstens een half uur in de buurt waren. ",
        "Onder de grond = onder het natuurlijke maaiveld; gegraven kelders en kuilen tellen als ondergronds."),
      notCounted(b),
      h("h3", null, "Waar"), mapBox,
      h("h3", null, "Bouwplekken"), sitesTable,
      h("p", { class: "folder" }, "Vink een plek aan als jullie hem bekeken hebben; dat wordt in deze browser onthouden. ",
        "Het teleportcommando zet je 2 blokken boven het hoogste bouwblok (gebruik toeschouwersmodus als het ondergronds is)."),
      layerProfile(b) ? [h("h3", null, "Hoogteprofiel"), layerProfile(b)] : null,
      blocks ? [h("h3", null, "Meest gebruikte bouwblokken"), blocks] : null,
      structs.length ? h("p", { class: "folder" }, "Gegenereerde structuren (niet meegeteld): ",
        structs.map(([k, v]) => `${structureName(k)} (${NUM.format(v)} chunks)`).join(", "),
        b.structure_built ? `; samen ${NUM.format(b.structure_built)} blokken.` : ".") : null,
    ];
  }

  function textSection(w) {
    if (!w._texts.length) return null;
    const matches = new Set(textMatches(w));
    const ordered = [...w._texts].sort((a, b) => (matches.has(b) - matches.has(a)) || (a[7] - b[7]) || a[0].localeCompare(b[0]));
    const makers = w._texts.filter((t) => t[7]).length;
    const rows = ordered.map((t) => {
      const [kind, text, holder, dim, x, y, z] = t;
      const where = x === null ? holder : `${holder} · ${dim && dim !== "minecraft:overworld" ? `${dimName(dim)} ` : ""}${x}, ${y}, ${z}`;
      const tp = x === null ? null : `/execute in ${dim || "minecraft:overworld"} run tp @s ${x} ${y + 1} ${z}`;
      return h("tr", { class: matches.has(t) ? "match" : null },
        h("td", null, TEXT_KINDS[kind] || kind, t[7] ? h("div", { class: "folder" }, "van de makers") : null),
        h("td", { class: "text" }, text.length > 400 ? h("details", null, h("summary", null, snippet(text)), text) : text),
        h("td", null, where),
        h("td", null, tp ? copyButton(tp) : null));
    });
    const table = h("table", { class: "plain texts" },
      h("thead", null, h("tr", null, ["Soort", "Tekst", "Waar", "Teleport"].map((c) => h("th", null, c)))),
      h("tbody", null, rows));
    return [h("h3", null, `Teksten (${NUM.format(w._texts.length)})`),
      matches.size ? h("p", { class: "folder" }, `${matches.size} passen bij je zoekopdracht; die staan bovenaan.`) : null,
      makers ? h("p", { class: "folder" }, `${NUM.format(makers)} teksten staan in chunks van vóór onze spelers (de makers van de map); die tellen niet mee bij het zoeken.`) : null,
      w._texts.length > 60 ? h("details", { open: matches.size > 0 }, h("summary", null, `Toon alle ${NUM.format(w._texts.length)} teksten`), table) : table];
  }

  const NOTE_DATE = new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short" });
  function noteView(w) {
    const n = w._note;
    const box = h("section", { class: "note-box" });
    const edit = () => box.replaceChildren(...noteEditor(w));
    const editButton = notesWritable
      ? h("button", { type: "button", class: "ghost small", onclick: edit }, n ? "Bewerk notitie" : "Notitie toevoegen")
      : null;
    if (!n) {
      box.append(h("div", { class: "note-head" }, h("span", { class: "folder" }, notesWritable
        ? "Nog geen notitie bij deze wereld." : "Nog geen notitie. Toevoegen kan via mcatlas serve (knop verschijnt dan hier) of mcatlas note."),
        editButton));
      return box;
    }
    box.append(
      h("div", { class: "note-head" },
        h("div", null, h("b", null, n.title || "Notitie"), n.rating ? ` ${"★".repeat(n.rating)}` : null),
        editButton),
      n.tags.length ? h("div", { class: "badges" }, n.tags.map((t) => h("span", { class: "badge" }, t))) : null,
      n.note ? h("div", { class: "note-text" }, n.note) : null,
      n.updated ? h("div", { class: "folder" }, `Bijgewerkt ${NOTE_DATE.format(new Date(n.updated))}`) : null);
    return box;
  }

  function noteEditor(w) {
    const n = w._note || { title: "", note: "", tags: [], rating: null };
    const title = h("input", { type: "text", value: n.title, maxlength: 200, placeholder: "Bijv. Sams treinstation" });
    const tags = h("input", { type: "text", value: n.tags.join(", "), placeholder: "gevonden, trein" });
    const rating = h("select", null, h("option", { value: "" }, "–"),
      [1, 2, 3, 4, 5].map((r) => h("option", { value: r, selected: n.rating === r }, "★".repeat(r))));
    const text = h("textarea", { rows: 6, placeholder: "Wat is dit voor wereld, wat is er bijzonder, waar ligt wat?" });
    text.value = n.note;
    const status = h("span", { class: "folder" });
    const save = h("button", { type: "button", class: "primary", onclick: async () => {
      save.disabled = true; status.textContent = "Opslaan…";
      const body = {
        title: title.value.trim(), note: text.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
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
        status.textContent = `Niet opgeslagen: ${e.message}`;
        save.disabled = false;
      }
    } }, "Opslaan");
    const cancel = h("button", { type: "button", class: "ghost", onclick: () => openDetail(w) }, "Annuleren");
    return [
      h("label", { class: "field" }, "Titel", title),
      h("label", { class: "field" }, "Tags (met komma's)", tags),
      h("label", { class: "field" }, "Waardering", rating),
      h("label", { class: "field" }, "Notitie", text),
      h("div", { class: "note-actions" }, save, cancel, status),
      h("p", { class: "folder" }, "Wordt bewaard als tekstbestand naast het archief; de werelden zelf worden niet aangeraakt."),
    ];
  }

  let openWorld = null;
  function openDetail(w) {
    openWorld = w;
    const a = w.activity;
    const body = $("#detail-body");
    const close = h("button", { class: "ghost close", type: "button", onclick: () => $("#detail").close() }, "Sluiten");
    const comps = Object.entries(w.importance.components)
      .map(([k, v]) => `${{ days: "dagen", weeks: "weken", play_hours: "speeltijd", items_used: "items", chunks: "gebied", built: "gebouwd" }[k] || k} ${DEC.format(v)}`)
      .join(" + ");

    const players = w.players.length ? h("table", { class: "plain" },
      h("thead", null, h("tr", null, ["Speler", "Speeltijd", "Sessies", "Items", "Adv.", "Modus", "Laatste positie"]
        .map((c, i) => h("th", { class: i && i < 5 ? "num" : null }, c)))),
      h("tbody", null, w.players.map((p) => h("tr", null,
        h("td", { title: p.uuid }, p.name || `${p.uuid.slice(0, 8)}… (onbekend)`),
        h("td", { class: "num" }, p.play_hours ? hours(p.play_hours) : "–"),
        h("td", { class: "num" }, p.sessions ?? "–"),
        h("td", { class: "num" }, p.items_used ? NUM.format(p.items_used) : "–"),
        h("td", { class: "num" }, p.advancements || "–"),
        h("td", null, p.game_mode !== null && p.game_mode !== undefined ? MODES[p.game_mode] : "–"),
        h("td", null, p.position ? `${(p.dimension || "").replace("minecraft:", "")} ${p.position.map((x) => Math.round(x)).join(", ")}` : "–"))))) : h("p", { class: "folder" }, "Geen spelersgegevens.");

    const dims = w.dimensions.length ? h("table", { class: "plain" },
      h("thead", null, h("tr", null, h("th", null, "Dimensie"), h("th", { class: "num" }, "Chunks"), h("th", { class: "num" }, "Regio's"), h("th", null, "Gebied (blokken)"))),
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
      h("td", null, d.sig.last_played ? "laatst gespeeld" : "")));

    const related = w.related.length ? h("ul", null, w.related.map((r) => h("li", null,
      h("a", { class: "rel", onclick: () => { const o = byId.get(r.world_id); if (o) openDetail(o); } }, r.folder_name),
      ` — ${Math.round(r.similarity * 100)}% gedeelde geschiedenis`))) : null;

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
        stat("Actieve dagen", extraDays(w) > 0 ? `${NUM.format(a.distinct_days)}–${NUM.format(w.days_upper)}` : NUM.format(a.distinct_days)),
        stat("Periode", a.span_days ? `${NUM.format(a.span_days)} d` : "–"),
        stat("Maanden", NUM.format(a.active_months)),
        stat(w.foreign_players ? "Speeltijd (eigen)" : "Speeltijd", w.play_hours ? hours(w.play_hours) : "–"),
        stat("Sessies", w.sessions ? NUM.format(w.sessions) : "–"),
        stat("Items gebruikt", w.items_used ? NUM.format(w.items_used) : "–"),
        stat("Chunks", NUM.format(w.chunks)),
        stat("Grootte", bytes(w.size_bytes))),
      h("h3", null, "Activiteit per week"),
      strip(w, "big-strip", 90),
      monthTicks(),
      h("p", { class: "folder" }, `${period(w)}. Elke kolom is een week; de hoogte is het aantal actieve dagen (max. 7). `,
        "Datums zijn een ondergrens: Minecraft bewaart per chunk alleen de laatste opslag en per advancement alleen de eerste keer.",
        extraDays(w) > 0 ? ` Er zijn ${NUM.format(w.sessions)} sessies geteld, dus er is mogelijk op tot ${NUM.format(w.days_upper)} dagen gespeeld.` : null),
      historyNote(w),
      buildSection(w),
      textSection(w),
      h("h3", null, "Kenmerken"),
      kv([
        ["Versie", w.version_name ? `${w.version_name}${w.data_version ? ` (data ${w.data_version})` : ""}` : null],
        ["Spelmodus", w.game_mode !== null && w.game_mode !== undefined ? MODES[w.game_mode] : null],
        ["Wereldtype", `${GENERATORS[w.generator] || w.generator}${w.generator_detail ? ` — ${w.generator_detail}` : ""}`],
        ["Cheats", w.cheats === null ? null : (w.cheats ? "aan" : "uit")],
        ["Seed", w.seed !== null && w.seed !== undefined ? String(w.seed) : null],
        ["Laatst gespeeld", w.last_played ? DATE.format(new Date(w.last_played)) : null],
        ["Datapacks", w.datapacks.length ? w.datapacks.join(", ") : null],
        ["Sessieduur", w.hours_per_session ? `gemiddeld ${hours(w.hours_per_session)} per sessie${w.afk_suspect ? " — spel stond waarschijnlijk lang aan" : ""}` : null],
        ["In-game kaarten", w.map_items || null],
        ["Bestanden", `${NUM.format(w.files)} (${bytes(w.size_bytes)})`],
        ["Score", `${DEC.format(w.importance.score)} = ${comps}`],
        ["Bron", `${w.source_id}: ${w.relpath}`],
      ]),
      h("h3", null, "Spelers"), players,
      dims ? [h("h3", null, "Dimensies"), dims] : null,
      related ? [h("h3", null, "Verwante werelden"), related] : null,
      w._days.length ? h("details", null, h("summary", null, `Alle ${w._days.length} actieve dagen`),
        h("table", { class: "plain" },
          h("thead", null, h("tr", null, h("th", null, "Dag"), h("th", { class: "num" }, "Chunks opgeslagen"),
            h("th", { class: "num" }, "Bestanden"), h("th", { class: "num" }, "Advancements"), h("th", null, ""))),
          h("tbody", null, dayRows))) : null,
      w.errors.length ? [h("h3", null, "Meldingen bij analyse"), h("div", { class: "errors" }, w.errors.join("\n"))] : null,
    ].flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
    const dlg = $("#detail");
    if (!dlg.open) dlg.showModal();
    dlg.scrollTop = 0;
    setHash();
  }
  $("#detail").addEventListener("close", setHash);
  $("#detail").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

  // ---------- wiring ----------
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

  const dayInput = (el) => (/^\d{4}-\d{2}-\d{2}$/.test(el.value) ? parseDay(el.value) : null);
  for (const el of [$("#t-from"), $("#t-to")]) {
    if (CATALOG.first_day) { el.min = CATALOG.first_day; el.max = CATALOG.last_day; }
    el.addEventListener("change", () => { setRange(dayInput($("#t-from")), dayInput($("#t-to"))); setHash(); render(); });
  }
  $("#t-clear").addEventListener("click", () => { setRange(null, null); setHash(); render(); });

  const params = new URLSearchParams(location.hash.slice(1));
  const hashDay = (key) => (/^\d{4}-\d{2}-\d{2}$/.test(params.get(key) || "") ? parseDay(params.get(key)) : null);
  setRange(hashDay("van"), hashDay("tot"));
  if (params.get("q")) { state.q = params.get("q"); $("#q").value = state.q; }
  render();
  loadTexts();
  checkNotesApi();
  const wanted = params.get("w");
  if (wanted && byId.has(wanted)) openDetail(byId.get(wanted));
})();
