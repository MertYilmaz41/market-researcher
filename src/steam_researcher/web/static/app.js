import { cssVar, scoreColor, scoreInk } from "/static/palette.js";
import { createMap2d } from "/static/map2d.js";

const $ = (sel) => document.querySelector(sel);

// ---------- tiny DOM helper: text is always set via textContent ----------
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const money = (x) => (x >= 1e6 ? `$${(x / 1e6).toFixed(1)}M` : x >= 1e3 ? `$${Math.round(x / 1e3)}k` : `$${Math.round(x)}`);
const pct = (x) => `${Math.round(x * 100)}%`;

// ---------- toasts: every message the user should see goes through here ----------
const ICONS = { success: "✓", info: "i", warning: "!", error: "×" };
const LIFETIME = { success: 6000, info: 7000, warning: 12000, error: 0 }; // 0 = stays until closed

function toast(level, title, message = "", hint = "") {
  const close = el("button", { class: "close", type: "button", "aria-label": "Dismiss" }, "×");
  const node = el("div", { class: `toast ${level}`, role: level === "error" ? "alert" : "status" },
    el("span", { class: "icon" }, ICONS[level] || "i"),
    el("div", {},
      el("b", {}, title),
      message ? el("p", {}, message) : null,
      hint ? el("p", { class: "hint" }, hint) : null,
    ),
    close,
  );
  const remove = () => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 200);
  };
  close.addEventListener("click", remove);
  if (LIFETIME[level]) setTimeout(remove, LIFETIME[level]);
  const box = $("#toasts");
  box.append(node);
  while (box.children.length > 5) box.firstElementChild.remove(); // don't bury the screen
}

const notify = (n) => n && toast(n.level, n.title, n.message, n.hint);
const notifyAll = (list) => (list || []).forEach(notify);

// Any failure becomes a toast. ApiError carries a server Notice; a TypeError from fetch means
// the local server isn't reachable at all.
class ApiError extends Error {
  constructor(notice) {
    super(notice.message);
    this.notice = notice;
  }
}

function notifyError(err, fallbackTitle = "Something went wrong") {
  if (err instanceof ApiError) return notify(err.notice);
  if (err instanceof TypeError) {
    return toast("error", "Can't reach the Steam Researcher server",
      "The page lost its connection to the local server.",
      "Is the Steam Researcher window still open? Start it again with Steam Researcher.bat, then reload this page.");
  }
  toast("error", fallbackTitle, err.message || String(err));
}

async function apiError(res) {
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (body?.notice) return new ApiError(body.notice);
  let detail = body?.detail;
  if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
  return new ApiError({ level: "error", title: `Request failed (HTTP ${res.status})`, message: detail || res.statusText, hint: "" });
}

// ---------- opportunity map: 2D (always works) and 3D (needs three.js from the CDN + WebGL) ----------
const onMapSelect = (appid) => selectGame(appid);
const map2d = createMap2d($("#map"), { onSelect: onMapSelect });
let map3d = null;
try {
  const { createMap } = await import("/static/map3d.js");
  const m = createMap($("#map"), { onSelect: onMapSelect });
  if (!m.available) throw new Error("WebGL is disabled in this browser");
  map3d = m;
} catch (err) {
  console.error(err);
  toast("warning", "3D map unavailable",
    "The 3D library couldn't load (no internet, the CDN is blocked, or WebGL is off).",
    "The 2D map shows the same games. Reload the page to try 3D again.");
}
// Both maps always hold the current games and selection, so switching views is instant.
const map = {
  setGames(games) { map2d.setGames(games); map3d?.setGames(games); },
  select(appid) { map2d.select(appid); map3d?.select(appid); },
};

const MAP_LEGEND = {
  "2d": "x: demand · y: dissatisfaction · size: revenue · color: score · hover for fixability",
  "3d": "x: demand · y: dissatisfaction · z: fixability · size: revenue · color: score",
};
function setMapView(view) {
  if (view !== "2d" && !map3d) view = "2d";
  else if (view !== "2d") view = "3d";
  map2d.setVisible(view === "2d");
  map3d?.setVisible(view === "3d");
  $("#map-legend").textContent = MAP_LEGEND[view];
  for (const b of document.querySelectorAll("#map-view button")) {
    b.setAttribute("aria-pressed", String(b.dataset.view === view));
  }
  try { localStorage.setItem("mapView", view); } catch { /* private mode: just not remembered */ }
}
document.querySelectorAll("#map-view button").forEach((b) => b.addEventListener("click", () => setMapView(b.dataset.view)));
if (!map3d) {
  const b3 = $('#map-view button[data-view="3d"]');
  b3.disabled = true;
  b3.title = "3D map unavailable in this browser";
}
let savedView = "3d";
try { savedView = localStorage.getItem("mapView") || "3d"; } catch { /* storage blocked */ }
setMapView(savedView);

// ---------- state ----------
// A search and a single-game analysis can run at the same time. keepPanel: the user analyzed a game
// during the current search, so its results must not replace that game in the panel.
const state = { games: [], selected: null, sort: { key: "rank", asc: true }, runId: null,
  searching: false, analyzing: false, keepPanel: false };

// Buttons are never disabled while busy: a disabled button ignores clicks and Enter silently.
// They show what's running instead, and a second press explains why nothing new starts.
function setButtonBusy(button, busy, label) {
  button.textContent = label;
  button.classList.toggle("busy", busy);
  button.setAttribute("aria-busy", String(busy));
}

function setSearching(on) {
  state.searching = on;
  document.body.classList.toggle("searching", on);
  setButtonBusy($("#run"), on, on ? "Searching..." : "Find opportunities");
}

function setAnalyzing(on) {
  state.analyzing = on;
  setButtonBusy($("#game-form button"), on, on ? "Analyzing..." : "Analyze");
}

function stillRunning(what) {
  toast("info", "Please wait", `${what} is still running.`, "Wait for it to finish, then try again.");
}

// ---------- top bar ----------
function openFilters(open = true) {
  $("#filters").hidden = !open;
  $("#filters-toggle").setAttribute("aria-expanded", String(open));
}
$("#filters-toggle").addEventListener("click", () => openFilters($("#filters").hidden));
document.addEventListener("click", (e) => {
  if (!e.target.closest("#filters, #filters-toggle, #toasts")) openFilters(false);
});
document.querySelectorAll("input").forEach((i) => i.addEventListener("input", () => i.classList.remove("invalid")));

const labelOf = (input) =>
  input.closest("label")?.firstChild?.textContent.trim() || input.getAttribute("aria-label") || "This field";

function fieldError(input, message, hint = "") {
  input.classList.add("invalid");
  if (input.closest("#filters")) openFilters(true);
  input.focus();
  toast("error", `Check "${labelOf(input)}"`, message, hint);
}

// ---------- tag picker: tick any number of Steam tags (games must have all of them) ----------
const MAX_TAGS = 5; // config.MAX_TAGS on the server
const tagInput = $("#tag");
const tagPop = $("#tag-pop");
const tagList = $("#tag-list");
// tags: Steam's catalog. shown: options in list order. freeText: the catalog failed to load, so the
// box takes comma-separated tags typed by hand.
const tagPicker = { tags: [], picked: ["Job Simulator"], shown: [], active: -1, freeText: false };

const isPicked = (t) => tagPicker.picked.includes(t);
const tagsLabel = (tags) => tags.join(" + ");

// Case-insensitive substring match, prefix matches first. Empty query = every tag.
function matchTags(query) {
  const q = query.trim().toLowerCase();
  if (!q) return tagPicker.tags;
  const prefix = [], inside = [];
  for (const t of tagPicker.tags) {
    const i = t.toLowerCase().indexOf(q);
    if (i === 0) prefix.push(t);
    else if (i > 0) inside.push(t);
  }
  return prefix.concat(inside);
}

function renderChips() {
  $("#tag-chips").replaceChildren(...tagPicker.picked.map((t) =>
    el("span", { class: "tag-chip" }, t,
      el("button", { type: "button", tabindex: "-1", "aria-label": `Remove ${t}`,
        onmousedown: (e) => e.preventDefault(), // don't steal focus from the filter box
        onclick: (e) => { e.stopPropagation(); togglePick(t); } }, "×"))));
  if (tagPicker.freeText) return;
  const open = !tagPop.hidden;
  tagInput.placeholder = open ? "Filter tags..." : tagPicker.picked.length ? "" : "Pick Steam tags...";
}

// Update checkboxes, limits and the footer in place: rows never move while you tick.
function refreshList() {
  const full = tagPicker.picked.length >= MAX_TAGS;
  tagList.querySelectorAll("li[role=option]").forEach((li) => {
    const on = isPicked(li.dataset.tag);
    li.setAttribute("aria-selected", String(on));
    li.classList.toggle("disabled", full && !on);
    li.setAttribute("aria-disabled", String(full && !on));
  });
  const n = tagPicker.picked.length;
  $("#tag-count").textContent = full ? `${MAX_TAGS} selected (the maximum)`
    : n ? `${n} selected · games must have all of them` : "Tick one or more tags";
  $("#tag-clear").hidden = !n;
}

function togglePick(tag) {
  if (isPicked(tag)) tagPicker.picked = tagPicker.picked.filter((t) => t !== tag);
  else if (tagPicker.picked.length < MAX_TAGS) tagPicker.picked.push(tag);
  else return;
  tagInput.classList.remove("invalid");
  renderChips();
  refreshList();
}

function setActive(i) {
  const items = tagList.querySelectorAll("li[role=option]");
  items[tagPicker.active]?.classList.remove("active");
  tagPicker.active = i;
  const li = items[i];
  if (!li) return tagInput.removeAttribute("aria-activedescendant");
  li.classList.add("active");
  li.scrollIntoView({ block: "nearest" });
  tagInput.setAttribute("aria-activedescendant", li.id);
}

// Ticked tags first (as of opening), then the rest. Typing in the box only narrows the list.
function openTagList(query = tagInput.value) {
  if (!tagPicker.tags.length) return;
  const matches = matchTags(query);
  const picked = matches.filter(isPicked), rest = matches.filter((t) => !isPicked(t));
  tagPicker.shown = picked.concat(rest);
  tagPicker.active = -1;
  let i = 0;
  const option = (t) => el("li", { role: "option", id: `tag-opt-${i++}`, "data-tag": t, onclick: () => togglePick(t) },
    el("span", { class: "check", "aria-hidden": "true" }, "✓"), t);
  const group = (title) => el("li", { class: "group", role: "presentation" }, title);
  const rows = [];
  if (picked.length) rows.push(group("Selected"), ...picked.map(option));
  if (rest.length) rows.push(...(picked.length ? [group("All tags")] : []), ...rest.map(option));
  if (!matches.length) rows.push(el("li", { class: "none" }, `No Steam tag contains "${query.trim()}"`));
  tagList.replaceChildren(...rows);
  tagPop.hidden = false;
  tagInput.setAttribute("aria-expanded", "true");
  if (query.trim() && tagPicker.shown.length) setActive(0);
  renderChips();
  refreshList();
}

function closeTagList() {
  tagPop.hidden = true;
  if (!tagPicker.freeText) tagInput.value = ""; // the filter is temporary; picks live in the chips
  tagInput.setAttribute("aria-expanded", "false");
  tagInput.removeAttribute("aria-activedescendant");
  renderChips();
}

tagInput.addEventListener("focus", () => openTagList());
tagInput.addEventListener("input", () => openTagList());
tagInput.addEventListener("blur", closeTagList);
// A click anywhere on the field (chips, empty space) opens the list.
$("#tag-combo").addEventListener("click", (e) => {
  if (tagPop.contains(e.target) || e.target.closest("#tag-toggle")) return;
  if (document.activeElement !== tagInput) tagInput.focus();
  else if (tagPop.hidden) openTagList();
});
tagPop.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus while ticking/scrolling
$("#tag-clear").addEventListener("click", () => {
  tagPicker.picked = [];
  renderChips();
  refreshList();
});
$("#tag-toggle").addEventListener("mousedown", (e) => {
  e.preventDefault();
  if (!tagPop.hidden) return closeTagList();
  if (document.activeElement !== tagInput) tagInput.focus();
  else openTagList();
});
tagInput.addEventListener("keydown", (e) => {
  if (e.key === "Backspace" && !tagInput.value && tagPicker.picked.length && tagPicker.tags.length) {
    e.preventDefault();
    return togglePick(tagPicker.picked[tagPicker.picked.length - 1]);
  }
  if (tagPop.hidden) {
    if (e.key === "ArrowDown" && tagPicker.tags.length) { e.preventDefault(); openTagList(); }
    return; // Enter with the list closed submits the search as usual
  }
  const last = tagPicker.shown.length - 1;
  if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(last, tagPicker.active + 1)); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, tagPicker.active - 1)); }
  else if (e.key === "Enter") {
    e.preventDefault(); // Enter ticks; it never submits while the list is open
    if (tagPicker.active >= 0) togglePick(tagPicker.shown[tagPicker.active]);
    else closeTagList();
  } else if (e.key === "Escape") closeTagList();
});

renderChips();

(async function loadTags() {
  try {
    const res = await fetch("/api/tags");
    if (!res.ok) throw await apiError(res);
    tagPicker.tags = (await res.json()).tags || [];
    if (document.activeElement === tagInput) openTagList();
  } catch (err) {
    // Fallback: type tags by hand, comma-separated.
    $("#tag-toggle").hidden = true;
    tagInput.value = tagPicker.picked.join(", ");
    tagPicker.picked = [];
    renderChips();
    tagPicker.freeText = true;
    tagInput.placeholder = "Steam tags, comma-separated, e.g. Crafting, Survival";
    toast("warning", "Tag list unavailable",
      err instanceof ApiError ? err.notice.message : "The list of Steam tags couldn't be loaded.",
      "You can still type tags by hand, separated by commas, e.g. Crafting, Survival.");
  }
})();

// Our own English text: the browser's validationMessage follows the OS language.
function validityText(input) {
  const v = input.validity, { min, max, step } = input;
  if (v.valueMissing) return "This field can't be empty.";
  if (v.badInput) return "Enter a number.";
  if (v.rangeUnderflow || v.rangeOverflow) {
    return max ? `Enter a number from ${min} to ${max}.` : `Enter a number of at least ${min}.`;
  }
  if (v.stepMismatch) return `Use a multiple of ${step}, e.g. ${Math.round(+input.value / +step) * +step || step}.`;
  return input.validationMessage;
}

// The browser's own validation cancels submit before our handler runs. The invalid field is often
// inside the Filters popover, which the outside-click handler has just hidden, so its bubble can't
// appear. Re-open the popover and show a toast so this is never silent.
$("#tag-form").addEventListener("invalid", (e) => {
  e.preventDefault(); // our toast replaces the browser bubble
  const input = e.target;
  if ($("#tag-form").querySelector(".invalid")) return; // one toast per submit
  fieldError(input, validityText(input));
}, true);

$("#run").addEventListener("click", () => {
  document.querySelectorAll("#tag-form .invalid").forEach((i) => i.classList.remove("invalid"));
});

$("#tag-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.searching) return stillRunning("A search");
  const body = {
    // picks come only from ticks; in the free-text fallback, from the comma-separated box
    tags: !tagPicker.freeText ? [...tagPicker.picked]
      : tagInput.value.split(",").map((t) => t.trim()).filter(Boolean),
    min_reviews: +$("#min-reviews").value,
    lo: +$("#lo").value,
    hi: +$("#hi").value,
    max_games: +$("#max-games").value,
    reviews: +$("#reviews").value,
  };
  if (!body.tags.length) {
    return fieldError(tagInput, "Pick at least one tag.",
      !tagPicker.freeText ? "Tick one or more tags in the list." : "Type tags separated by commas, e.g. Crafting, Survival.");
  }
  if (body.tags.length > MAX_TAGS) {
    return fieldError(tagInput, `Use at most ${MAX_TAGS} tags.`, "Games must have every tag, so a few tags is usually enough.");
  }
  const label = tagsLabel(body.tags);
  if (body.lo > body.hi) {
    $("#lo").classList.add("invalid");
    return fieldError($("#hi"), `'% positive from' (${body.lo}) is higher than '% positive to' (${body.hi}).`,
      "Swap the two values, e.g. 5 to 70.");
  }
  openFilters(false);
  state.keepPanel = false;
  setSearching(true);
  searchStatus(label, 0, "", `Fetching games tagged ${label}...`);
  try {
    const res = await fetch("/api/tag-runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw await apiError(res);
    const { id, notices } = await res.json();
    notifyAll(notices);
    state.runId = id;
    await poll(id, label);
  } catch (err) {
    notifyError(err, "Search failed");
  } finally {
    setSearching(false);
    searchStatus(null);
  }
});

// The banner over the (faded) previous results while a search runs; tag null hides it.
function searchStatus(tag, frac, count, message) {
  const box = $("#search-status");
  box.hidden = tag == null;
  if (tag == null) return;
  $("#search-status-title").textContent = `Searching "${tag}"...`;
  $("#search-status-count").textContent = count;
  $("#search-status-fill").style.width = `${Math.round(frac * 100)}%`;
  $("#search-status-text").textContent = message || "";
}

async function poll(id, tag) {
  for (;;) {
    const res = await fetch(`/api/tag-runs/${id}`);
    if (res.status === 404) {
      throw new ApiError({ level: "error", title: "The search was interrupted",
        message: "The server was restarted, so this run was lost.", hint: "Press Find opportunities again." });
    }
    if (!res.ok) throw await apiError(res);
    const job = await res.json();
    if (job.status === "error") throw new ApiError(job.error);
    if (job.status === "done") return showResult(job.result, id);
    searchStatus(tag, job.total ? job.done / job.total : 0, job.total ? `${job.done} / ${job.total}` : "", job.message);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

$("#game-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.analyzing) return stillRunning("The analysis of the previous game");
  const input = $("#appid");
  input.classList.remove("invalid");
  const raw = input.value.trim();
  if (!raw) {
    return fieldError(input, "Enter a Steam AppID or store link.",
      "For example 1330660 or https://store.steampowered.com/app/1330660/");
  }
  const appid = (raw.match(/\/app\/(\d+)/) || raw.match(/^(\d+)$/) || [])[1];
  if (!appid || +appid <= 0) {
    return fieldError(input, `"${raw.slice(0, 60)}" isn't an AppID or a Steam store link.`,
      "Use the number from the store URL, e.g. 1330660 from store.steampowered.com/app/1330660/");
  }
  if (state.games.some((g) => g.game.appid === +appid)) return selectGame(+appid);

  if (state.searching) state.keepPanel = true; // the finishing search must not replace this game
  setAnalyzing(true);
  const panel = $("#panel");
  const previous = [...panel.childNodes];
  panel.replaceChildren(el("div", { class: "empty loading" },
    el("div", {},
      el("p", {}, `Analyzing AppID ${appid}...`),
      el("div", { class: "progress-bar indeterminate" }, el("span")),
      el("p", { class: "muted" }, "The first time can take ~15 s, longer if Steam's review server is slow."))));
  try {
    const res = await fetch(`/api/games/${appid}?reviews=${+$("#reviews").value || 300}`);
    if (!res.ok) throw await apiError(res);
    const g = await res.json();
    state.selected = null;
    map.select(null);
    highlightRow();
    renderPanel(g);
    if (state.games.length) {
      toast("info", "Shown in the details panel", `${g.game.name} isn't part of the current ranking.`);
    }
    notifyAll(g.notices);
  } catch (err) {
    panel.replaceChildren(...previous);
    state.keepPanel = false;
    notifyError(err, "Analysis failed");
  } finally {
    setAnalyzing(false);
  }
});

// ---------- results ----------
function showResult(result, id) {
  state.games = result.games.map((g, i) => ({ ...g, rank: i + 1 }));
  state.sort = { key: "rank", asc: true };
  $("#table-title").textContent = `${result.tag}: opportunity ranking`;
  const notes = [
    `${result.n_candidates} of ${result.n_tag_games} games have ≥ ${result.min_reviews} reviews and ${result.lo}-${result.hi}% positive; analyzed the ${state.games.length} with most reviews.`,
  ];
  if (result.not_games.length) notes.push(`Excluded non-games: ${result.not_games.join(", ")}.`);
  $("#table-note").textContent = notes.join(" ");
  const dl = $("#download");
  dl.hidden = !state.games.length;
  dl.href = `/api/tag-runs/${id}/report.md`;

  map.setGames(state.games);
  renderTable();
  notifyAll(result.notices);
  if (state.keepPanel) {
    // the panel shows a game the user analyzed during the search: leave it there
  } else if (state.games.length) {
    selectGame(state.games[0].game.appid);
  } else {
    state.selected = null;
    const why = (result.notices || []).find((n) => n.level === "warning");
    $("#panel").replaceChildren(el("div", { class: "empty" },
      why ? `${why.title}. ${why.hint}` : "No games to show. Try a lower minimum or a wider % range."));
  }
}

const sortValue = {
  rank: (g) => g.rank,
  name: (g) => g.game.name.toLowerCase(),
  score: (g) => g.opportunity.score,
  reviews: (g) => g.reviews,
  rating: (g) => g.rating,
  recent: (g) => g.recent_share ?? -1,
  gross: (g) => g.box.gross_mid,
  complaint: (g) => g.mining?.categories[0]?.share ?? -1,
  risks: (g) => riskCodes(g).length,
};

const recentText = (g) => g.recent_share == null ? "-" : `${g.recent_reviews.toLocaleString("en-US")} (${pct(g.recent_share)})`;

const riskCodes = (g) => g.flags.filter((f) => f.severity !== "info").map((f) => f.code);

function renderTable() {
  const { key, asc } = state.sort;
  const rows = [...state.games].sort((a, b) => {
    const va = sortValue[key](a), vb = sortValue[key](b);
    return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
  });
  for (const th of document.querySelectorAll("#ranking th")) {
    th.classList.toggle("sorted", th.dataset.key === key);
    th.classList.toggle("asc", th.dataset.key === key && asc);
  }
  $("#ranking tbody").replaceChildren(
    ...rows.map((g) => {
      const o = g.opportunity;
      const adj = Math.round(o.effective_rating) !== Math.round(g.rating) ? ` (${Math.round(o.effective_rating)}% adj.)` : "";
      const top = g.mining?.categories[0];
      return el("tr", { "data-appid": g.game.appid, onclick: () => selectGame(g.game.appid) },
        el("td", { class: "num" }, g.rank),
        el("td", {}, g.game.name),
        el("td", { class: "num" }, el("span", { class: "score-pill", style: `background:${scoreColor(o.score)};color:${scoreInk(o.score)}` }, Math.round(o.score))),
        el("td", { class: "num" }, g.reviews.toLocaleString("en-US")),
        el("td", { class: "num" }, `${Math.round(g.rating)}%${adj}`),
        el("td", { class: "num" }, recentText(g)),
        el("td", { class: "num" }, g.price ? money(g.box.gross_mid) : "F2P"),
        el("td", { class: "complaint-cell" }, top ? `${top.label} (${pct(top.share)})` : "-"),
        el("td", { class: "risks-cell" }, riskCodes(g).join(", ") || "-"),
      );
    }),
  );
  highlightRow();
}

document.querySelectorAll("#ranking th").forEach((th) =>
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    state.sort = { key, asc: state.sort.key === key ? !state.sort.asc : ["rank", "name"].includes(key) };
    renderTable();
  }),
);

function highlightRow() {
  for (const tr of document.querySelectorAll("#ranking tbody tr")) {
    tr.classList.toggle("selected", +tr.dataset.appid === state.selected);
  }
}

function selectGame(appid) {
  const g = state.games.find((x) => x.game.appid === appid);
  if (!g) return;
  state.selected = appid;
  map.select(appid); // both views, so the hidden one is in sync when you switch
  highlightRow();
  renderPanel(g);
  document.querySelector(`#ranking tr[data-appid="${appid}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------- detail panel ----------
function bar(labelText, value, text) {
  return el("div", { class: "bar" },
    el("span", {}, labelText),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` })),
    el("span", { class: "val" }, text ?? pct(value)),
  );
}

function renderPanel(g) {
  const o = g.opportunity;
  const game = g.game;
  const adjusted = Math.round(o.effective_rating) !== Math.round(g.rating);

  const head = [
    el("h3", {}, game.name),
    el("div", { class: "sub" },
      el("a", { href: g.store_url, target: "_blank", rel: "noopener" }, "Steam store"),
      ` · AppID ${game.appid}`,
      g.details ? ` · Released ${g.details.release_date}` : "",
      game.developer ? ` · ${game.developer}` : "",
    ),
    el("div", { class: "score-row" },
      el("div", { class: "score-ring", style: `--p:${o.score};--ring:${scoreColor(o.score)}` }, el("span", {}, Math.round(o.score))),
      el("div", { class: "facts" },
        el("div", {}, el("span", {}, "Reviews"), el("b", {}, g.reviews.toLocaleString("en-US"))),
        el("div", {}, el("span", {}, "% positive"), el("b", {}, `${Math.round(g.rating)}%`, adjusted ? ` (${Math.round(o.effective_rating)}% adj.)` : "")),
        el("div", {}, el("span", {}, "Last 12 months"), el("b", {}, recentText(g))),
        el("div", {}, el("span", {}, "Est. gross (x45)"), el("b", {}, g.price ? money(g.box.gross_mid) : "F2P")),
        el("div", {}, el("span", {}, "Range (x30-x100)"), el("b", {}, g.price ? `${money(g.box.gross_low)} - ${money(g.box.gross_high)}` : "-")),
      ),
    ),
    el("div", { class: "bars" },
      bar("Demand", o.demand),
      bar("Dissatisfaction", o.dissatisfaction),
      bar("Fixability", o.fixability),
    ),
    o.penalty ? el("div", { class: "penalty" }, `Risk penalty -${Math.round(o.penalty)} (${o.penalized.join(", ")})`) : null,
    Object.keys(game.tags || {}).length
      ? el("div", { class: "chips" }, Object.keys(game.tags).slice(0, 10).map((t) => el("span", { class: "chip" }, t)))
      : null,
  ];

  const tabs = [
    ["Complaints", () => complaintsTab(g)],
    ["Core fantasy", () => fantasyTab(g)],
    [`Risks${g.flags.length ? ` (${g.flags.length})` : ""}`, () => risksTab(g)],
    ["History", () => historyTab(g)],
  ];
  const body = el("div");
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  tabs.forEach(([name, render], i) => {
    const b = el("button", { type: "button", role: "tab" }, name);
    b.addEventListener("click", () => {
      tabBar.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      body.replaceChildren(render());
    });
    tabBar.append(b);
    if (i === 0) { b.classList.add("active"); body.replaceChildren(render()); }
  });

  $("#panel").replaceChildren(...head.filter(Boolean), tabBar, body);
  $("#panel").scrollTop = 0;
}

function complaintsTab(g) {
  const m = g.mining;
  if (g.review_error) return el("div", { class: "callout" }, `Review texts unavailable: ${g.review_error}`);
  if (!m || !m.n_negative) return el("div", { class: "callout" }, "No English negative reviews to mine.");
  return el("div", {},
    el("div", { class: "callout" },
      el("b", {}, "Great idea, bad execution? "),
      `${pct(m.idea_praise_share)} of ${m.n_negative} negative reviews still praise the idea or its potential. `,
      `${pct(m.fixability)} of complaint mentions are fixable.`),
    m.categories.map((c) =>
      el("details", { class: "complaint" },
        el("summary", {},
          bar(c.label, c.share),
          el("div", { class: c.fixable ? "pillar" : "pillar unfixable" }, (c.fixable ? "Do: " : "") + c.pillar)),
        c.quotes.map((q) => el("blockquote", {}, `"${q}"`)),
      ),
    ),
  );
}

function fantasyTab(g) {
  const m = g.mining;
  if (!m || !(m.core_phrases.length || m.liked.length)) return el("div", { class: "callout" }, "No positive-review phrases found.");
  const max = Math.max(1, ...m.core_phrases.map(([, n]) => n));
  return el("div", {},
    m.core_phrases.length ? el("p", { class: "muted" }, `Common phrases in ${m.n_positive} positive reviews`) : null,
    el("div", { class: "bars" }, m.core_phrases.map(([p, n]) => bar(p, n / max, String(n)))),
    m.liked.length ? el("div", {}, el("p", { class: "muted" }, "Players liked"),
      el("div", { class: "chips" }, m.liked.map(([p]) => el("span", { class: "chip" }, p)))) : null,
  );
}

function risksTab(g) {
  if (!g.flags.length) return el("div", { class: "callout" }, "No risk flags.");
  return el("div", {}, g.flags.map((f) =>
    el("div", { class: "risk" },
      el("span", { class: `sev ${f.severity}` }, f.severity),
      el("div", {}, el("code", {}, f.code), el("div", {}, f.message)),
    ),
  ));
}

const POSITIVE = cssVar("--accent-2"), NEGATIVE = cssVar("--bad"); // History bars

function historyTab(g) {
  const h = g.histogram || [];
  if (!h.length) return el("div", { class: "callout" }, "No review histogram available.");
  const W = 600, H = 170, pad = 18;
  const max = Math.max(1, ...h.map((p) => p.up + p.down));
  const bw = (W - pad) / h.length;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const rect = (x, y, w, hgt, fill, title) => {
    const r = document.createElementNS(NS, "rect");
    Object.entries({ x, y, width: Math.max(0.5, w), height: Math.max(0, hgt), fill, rx: 1.5 }).forEach(([k, v]) => r.setAttribute(k, v));
    const t = document.createElementNS(NS, "title");
    t.textContent = title;
    r.append(t);
    svg.append(r);
  };
  h.forEach((p, i) => {
    const month = new Date(p.date * 1000).toISOString().slice(0, 7);
    const upH = ((H - pad) * p.up) / max, downH = ((H - pad) * p.down) / max;
    const x = pad / 2 + i * bw + bw * 0.12, w = bw * 0.76;
    const tip = `${month}: ${p.up} positive, ${p.down} negative`;
    rect(x, H - pad - upH, w, upH, POSITIVE, tip);
    rect(x, H - pad - upH - downH, w, downH, NEGATIVE, tip);
  });
  const first = new Date(h[0].date * 1000).toISOString().slice(0, 7);
  const last = new Date(h[h.length - 1].date * 1000).toISOString().slice(0, 7);
  return el("div", { class: "hist" },
    svg,
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: `background:${POSITIVE}` }), "Positive"),
      el("span", {}, el("i", { style: `background:${NEGATIVE}` }), "Negative"),
      el("span", { style: "margin-left:auto" }, `${first} → ${last}`),
    ),
    el("p", { class: "muted" }, "Monthly reviews. A tall spike after launch can mean a streamer effect (mostly blue) or a review bomb (mostly red)."),
  );
}
