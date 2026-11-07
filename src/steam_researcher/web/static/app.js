import { cssVar, scoreColor, scoreLevel } from "/static/palette.js";
import { createMap2d } from "/static/map2d.js";
import { applyStatic, dateTime, decimal, fmt, getLang, pct, percent, setLang, t } from "/static/i18n.js";

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
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// Rows and cells that open something: reachable with Tab and opened with Enter or Space, not only the mouse.
// Keys on a button inside (a star, an ⓘ) stay that button's.
function clickable(node, fn) {
  node.tabIndex = 0;
  node.addEventListener("click", fn);
  node.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target === node) { e.preventDefault(); fn(e); }
  });
  return node;
}
// Sortable headers also say how they're sorted to screen readers.
function markSorted(ths, key, asc) {
  for (const th of ths) {
    if (!th.dataset.key) continue;
    th.classList.toggle("sorted", th.dataset.key === key);
    th.classList.toggle("asc", th.dataset.key === key && asc);
    th.setAttribute("aria-sort", th.dataset.key === key ? (asc ? "ascending" : "descending") : "none");
  }
}
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const money = (x) => (x >= 1e9 ? `$${decimal(x / 1e9, 1)}B` : x >= 1e6 ? `$${decimal(x / 1e6, 1)}M` : x >= 1e3 ? `$${Math.round(x / 1e3)}k` : `$${Math.round(x)}`);
const range = (lo, hi) => (getLang() === "tr" ? `%${lo}-${hi}` : `${lo}-${hi}%`);

// Every request says which language the server's text (notices, score card, risks) should be in.
const api = (url, opts = {}) => fetch(url, { ...opts, headers: { ...opts.headers, "X-Lang": getLang() } });

// ---------- state ----------
// A search and a single-game analysis can run at the same time. keepPanel: the user analyzed a game
// during the current search, so its results must not replace that game in the panel.
const state = { games: [], selected: null, runId: null, result: null, shortlist: [], showAll: false,
  searching: false, analyzing: false, keepPanel: false, searchMax: 0 };
const SHOWN = 8; // rows of the ranking before "Show N more"

// ---------- toasts: every message the user should see goes through here ----------
const LIFETIME = { success: 6000, info: 7000, warning: 12000, error: 0 }; // 0 = stays until closed

function toast(level, title, message = "", hint = "") {
  const close = el("button", { class: "close", type: "button", "aria-label": t("Dismiss") }, "×");
  const node = el("div", { class: `toast ${level}`, role: level === "error" ? "alert" : "status" },
    el("span", { class: "icon", "aria-hidden": "true" }),
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

// Thrown when the user presses Cancel on a running search or market ranking.
class CancelledRun extends Error {}

// The run each status card's Cancel button stops: id once the server has started it.
const runCtl = { games: { id: null, cancelled: false }, markets: { id: null, cancelled: false } };

function cancelRun(kind) {
  const ctl = runCtl[kind];
  if (ctl.cancelled) return;
  ctl.cancelled = true;
  const box = kind === "games" ? $("#search-status") : $("#markets-status");
  box.querySelector(".cancel-run").textContent = t("Cancelling...");
  box.querySelector(".search-status-text").textContent = t("Stopping after the current step...");
  if (ctl.id) api(`/api/${kind === "games" ? "tag" : "market"}-runs/${ctl.id}/cancel`, { method: "POST" }).catch(() => {});
}

function startRun(kind) {
  Object.assign(runCtl[kind], { id: null, cancelled: false });
  const box = kind === "games" ? $("#search-status") : $("#markets-status");
  box.querySelector(".cancel-run").textContent = t("Cancel");
}

// After the server answers with the job id: a Cancel pressed meanwhile is sent now.
function runStarted(kind, id) {
  runCtl[kind].id = id;
  if (runCtl[kind].cancelled) {
    runCtl[kind].cancelled = false;
    cancelRun(kind);
    throw new CancelledRun();
  }
}

function notifyError(err, fallbackTitle = t("Something went wrong")) {
  if (err instanceof ApiError) return notify(err.notice);
  if (err instanceof TypeError) {
    return toast("error", t("Can't reach the Steam Researcher server"),
      t("The page lost its connection to the local server."),
      t("Is the Steam Researcher window still open? Start it again with Steam Researcher.bat, then reload this page."));
  }
  toast("error", fallbackTitle, err.message || String(err));
}

async function apiError(res) {
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (body?.notice) return new ApiError(body.notice);
  let detail = body?.detail;
  if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
  return new ApiError({ level: "error", title: t("Request failed (HTTP {status})", { status: res.status }), message: detail || res.statusText, hint: "" });
}

// ---------- opportunity map: 2D (always works) and 3D (needs three.js from the CDN + WebGL) ----------
const onMapSelect = (appid) => selectGame(appid);
const map2d = createMap2d($("#map"), { onSelect: onMapSelect, describe: mapCard, axes: () => state.result?.axes });
let map3d = null;
try {
  const { createMap } = await import("/static/map3d.js");
  const m = createMap($("#map"), { onSelect: onMapSelect, describe: mapCard });
  if (!m.available) throw new Error("WebGL is disabled in this browser");
  map3d = m;
} catch (err) {
  console.error(err);
  toast("warning", t("3D map unavailable"),
    t("The 3D library couldn't load (no internet, the CDN is blocked, or WebGL is off)."),
    t("The 2D map shows the same games. Reload the page to try 3D again."));
}
// Both maps always hold the current games and selection, so switching views is instant.
const map = {
  setGames(games) { map2d.setGames(games); map3d?.setGames(games); },
  select(appid) { map2d.select(appid); map3d?.select(appid); },
  relabel() { map2d.relabel(); map3d?.relabel(); },
};

const MAP_LEGEND = {
  "2d": () => t("Bubble size = est. revenue · free-to-play games get the smallest bubble · color = score · ratings exclude review-bomb periods"),
  "3d": () => t("x: demand · y: dissatisfaction · z: fixability · size: revenue · color: score · drag to orbit, scroll to zoom"),
};
let mapView = "3d";
function setMapView(view) {
  if (view !== "2d" && !map3d) view = "2d";
  else if (view !== "2d") view = "3d";
  map2d.setVisible(view === "2d");
  map3d?.setVisible(view === "3d");
  mapView = view;
  $("#map-legend").textContent = MAP_LEGEND[view]();
  if (!map3d) $('#map-view button[data-view="3d"]').title = t("3D map unavailable in this browser");
  for (const b of document.querySelectorAll("#map-view button")) {
    b.setAttribute("aria-pressed", String(b.dataset.view === view));
  }
  try { localStorage.setItem("mapView", view); } catch { /* private mode: just not remembered */ }
}
document.querySelectorAll("#map-view button").forEach((b) => b.addEventListener("click", () => setMapView(b.dataset.view)));
if (!map3d) {
  $('#map-view button[data-view="3d"]').disabled = true;
}
let savedView = "2d";
try { savedView = localStorage.getItem("mapView") || "2d"; } catch { /* storage blocked */ }
setMapView(savedView);

// The Games view shows the ranking as a list or as the map, never both.
let gamesMode = "table";
function setGamesMode(mode) {
  gamesMode = mode === "map" ? "map" : "table";
  $("#games-view .table-wrap").hidden = gamesMode !== "table";
  $("#map").hidden = gamesMode !== "map";
  $("#map-legend").hidden = gamesMode !== "map" || !state.games.length;
  $("#map-tools").hidden = gamesMode !== "map";
  for (const b of document.querySelectorAll("#games-mode button")) b.setAttribute("aria-pressed", String(b.dataset.mode === gamesMode));
  if (gamesMode === "map") setMapView(mapView); // resizes the shown map to its new box
  try { localStorage.setItem("gamesMode", gamesMode); } catch { /* storage blocked */ }
}
$("#games-mode").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (b) setGamesMode(b.dataset.mode);
});

// ---------- details drawer: opens with a game, closes with × (or ← on a phone) or Esc ----------
// Opening moves the focus into the drawer (unless the page opened it by itself, after a search);
// closing gives it back to what opened it, or to the game's row.
let drawerReturn = null;
function openDrawer(focus = true) {
  if (!$("#drawer").hidden) return;
  drawerReturn = document.activeElement;
  $("#drawer").hidden = false;
  document.body.classList.add("drawer-open");
  if (focus) (matchMedia("(max-width: 1000px)").matches ? $("#sheet-back") : $("#drawer-close")).focus({ preventScroll: true });
}
function closeDrawer() {
  const appid = state.selected;
  const focusInside = $("#drawer").contains(document.activeElement) || document.activeElement === document.body;
  $("#drawer").hidden = true;
  document.body.classList.remove("drawer-open");
  if (focusInside) {
    const back = drawerReturn?.isConnected && drawerReturn !== document.body ? drawerReturn
      : document.querySelector(`#ranking tr[data-appid="${appid}"]`);
    back?.focus({ preventScroll: true });
  }
  drawerReturn = null;
  state.selected = null;
  state.panelGame = null;
  map.select(null);
  highlightRow();
}
$("#drawer-close").addEventListener("click", closeDrawer);
$("#sheet-back").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  // Esc first closes whatever is open on top (tag list, filters, score card, help)
  if (e.key !== "Escape" || $("#drawer").hidden || e.defaultPrevented) return;
  if (e.target.closest?.("#tag-combo") || !tagPop.hidden || !$("#filters").hidden
    || document.querySelector("dialog[open]") || !scoreTip.hidden) return;
  closeDrawer();
});

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
  setButtonBusy($("#run"), on, on ? t("Searching...") : t("Search"));
  renderSummary(); // the AI chip hides while a search runs; the result is drawn before this flag clears
}

function setAnalyzing(on) {
  state.analyzing = on;
}

function stillRunning(what) {
  toast("info", t("Please wait"), what, t("Wait for it to finish, then try again."));
}

// ---------- the filters popover (under the title) ----------
function openFilters(open = true) {
  $("#filters").hidden = !open;
  $("#filters-toggle").setAttribute("aria-expanded", String(open));
}
$("#filters-toggle").addEventListener("click", () => openFilters($("#filters").hidden));
document.addEventListener("click", (e) => {
  if (!$("#filters").hidden && !e.target.closest(".filters-wrap, #toasts, #term-tip")) openFilters(false);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#filters").hidden) { openFilters(false); $("#filters-toggle").focus(); e.preventDefault(); }
});
document.querySelectorAll("input").forEach((i) => i.addEventListener("input", () => i.classList.remove("invalid")));

// ---------- filters and tags are remembered in this browser; presets fill the filter fields ----------
const FILTER_IDS = ["min-reviews", "lo", "hi", "max-games", "reviews"];
const PRESETS = {
  default: { "min-reviews": 100, lo: 5, hi: 70, "max-games": 15, reviews: 200 },
  proven: { "min-reviews": 500, lo: 5, hi: 70, "max-games": 15, reviews: 200 },
  quick: { "min-reviews": 100, lo: 5, hi: 70, "max-games": 8, reviews: 100 },
};

function loadSaved() {
  try { return JSON.parse(localStorage.getItem("filters") || "null"); } catch { return null; }
}

function saveFilters() {
  const saved = loadSaved() || {};
  const values = Object.fromEntries(FILTER_IDS.map((id) => [id, $(`#${id}`).value]));
  // The free-text fallback has no picks: keep the tags remembered from before.
  const tags = tagPicker.freeText ? saved.tags : tagPicker.picked;
  try { localStorage.setItem("filters", JSON.stringify({ values, tags })); } catch { /* storage blocked */ }
  filtersSummary();
}

// The filter button says what the filters are: "100+ reviews · 5-70% positive · top 15".
function filtersSummary() {
  const v = (id) => $(`#${id}`).value;
  $("#filters-summary").textContent = t("{min}+ reviews · {range} positive · top {n}",
    { min: fmt(+v("min-reviews") || 0), range: range(v("lo"), v("hi")), n: v("max-games") });
}

for (const id of FILTER_IDS) $(`#${id}`).addEventListener("change", saveFilters);
document.querySelectorAll("#filters [data-preset]").forEach((b) => b.addEventListener("click", () => {
  for (const [id, v] of Object.entries(PRESETS[b.dataset.preset])) {
    $(`#${id}`).value = v;
    $(`#${id}`).classList.remove("invalid");
  }
  saveFilters();
}));

const labelOf = (input) =>
  input.closest("label")?.firstChild?.textContent.trim() || input.getAttribute("aria-label") || t("This field");

function fieldError(input, message, hint = "") {
  input.classList.add("invalid");
  if (input.closest("#filters")) openFilters(true);
  input.focus();
  toast("error", t("Check \"{field}\"", { field: labelOf(input) }), message, hint);
}

// ---------- the search box: tick Steam tags (games must have all of them), or paste a game's AppID ----------
const MAX_TAGS = 5; // config.MAX_TAGS on the server
const tagInput = $("#tag");
const tagPop = $("#tag-pop");
const tagList = $("#tag-list");
// tags: Steam's catalog. shown: options in list order. freeText: the catalog failed to load, so the
// box takes comma-separated tags typed by hand.
const tagPicker = { tags: [], picked: [], shown: [], active: -1, freeText: false };

{ // the last filters and tags used in this browser
  const saved = loadSaved();
  if (saved?.values) {
    for (const id of FILTER_IDS) if (saved.values[id] != null && saved.values[id] !== "") $(`#${id}`).value = saved.values[id];
  }
  if (Array.isArray(saved?.tags)) tagPicker.picked = saved.tags.filter((x) => typeof x === "string").slice(0, MAX_TAGS);
  filtersSummary();
}

const isPicked = (t) => tagPicker.picked.includes(t);
const tagsLabel = (tags) => tags.join(" + ");
// "1330660" or a store link -> "1330660"; anything else -> null
const parseAppid = (text) => {
  const id = (text.trim().match(/\/app\/(\d+)/) || text.trim().match(/^(\d+)$/) || [])[1];
  return id && +id > 0 ? id : null;
};

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
  saveFilters();
  $("#tag-chips").replaceChildren(...tagPicker.picked.map((tag) =>
    el("span", { class: "tag-chip" }, tag,
      el("button", { type: "button", "aria-label": t("Remove {tag}", { tag }),
        onmousedown: (e) => e.preventDefault(), // don't steal focus from the filter box
        onclick: (e) => { e.stopPropagation(); togglePick(tag); } }, "×"))));
  if (tagPicker.freeText) return;
  const open = !tagPop.hidden;
  tagInput.placeholder = open ? t("Filter tags, or paste an AppID...") : tagPicker.picked.length ? "" : t("Add a tag, or paste an AppID");
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
  $("#tag-count").textContent = full ? t("{n} selected (the maximum)", { n: MAX_TAGS })
    : n ? t("{n} selected · games must have all of them", { n }) : t("Tick one or more tags");
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

// Ticked tags first (as of opening), then the rest. Typing in the box only narrows the list; an AppID
// or a store link offers that game instead. With nothing typed, the past searches are listed below.
function openTagList(query = tagInput.value) {
  const appid = parseAppid(query);
  const rows = [];
  tagPicker.shown = [];
  tagPicker.active = -1;
  if (appid) {
    rows.push(el("li", { class: "open-game", onclick: () => analyzeGame(appid) }, t("Open game {appid}", { appid })));
  } else if (tagPicker.tags.length) {
    const matches = matchTags(query);
    const picked = matches.filter(isPicked), rest = matches.filter((tag) => !isPicked(tag));
    tagPicker.shown = picked.concat(rest);
    let i = 0;
    const option = (tag) => el("li", { role: "option", id: `tag-opt-${i++}`, "data-tag": tag, onclick: () => togglePick(tag) },
      el("span", { class: "check", "aria-hidden": "true" }, "✓"), tag);
    const group = (title) => el("li", { class: "group label", role: "presentation" }, title);
    if (picked.length) rows.push(group(t("Selected")), ...picked.map(option));
    if (rest.length) rows.push(...(picked.length ? [group(t("All tags"))] : []), ...rest.map(option));
    if (!matches.length) rows.push(el("li", { class: "none" }, t("No Steam tag contains \"{query}\"", { query: query.trim() })));
  } else if (tagPicker.freeText && !query.trim()) {
    rows.push(el("li", { class: "none" }, t("Steam tags, comma-separated, e.g. Crafting, Survival")));
  }
  tagList.replaceChildren(...rows);
  tagList.hidden = !rows.length;
  $(".combo-foot").hidden = !!appid || tagPicker.freeText;
  const showRuns = !query.trim();
  $("#runs-section").hidden = !showRuns;
  const wasHidden = tagPop.hidden;
  tagPop.hidden = false;
  tagInput.setAttribute("aria-expanded", "true");
  if (query.trim() && tagPicker.shown.length) setActive(0);
  if (showRuns && (wasHidden || !runsLoaded)) loadRuns();
  renderChips();
  refreshList();
}

function closeTagList() {
  tagPop.hidden = true;
  // The filter is temporary (picks live in the chips); an AppID stays until it's opened.
  if (!tagPicker.freeText && !parseAppid(tagInput.value)) tagInput.value = "";
  tagInput.setAttribute("aria-expanded", "false");
  tagInput.removeAttribute("aria-activedescendant");
  runsLoaded = false;
  renderChips();
}

tagInput.addEventListener("focus", () => openTagList());
tagInput.addEventListener("input", () => openTagList());
// Focus moving into the list (a past search, with Tab) keeps it open; anywhere else closes it.
tagInput.addEventListener("blur", (e) => { if (!tagPop.contains(e.relatedTarget)) closeTagList(); });
tagPop.addEventListener("focusout", (e) => { if (!$("#tag-combo").contains(e.relatedTarget)) closeTagList(); });
// A click anywhere on the field (chips, empty space) opens the list.
$("#tag-combo").addEventListener("click", (e) => {
  if (tagPop.contains(e.target)) return;
  if (document.activeElement !== tagInput) tagInput.focus();
  else if (tagPop.hidden) openTagList();
});
tagPop.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus while ticking/scrolling
$("#tag-clear").addEventListener("click", () => {
  tagPicker.picked = [];
  renderChips();
  refreshList();
});
tagInput.addEventListener("keydown", (e) => {
  if (e.key === "Backspace" && !tagInput.value && tagPicker.picked.length && tagPicker.tags.length) {
    e.preventDefault();
    return togglePick(tagPicker.picked[tagPicker.picked.length - 1]);
  }
  if (tagPop.hidden) {
    if (e.key === "ArrowDown") { e.preventDefault(); openTagList(); }
    return; // Enter with the list closed submits the search as usual
  }
  const last = tagPicker.shown.length - 1;
  if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(last, tagPicker.active + 1)); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, tagPicker.active - 1)); }
  else if (e.key === "Enter") {
    if (parseAppid(tagInput.value) || tagPicker.freeText) return; // submits: opens the game / searches
    e.preventDefault(); // Enter ticks; it never submits while the tag list is open
    if (tagPicker.active >= 0) togglePick(tagPicker.shown[tagPicker.active]);
    else closeTagList();
  } else if (e.key === "Escape") closeTagList();
});

renderChips();

(async function loadTags() {
  try {
    const res = await api("/api/tags");
    if (!res.ok) throw await apiError(res);
    tagPicker.tags = (await res.json()).tags || [];
    const known = tagPicker.picked.filter((tag) => tagPicker.tags.includes(tag)); // e.g. a tag Steam renamed
    if (known.length !== tagPicker.picked.length) { tagPicker.picked = known; renderChips(); }
    if (document.activeElement === tagInput) openTagList();
  } catch (err) {
    // Fallback: type tags by hand, comma-separated.
    tagInput.value = tagPicker.picked.join(", ");
    tagPicker.picked = [];
    renderChips();
    tagPicker.freeText = true;
    tagInput.placeholder = t("Steam tags, comma-separated, e.g. Crafting, Survival");
    toast("warning", t("Tag list unavailable"),
      err instanceof ApiError ? err.notice.message : t("The list of Steam tags couldn't be loaded."),
      t("You can still type tags by hand, separated by commas, e.g. Crafting, Survival."));
  }
})();

// Our own text: the browser's validationMessage follows the OS language, not the page's.
function validityText(input) {
  const v = input.validity, { min, max, step } = input;
  if (v.valueMissing) return t("This field can't be empty.");
  if (v.badInput) return t("Enter a number.");
  if (v.rangeUnderflow || v.rangeOverflow) {
    return max ? t("Enter a number from {min} to {max}.", { min, max }) : t("Enter a number of at least {min}.", { min });
  }
  if (v.stepMismatch) {
    return t("Use a multiple of {step}, e.g. {example}.", { step, example: Math.round(+input.value / +step) * +step || step });
  }
  return input.validationMessage;
}

// The browser's own validation cancels submit before our handler runs. The invalid field is often
// inside the closed Filters popover, so its bubble can't appear. Re-open the popover and show a toast,
// so this is never silent.
$("#tag-form").addEventListener("invalid", (e) => {
  e.preventDefault(); // our toast replaces the browser bubble
  const input = e.target;
  if (document.querySelector("#filters .invalid")) return; // one toast per submit
  fieldError(input, validityText(input));
}, true);

$("#run").addEventListener("click", () => {
  document.querySelectorAll("#filters .invalid, #tag.invalid").forEach((i) => i.classList.remove("invalid"));
});

$("#tag-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const appid = !tagPicker.freeText && parseAppid(tagInput.value);
  if (appid) return analyzeGame(appid);
  if (state.searching) return stillRunning(t("A search is still running."));
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
    return fieldError(tagInput, t("Pick at least one tag, or paste a game's AppID."),
      !tagPicker.freeText ? t("Click the search box and tick one or more tags in the list.") : t("Type tags separated by commas, e.g. Crafting, Survival."));
  }
  if (body.tags.length > MAX_TAGS) {
    return fieldError(tagInput, t("Use at most {n} tags.", { n: MAX_TAGS }), t("Games must have every tag, so a few tags is usually enough."));
  }
  const label = tagsLabel(body.tags);
  if (body.lo > body.hi) return rangeError(body);
  tagInput.blur();
  setTableView("games");
  state.keepPanel = false;
  state.searchMax = body.max_games;
  setSearching(true);
  startRun("games");
  renderTitle(label);
  try {
    // Inside the try: if anything here fails, the button and card reset and the error is shown,
    // instead of a "Searching..." that never ends.
    searchStatus({ status: "running", done: 0, total: 0, step: 0, message: t("Fetching games tagged {tag}...", { tag: label }) });
    renderLive(null);
    const res = await api("/api/tag-runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw await apiError(res);
    const { id, notices } = await res.json();
    runStarted("games", id);
    notifyAll(notices);
    await poll(id);
  } catch (err) {
    if (err instanceof CancelledRun) {
      toast("info", t("Search cancelled"), state.games.length ? t("The previous results are still shown.") : "", "");
    } else {
      notifyError(err, t("Search failed"));
    }
    renderTitle();
  } finally {
    setSearching(false);
    searchStatus(null);
    renderLive(null);
  }
});

function rangeError(body) {
  $("#lo").classList.add("invalid");
  return fieldError($("#hi"), t("'% positive from' ({lo}) is higher than '% positive to' ({hi}).", body),
    t("Swap the two values, e.g. 5 to 70."));
}

// "~3 min left": the server estimates the time left from the pace so far (null: no estimate yet).
const etaText = (eta) => (eta == null ? "" : eta < 60 ? t("under a minute left") : t("~{n} min left", { n: Math.round(eta / 60) }));

// A progress card; job null hides it.
function statusBox(box, title, job, count) {
  box.hidden = job == null;
  if (job == null) return;
  box.querySelector(".search-status-title").textContent = title;
  box.querySelector(".search-status-count").textContent = count;
  box.querySelector(".search-status-eta").textContent = etaText(job.eta);
  box.querySelector(".search-status-fill").style.width = `${Math.round((job.total ? job.done / job.total : 0) * 100)}%`;
  if (!runCtl[box.id === "search-status" ? "games" : "markets"].cancelled) {
    box.querySelector(".search-status-text").textContent = job.message || "";
  }
}

// The search's card: step 1 lists the tags' games, step 2 checks and analyzes them (the games appear
// one by one), step 3 ranks them, which is too quick to show.
function searchStatus(job) {
  const box = $("#search-status");
  if (job == null) return statusBox(box, "", null);
  const step = job.games?.length ? 2 : 1;
  box.querySelector(".step-badge").textContent = t("Step {n} of 3", { n: step });
  for (const li of box.querySelectorAll(".steps li")) {
    li.classList.toggle("done", +li.dataset.step < step);
    li.classList.toggle("now", +li.dataset.step === step);
  }
  statusBox(box, step === 1 ? t("Listing the games with these tags") : t("Reading reviews and scoring games"), job,
    job.total ? `${job.done} / ${job.total}` : "");
}

// The run's warnings stay above the ranking after their toasts fade (each can be dismissed).
function renderResultNotices(list) {
  const items = (list || []).filter((n) => n.level === "warning" || n.level === "info").map((n) => {
    const item = el("li", { class: `result-notice ${n.level}` },
      el("b", {}, n.title), " ", n.message, n.hint ? el("span", { class: "muted" }, ` ${n.hint}`) : null);
    item.append(el("button", { type: "button", class: "close", "aria-label": t("Dismiss"), onclick: () => {
      item.remove();
      $("#result-notices").hidden = !$("#result-notices").children.length;
    } }, "×"));
    return item;
  });
  $("#result-notices").replaceChildren(...items);
  $("#result-notices").hidden = !items.length;
}

// While a search runs: each game as it goes, finished ones ranked by score.
const STAGES = {
  store: () => t("Store check"),
  details: () => t("Store data and risks"),
  reviews: (g) => (g.total ? t("Reading reviews · {done} / {total}", { done: g.done, total: g.total }) : t("Reading reviews")),
  done: () => t("Done"),
  failed: () => t("Failed"),
};
function renderLive(job) {
  const games = job?.games || [];
  $("#live").hidden = !games.length;
  if (!games.length) return;
  const done = games.filter((g) => g.stage === "done").sort((a, b) => b.score - a.score);
  const rest = games.filter((g) => g.stage !== "done");
  const row = (g, i) => {
    const finished = g.stage === "done";
    const skel = () => el("span", { class: "skel" });
    return el("tr", { class: finished ? "" : "busy" },
      el("td", { class: "num muted" }, finished ? i + 1 : "–"),
      el("td", {}, g.name),
      el("td", {}, finished ? pill(g.score, "small") : skel()),
      el("td", {}, finished && g.rating != null ? percent(g.rating) : skel()),
      el("td", { class: "num" }, finished && g.reviews != null ? fmt(g.reviews) : skel()),
      el("td", {}, el("span", { class: `stage ${g.stage}` }, (STAGES[g.stage] || (() => g.stage))(g))));
  };
  $("#live-table tbody").replaceChildren(...done.map(row), ...rest.map((g) => row(g)));
  const started = games.filter((g) => g.stage !== "store").length;
  const queued = Math.max(0, state.searchMax - started);
  $("#live-queued").textContent = queued
    ? t("Up to {n} more queued · each game starts as soon as it passes the store check", { n: queued }) : "";
}

async function poll(id) {
  for (;;) {
    const res = await api(`/api/tag-runs/${id}`);
    if (res.status === 404) {
      throw new ApiError({ level: "error", title: t("The search was interrupted"),
        message: t("The server was restarted, so this run was lost."), hint: t("Press Search again.") });
    }
    if (!res.ok) throw await apiError(res);
    const job = await res.json();
    if (job.status === "cancelled" || runCtl.games.cancelled) throw new CancelledRun();
    if (job.status === "error") throw new ApiError(job.error);
    if (job.status === "done") return showResult(job.result, id);
    searchStatus(job);
    renderLive(job);
    if (job.slow) notify(job.slow);
    await new Promise((r) => setTimeout(r, 1000));
    if (runCtl.games.cancelled) throw new CancelledRun();
  }
}

$("#search-status .cancel-run").addEventListener("click", () => cancelRun("games"));
$("#markets-status .cancel-run").addEventListener("click", () => cancelRun("markets"));

// One game by AppID (pasted into the search box), shown in the drawer.
async function analyzeGame(appid) {
  if (state.analyzing) return stillRunning(t("The analysis of the previous game is still running."));
  tagInput.value = "";
  tagInput.blur();
  closeTagList();
  if (state.games.some((g) => g.game.appid === +appid)) return selectGame(+appid);

  if (state.searching) state.keepPanel = true; // the finishing search must not replace this game
  setAnalyzing(true);
  const panel = $("#panel");
  const previous = [...panel.childNodes];
  const wasOpen = !$("#drawer").hidden;
  openDrawer();
  panel.replaceChildren(el("div", { class: "empty loading" },
    el("div", {},
      el("p", {}, t("Analyzing AppID {appid}...", { appid })),
      el("div", { class: "progress-bar indeterminate" }, el("span")),
      el("p", { class: "muted" }, t("The first time can take ~15 s, longer if Steam's review server is slow.")))));
  try {
    const g = await fetchGame(appid);
    state.selected = null;
    map.select(null);
    highlightRow();
    renderPanel(g);
    if (state.games.length) {
      toast("info", t("Shown in the details panel"), t("{name} isn't part of the current ranking.", { name: g.game.name }));
    }
    notifyAll(g.notices);
  } catch (err) {
    panel.replaceChildren(...previous);
    if (!wasOpen) closeDrawer();
    state.keepPanel = false;
    notifyError(err, t("Analysis failed"));
  } finally {
    setAnalyzing(false);
  }
}

async function fetchGame(appid) {
  const res = await api(`/api/games/${appid}?reviews=${+$("#reviews").value || 300}`);
  if (!res.ok) throw await apiError(res);
  return res.json();
}

// ---------- results ----------
// The title area of the Games view: the search's tags, or (while one runs) the tags being searched.
function renderTitle(searching = null) {
  const r = state.result;
  $("#games-kicker").hidden = !searching;
  $("#games-kicker").textContent = searching ? t("Games · searching") : "";
  $("#table-title").textContent = searching || r?.tag || t("Find underserved audiences");
  renderMarketLine(searching ? null : r);
  if (!searching && !r) $("#market-line").textContent = t("Steam games that many people bought but rate poorly, ranked as chances for a better game.");
  renderSummary();
}

// quiet: the same result again in another language, so no toasts and the selection stays.
function showResult(result, id, quiet = false) {
  state.games = result.games.map((g, i) => ({ ...g, rank: i + 1 }));
  state.result = result;
  state.runId = id;
  if (!quiet) state.showAll = false;
  const notes = [
    t("{candidates} of {total} games have ≥ {min} reviews and {range} positive; analyzed the {n} with most reviews.", {
      candidates: fmt(result.n_candidates), total: fmt(result.n_tag_games), min: fmt(result.min_reviews),
      range: range(result.lo, result.hi), n: state.games.length }),
  ];
  if (result.not_games.length) notes.push(t("Excluded non-games: {names}.", { names: result.not_games.join(", ") }));
  if (result.compared) notes.push(t("▲/▼ = score change since your previous run with these tags and filters."));
  $("#table-note").textContent = notes.join(" ");
  renderResultNotices(result.notices);
  if (!quiet) $("#opp-summary").hidden = true;
  renderTitle();
  $("#download").href = `/api/tag-runs/${id}/report.md?lang=${getLang()}`;
  $("#download-csv").href = `/api/tag-runs/${id}/ranking.csv?lang=${getLang()}`;
  $("#downloads").hidden = !state.games.length;
  if (!quiet) setTableView("games");

  $("#table-empty").hidden = state.games.length > 0;
  $("#map-legend").hidden = gamesMode !== "map" || !state.games.length;
  map.setGames(state.games);
  renderTable();
  if (quiet) {
    const g = state.games.find((x) => x.game.appid === state.selected);
    if (g) renderPanel(g, panelTab(), false);
    return;
  }
  notifyAll(result.notices);
  if (state.keepPanel) {
    // the panel shows a game the user analyzed during the search: leave it there
  } else if (state.games.length) {
    // On a narrow screen the drawer covers the page: show the ranking and let the user pick.
    if (matchMedia("(min-width: 1001px)").matches) selectGame(state.games[0].game.appid, false);
    else closeDrawer();
  } else {
    closeDrawer();
    const why = (result.notices || []).find((n) => n.level === "warning");
    $("#table-empty").replaceChildren(el("p", {},
      why ? `${why.title}. ${why.hint}` : t("No games to show. Try a lower minimum or a wider % range.")));
  }
}

// The whole tag in one sentence under the title: how many of its games with demand let players down,
// how many please them, and the unmet share (described, not a forecast: see the backtest).
function renderMarketLine(r) {
  const line = $("#market-line");
  const m = r?.market;
  if (!m) return line.replaceChildren();
  const rated = m.n_underserved + m.n_well_served;
  if (rated < 5) {
    return line.replaceChildren(t("{n} games with demand; too few rated clearly to describe this market.", { n: fmt(m.n_demand) }),
      info("with_demand"));
  }
  line.replaceChildren(
    t("{under} of {demand} games with demand leave players disappointed ({range} positive); {well} please them ({pct}+).", {
      under: fmt(m.n_underserved), demand: fmt(m.n_demand), range: range(r.lo, r.hi), well: fmt(m.n_well_served),
      pct: percent(r.well_served) }),
    " ", el("b", {}, t("Unmet share {pct}", { pct: pct(m.gap) })), info("unmet_share"));
}

// ---------- opportunity summary: written on request by a local LLM (Ollama), saved with the run ----------
// The AI button under the title opens it; it says whether a summary is written yet.
function renderSummary() {
  const chip = $("#ai-chip"), box = $("#opp-summary");
  const r = state.result;
  chip.hidden = !r || !state.games.length || state.searching;
  if (chip.hidden) { box.hidden = true; return; }
  const s = r.summary;
  $("#ai-chip-text").textContent = state.summarizing ? t("Writing the AI summary... (about a minute)")
    : s ? t("AI summary: {pitch} · Read", { pitch: clip(s.pitch || "", 70) }) : t("Write an AI summary");
  chip.setAttribute("aria-expanded", String(!box.hidden));
  const body = box.querySelector(".opp-body");
  const price = priceLine(r.market);
  if (!s) {
    const button = el("button", { type: "button", class: "ghost", onclick: writeSummary });
    setButtonBusy(button, !!state.summarizing, state.summarizing ? t("Writing...") : t("Write summary"));
    body.replaceChildren(price || "", el("div", { class: "opp-empty" },
      el("p", {}, t("What players love, the complaints these games share, and what a better game would do. Written by the local model {model} (Ollama) from this ranking, in about a minute.", { model: r.llm_model })),
      button));
    return;
  }
  const byName = new Map(state.games.map((g) => [g.game.name, g.game.appid]));
  const chips = (names) => el("div", { class: "opp-games" }, names.map((name) =>
    byName.has(name)
      ? el("button", { type: "button", class: "chip", onclick: () => selectGame(byName.get(name)) }, name)
      : el("span", { class: "chip" }, name)));
  const section = (title, points) => !points.length ? null : el("div", {},
    el("h4", {}, title),
    el("ul", {}, points.map((p) => el("li", {}, p.text, p.games.length ? chips(p.games) : null))));
  body.replaceChildren(
    s.pitch ? el("p", { class: "opp-pitch" }, s.pitch) : null,
    price,
    el("p", { class: "opp-note" }, t("Written by the local model {model}. It can be wrong: check each point against the games it names.", { model: s.model })),
    el("div", { class: "opp-sections" },
      section(t("What players love"), s.loved),
      section(t("Shared complaints"), s.complaints),
      section(t("A better game would"), s.build),
      section(t("Caveats"), s.caveats)),
  );
}
const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);
$("#ai-chip").addEventListener("click", () => {
  $("#opp-summary").hidden = !$("#opp-summary").hidden;
  renderSummary();
});

// The price range of the market, worked out from the data (never by the model): shown with the summary.
function priceLine(m) {
  if (m?.price_median == null) return null;
  const usd = (x) => "$" + decimal(x, 2);
  let text = t("Price range in this market: median {median}, middle half {lo}–{hi}",
    { median: usd(m.price_median), lo: usd(m.price_p25), hi: usd(m.price_p75) });
  if (m.well_served_price_median != null) text += t(" · well-served games {price}", { price: usd(m.well_served_price_median) });
  return el("p", { class: "opp-price" }, text, info("price_range"));
}

async function writeSummary() {
  if (state.summarizing || state.gameSummarizing) return stillRunning(t("The opportunity summary is being written."));
  const id = state.runId;
  state.summarizing = true;
  renderSummary();
  try {
    const res = await api(`/api/tag-runs/${id}/summary`, { method: "POST" });
    if (!res.ok) throw await apiError(res);
    const data = await res.json();
    if (state.runId === id && state.result) {
      state.result.summary = data.summary;
      $("#opp-summary").hidden = false;
    }
  } catch (err) {
    notifyError(err);
  } finally {
    state.summarizing = false;
    renderSummary();
  }
}

// ---------- Games | Markets | Shortlist ----------
let tableView = "games";

function setTableView(view) {
  tableView = view;
  for (const b of document.querySelectorAll("#table-view button")) b.setAttribute("aria-pressed", String(b.dataset.view === view));
  $("#games-view").hidden = view !== "games";
  $("#markets-view").hidden = view !== "markets";
  $("#shortlist-view").hidden = view !== "shortlist";
  // The Filters button sits under the title of the view that uses it (Markets uses the first three).
  const filters = document.querySelector(".filters-wrap");
  if (view === "markets") $("#markets-filter-slot").append(filters);
  else if (view === "games") $("#games-view .chip-row").prepend(filters);
  if (view === "shortlist") renderShortlist();
}
$("#table-view").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b) setTableView(b.dataset.view);
});

const markets = { rows: [], sort: { key: "rank", asc: true }, running: false, result: null };
const BIG_MARKET = 20; // "Only tags with 20+ games with demand"

function marketsButton() {
  setButtonBusy($("#markets-run"), markets.running,
    markets.running ? t("Building...") : markets.result ? t("Rebuild · about 7 min") : t("Build market ranking"));
}

$("#markets-run").addEventListener("click", async () => {
  if (markets.running) return stillRunning(t("The market ranking is still running."));
  const body = { min_reviews: +$("#min-reviews").value, lo: +$("#lo").value, hi: +$("#hi").value };
  if (body.lo > body.hi) return rangeError(body);
  const box = $("#markets-status");
  markets.running = true;
  marketsButton();
  startRun("markets");
  try {
    statusBox(box, t("Building the market ranking..."), { done: 0, total: 0, message: t("Reading the Steam tag list") }, "");
    const res = await api("/api/market-runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw await apiError(res);
    const { id, notices } = await res.json();
    runStarted("markets", id);
    notifyAll(notices);
    for (;;) {
      const r = await api(`/api/market-runs/${id}`);
      if (r.status === 404) {
        throw new ApiError({ level: "error", title: t("The market ranking was interrupted"),
          message: t("The server was restarted, so this run was lost."), hint: t("Press Build market ranking again.") });
      }
      if (!r.ok) throw await apiError(r);
      const job = await r.json();
      if (job.status === "cancelled" || runCtl.markets.cancelled) throw new CancelledRun();
      if (job.status === "error") throw new ApiError(job.error);
      if (job.status === "done") { showMarkets(job.result); break; }
      statusBox(box, t("Building the market ranking..."), job,
        job.total ? t("{done} / {total} tags", { done: job.done, total: job.total }) : "");
      await new Promise((r2) => setTimeout(r2, 1000));
      if (runCtl.markets.cancelled) throw new CancelledRun();
    }
  } catch (err) {
    if (err instanceof CancelledRun) toast("info", t("Market ranking cancelled"), t("Tags read so far stay cached, so the next build is faster."));
    else notifyError(err, t("Market ranking failed"));
  } finally {
    markets.running = false;
    marketsButton();
    statusBox(box, "", null);
  }
});

// The intro until a ranking is built; then what the ranking holds.
function marketsText() {
  const result = markets.result;
  const well = percent(result?.well_served ?? 85);
  $("#markets-well-head").textContent = t("Well served ({pct}+)", { pct: well });
  $("#markets-key-under").textContent = t("Underserved ({range})", { range: range(result?.lo ?? 5, result?.hi ?? 70) });
  $("#markets-key-well").textContent = t("Well served ({pct}+)", { pct: well });
  if (!result) {
    $("#markets-note").textContent = t("Rank every Steam tag by its games with demand that players rate poorly. Uses the Filters; the first build takes ~7 minutes, then ~1 day from the cache.");
    return;
  }
  const notes = [t("{n} tags ranked by unmet share, games with ≥ {min} reviews; underserved = {range} positive. Broad tags (1,000+ games) and tags with under 3 underserved games come last.", {
    n: markets.rows.length, min: fmt(result.min_reviews), range: range(result.lo, result.hi) })];
  if (result.skipped.length) notes.push(t("{n} tags SteamSpy can't search are left out (search them one by one).", { n: result.skipped.length }));
  $("#markets-note").textContent = notes.join(" ");
}

function showMarkets(result, quiet = false) {
  markets.result = result;
  markets.rows = result.rows.map((r, i) => ({ ...r, rank: i + 1 }));
  if (!quiet) markets.sort = { key: "rank", asc: true };
  marketsText();
  marketsButton();
  if (result.failed.length && !quiet) {
    toast("warning", t("{n} tags couldn't be read", { n: result.failed.length }), result.failed.slice(0, 5).map((f) => f.tag).join(", "),
      t("They are missing from the ranking. Rebuild later to retry them."));
  }
  renderMarkets();
}

// The same three words as the sentence under a search's title.
function marketVerdict(r) {
  if (r.n_underserved + r.n_well_served < 5) return [t("Too few to tell"), ""];
  return r.gap >= 0.5 ? [t("Underserved"), "under"] : r.gap >= 0.3 ? [t("Mixed"), "mixed"] : [t("Well served"), "well"];
}

function renderMarkets() {
  const has = !!markets.result;
  for (const id of ["#market-cards", "#market-tools", "#markets-wrap"]) $(id).hidden = !has;
  if (!has) return;
  const q = $("#market-find").value.trim().toLocaleLowerCase();
  const big = $("#market-big").checked;
  const { key, asc } = markets.sort;
  const val = (r) => (key === "tag" ? r.tag.toLowerCase() : r[key]);
  const shown = markets.rows.filter((r) => (!q || r.tag.toLocaleLowerCase().includes(q)) && (!big || r.n_demand >= BIG_MARKET));
  const rows = shown.sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (asc ? 1 : -1));
  markSorted(document.querySelectorAll("#markets th"), key, asc);
  const n = fmt;
  $("#markets tbody").replaceChildren(...rows.map((r) => {
    const [verdict, cls] = marketVerdict(r);
    return clickable(el("tr", { title: t("Search {tag}", { tag: r.tag }) },
      el("td", { class: "rank" }, r.rank),
      el("td", { class: "tag" }, r.tag),
      el("td", { class: "num dim" }, n(r.n_games)),
      el("td", { class: "num" }, n(r.n_demand)),
      el("td", { class: "num under" }, n(r.n_underserved)),
      el("td", { class: "num dim" }, n(r.n_well_served)),
      el("td", {}, el("div", { class: "share-cell" },
        el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round(r.gap * 100)}%` })),
        el("span", {}, pct(r.gap)))),
      el("td", {}, el("span", { class: `verdict-tag ${cls}` }, verdict)),
    ), () => searchTag(r.tag));
  }));
  $("#markets-shown").textContent = t("{n} of {total} tags shown · click a tag to search it", { n: rows.length, total: markets.rows.length });
  // The top three by the server's order (unmet share, broad and thin tags last), among the shown ones.
  const top = [...shown].sort((a, b) => a.rank - b.rank).slice(0, 3);
  $("#market-cards").hidden = !top.length;
  $("#market-cards").replaceChildren(...top.map((r) => el("button", { type: "button", class: "market-card", onclick: () => searchTag(r.tag) },
    el("span", { class: "top" }, `#${r.rank}`, el("b", {}, marketVerdict(r)[0])),
    el("span", { class: "tag" }, r.tag),
    el("span", { class: "share" }, el("b", {}, pct(r.gap)),
      el("span", {}, t("unmet · {under} underserved vs {well} well served", { under: n(r.n_underserved), well: n(r.n_well_served) }))),
    el("span", { class: "go" }, t("Search this tag →")))));
}
$("#market-find").addEventListener("input", renderMarkets);
$("#market-big").addEventListener("change", renderMarkets);

document.querySelectorAll("#markets th[data-key]").forEach((th) => clickable(th, () => {
  const key = th.dataset.key, s = markets.sort;
  markets.sort = { key, asc: s.key === key ? !s.asc : key === "tag" || key === "rank" };
  renderMarkets();
}));

// From the Markets view: search that one tag as a normal games search.
function searchTag(tag) {
  if (state.searching) return stillRunning(t("A search is still running."));
  if (tagPicker.freeText) tagInput.value = tag;
  else { tagPicker.picked = [tag]; renderChips(); }
  setTableView("games");
  $("#tag-form").requestSubmit();
}

// ---------- "How it works": a help dialog (static text in index.html) ----------
const help = $("#help");
$("#help-toggle").addEventListener("click", () => help.showModal());
help.addEventListener("click", (e) => { if (e.target === help) help.close(); }); // a click on the backdrop

// From a tag chip in the panel: the same, and say that the picked tags were replaced.
function searchOneTag(tag) {
  if (!state.searching) toast("info", t("Searching {tag}", { tag }), t("Only this tag; your other tags were set aside."));
  searchTag(tag);
}

// ---------- Past searches: every finished search and market ranking is saved on the server ----------
// Listed in the search box's dropdown while nothing is typed.
let runsLoaded = false;
async function loadRuns() {
  runsLoaded = true;
  const list = $("#runs-list");
  list.replaceChildren(el("li", { class: "run-empty" }, t("Loading...")));
  try {
    const res = await api("/api/runs");
    if (!res.ok) throw await apiError(res);
    const { runs } = await res.json();
    if (!runs.length) {
      list.replaceChildren(el("li", { class: "run-empty" }, t("No saved runs yet. Finished searches appear here.")));
      return;
    }
    const count = (r) => (r.kind === "market" ? t("{n} tags", { n: r.n })
      : r.n === 1 ? t("{n} game", { n: r.n }) : t("{n} games", { n: r.n }));
    list.replaceChildren(...runs.map((r) => {
      const item = clickable(el("li", { class: r.id === state.runId ? "current" : "" },
        el("div", { class: "run-main" },
          el("b", {}, r.kind === "market" ? t("Markets: all tags") : r.label),
          el("span", {}, `${dateTime(r.created)} · ${count(r)}`)),
        el("button", { type: "button", class: "run-del", tabindex: "-1", title: t("Delete this run"), "aria-label": t("Delete run {label}", { label: r.label }),
          onclick: (e) => { e.stopPropagation(); deleteRun(r, item); } }, "×")), () => openRun(r));
      return item;
    }));
  } catch (err) {
    list.replaceChildren();
    notifyError(err, t("Couldn't load past runs"));
  }
}

async function deleteRun(r, item) {
  try {
    const res = await api(`/api/runs/${r.id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 404) throw await apiError(res);
    item.remove();
    if (!$("#runs-list").children.length) {
      $("#runs-list").replaceChildren(el("li", { class: "run-empty" }, t("No saved runs yet. Finished searches appear here.")));
    }
  } catch (err) {
    notifyError(err, t("Couldn't delete the run"));
  }
}

async function openRun(r) {
  if (r.kind === "tag" && state.searching) return stillRunning(t("A search is still running."));
  tagInput.blur();
  closeTagList();
  try {
    const res = await api(`/api/${r.kind === "market" ? "market" : "tag"}-runs/${r.id}`);
    if (!res.ok) throw await apiError(res);
    const job = await res.json();
    if (job.status !== "done") throw new ApiError({ level: "info", title: t("Still running"), message: t("This run hasn't finished yet.") });
    if (r.kind === "market") {
      showMarkets(job.result);
      setTableView("markets");
      return;
    }
    const res2 = job.result;
    // Put its tags and filters back, so Search reruns exactly this search.
    if (tagPicker.freeText) tagInput.value = res2.tags.join(", ");
    else { tagPicker.picked = [...res2.tags]; renderChips(); }
    $("#min-reviews").value = res2.min_reviews;
    $("#lo").value = res2.lo;
    $("#hi").value = res2.hi;
    saveFilters();
    state.keepPanel = false;
    showResult(res2, r.id);
  } catch (err) {
    notifyError(err, t("Couldn't open the run"));
  }
}

// The hover card of a map bubble: the same numbers as the list and the drawer.
function mapCard(g) {
  const o = g.opportunity, top = g.mining?.categories[0];
  const adjusted = Math.round(o.effective_rating) !== Math.round(g.rating);
  const cell = (label, ...value) => el("div", {}, el("span", {}, label), ...value);
  return el("div", { class: "tt" },
    el("div", { class: "tt-head" }, el("b", {}, g.game.name), pill(o.score, "small")),
    el("div", { class: "tt-grid" },
      cell(t("Rating"), percent(adjusted ? o.effective_rating : g.rating), adjusted ? el("em", {}, " ", t("w/o bombs")) : null),
      cell(t("Reviews"), fmt(g.reviews)),
      cell(t("Est. revenue"), g.price ? money(g.box.gross_mid) : "F2P"),
      cell(t("Top complaint"), top ? `${top.label} ${pct(top.share)}` : "-")),
    el("span", { class: "tt-foot" }, t("Click to open details")));
}

// Score change since the previous run with the same tags and filters (only present when one exists).
function delta(g) {
  if (g.new) return el("span", { class: "delta new", title: t("Not in your previous run with these tags") }, t("new"));
  if (g.score_change == null) return null;
  const d = Math.round(g.score_change);
  return el("span", { class: `delta ${d > 0 ? "up" : d < 0 ? "down" : "same"}`, title: t("Change since your previous run with these tags and filters") },
    d > 0 ? `▲${d}` : d < 0 ? `▼${-d}` : "=");
}

// The score as a tinted pill (violet 65+, near-white 45+, gray under).
function pill(score, size = "") {
  return el("span", { class: `pill ${scoreLevel(score)} ${size}` }, Math.round(score));
}

// The risks that cost points, as in the score card.
const penalties = (g) => g.score_explained?.penalties || [];

function renderTable() {
  const games = state.games;
  const shown = state.showAll ? games : games.slice(0, SHOWN);
  const maxShare = Math.max(0.01, ...games.map((g) => g.mining?.categories[0]?.share ?? 0));
  $("#ranking tbody").replaceChildren(...shown.map((g) => {
    const o = g.opportunity;
    const top = g.mining?.categories[0];
    const risks = penalties(g);
    const badge = o.penalty > 0 ? el("span", { class: "risk-badge", title: risks.map((p) => `${p.label} -${p.points}`).join(", "),
      "aria-label": t("Risk penalty -{points}", { points: Math.round(o.penalty) }) }, `⚠ −${Math.round(o.penalty)}`) : null;
    return clickable(el("tr", { "data-appid": g.game.appid },
      el("td", {}, g.rank),
      el("td", {}, el("div", { class: "game-cell" }, el("span", { class: "game-name" }, g.game.name), badge)),
      el("td", {}, scoreAnchor(el("span", { class: `pill ${scoreLevel(o.score)} score-pill`,
        "aria-label": t("Score {score}. How it is calculated", { score: Math.round(o.score) }) }, Math.round(o.score)), g), delta(g)),
      el("td", {}, top ? el("div", { class: "complaint-cell" },
        el("span", { class: "name", title: top.label }, top.label),
        el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round((top.share / maxShare) * 100)}%` })),
        el("span", { class: "pct" }, pct(top.share))) : el("span", { class: "muted" }, "-")),
      el("td", { class: "num" }, g.price ? money(g.box.gross_mid) : "F2P"),
    ), () => selectGame(g.game.appid));
  }));
  const more = games.length - shown.length;
  $("#show-more").hidden = more <= 0;
  $("#show-more").textContent = t("Show {n} more", { n: more });
  highlightRow();
}
$("#show-more").addEventListener("click", () => {
  state.showAll = true;
  renderTable();
});

// ---------- shortlist: starred games with a note, kept on the server across runs ----------
const isStarred = (appid) => state.shortlist.some((s) => s.appid === appid);

// The drawer's Shortlist button (the server keeps a snapshot of the game from this run).
function starButton(appid) {
  const on = isStarred(appid);
  const label = on ? t("Remove from shortlist") : t("Add to shortlist");
  return el("button", { type: "button", class: on ? "star on" : "star", "data-appid": appid, "aria-pressed": String(on),
    "aria-label": label, title: label, onclick: (e) => { e.stopPropagation(); toggleStar(appid); } },
  el("span", { class: "icon", "aria-hidden": "true" }, on ? "★" : "☆"), on ? t("Starred") : t("Shortlist"));
}

function refreshStars() {
  for (const b of document.querySelectorAll(".star[data-appid]")) b.replaceWith(starButton(+b.dataset.appid));
  $("#shortlist-count").textContent = state.shortlist.length || "";
  if (tableView === "shortlist") renderShortlist();
}

async function shortlistCall(path, options) {
  const res = await api(path, options);
  if (!res.ok) throw await apiError(res);
  state.shortlist = (await res.json()).games;
}

async function toggleStar(appid) {
  try {
    if (isStarred(appid)) await shortlistCall(`/api/shortlist/${appid}`, { method: "DELETE" });
    else {
      // A game of the ranking is starred as it is in this run; one analyzed by AppID as the server last analyzed it.
      const inRun = state.games.some((g) => g.game.appid === appid);
      await shortlistCall(`/api/shortlist/${appid}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(inRun ? { run_id: state.runId } : {}) });
    }
  } catch (err) {
    notifyError(err);
  }
  refreshStars();
}

async function loadShortlist() {
  try { await shortlistCall("/api/shortlist"); } catch { /* shown as empty; the next star call reports errors */ }
  refreshStars();
}

// "today", "3 days ago": when a game was starred
function ago(seconds) {
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400);
  return days <= 0 ? t("today") : days === 1 ? t("yesterday") : t("{n} days ago", { n: days });
}

function renderShortlist() {
  const list = state.shortlist;
  $("#shortlist-title").textContent = list.length ? t("{n} games worth a second look", { n: list.length }) : t("Shortlist");
  $("#shortlist-note").textContent = list.length ? "" : t("No games yet. Open a game and press Shortlist to keep it here.");
  $("#shortlist-note").hidden = !!list.length;
  $("#shortlist-csv").hidden = !list.length;
  $("#shortlist-foot").hidden = !list.length;
  $("#shortlist").replaceChildren(...list.map((s) => {
    const note = el("textarea", { class: "note", rows: "3", maxlength: "2000", placeholder: t("Why it is interesting, what to check next..."),
      "aria-label": t("Note for {name}", { name: s.name }) });
    note.value = s.note;
    note.addEventListener("change", async () => {
      try {
        await shortlistCall(`/api/shortlist/${s.appid}`, { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: note.value }) });
        toast("success", t("Note saved"), s.name);
      } catch (err) { notifyError(err); }
    });
    const stat = (label, value) => el("div", { class: "stat" }, el("span", {}, label), el("b", { title: value }, value));
    return el("article", { class: "sl-card", "data-appid": s.appid },
      el("div", { class: "sl-head" },
        pill(s.score, "big"),
        el("div", { class: "who" },
          el("button", { type: "button", class: "name", onclick: () => openGame(s.appid) }, s.name),
          el("span", { class: "from" }, t("From"), " ", el("b", {}, s.source), s.added ? ` · ${t("starred {when}", { when: ago(s.added) })}` : "")),
        el("button", { type: "button", class: "remove", title: t("Remove from shortlist"),
          "aria-label": t("Remove {name} from the shortlist", { name: s.name }), onclick: () => toggleStar(s.appid) }, "★")),
      el("div", { class: "stats3" },
        stat(t("Rating"), percent(s.rating)),
        stat(t("Reviews"), fmt(s.reviews)),
        stat(t("Top complaint"), s.complaint ? `${s.complaint} ${pct(s.complaint_share)}` : "-")),
      el("label", {}, t("Note"), note));
  }));
}

// A shortlisted game: selected if it is in the current ranking, else analyzed into the panel.
function openGame(appid) {
  if (state.games.some((g) => g.game.appid === appid)) {
    setTableView("games");
    return selectGame(appid);
  }
  analyzeGame(String(appid));
}

function highlightRow() {
  for (const tr of document.querySelectorAll("#ranking tbody tr")) {
    tr.classList.toggle("selected", +tr.dataset.appid === state.selected);
  }
}

function selectGame(appid, focus = true) {
  const g = state.games.find((x) => x.game.appid === appid);
  if (!g) return;
  state.selected = appid;
  if (!state.showAll && g.rank > SHOWN) { state.showAll = true; renderTable(); }
  map.select(appid); // both views, so the hidden one is in sync when you switch
  highlightRow();
  renderPanel(g, 0, focus);
  document.querySelector(`#ranking tr[data-appid="${appid}"]`)?.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
}

// ---------- score card: how a score was reached (hover or focus any score) ----------
// All numbers and wording come from the server (scoring.explain); this only lays them out.
const scoreTip = el("div", { id: "score-tip", class: "score-tip", role: "tooltip", hidden: true });
document.body.append(scoreTip);

function fillScoreTip(g) {
  const e = g.score_explained;
  const row = (cls, label, value, note) => el("div", { class: `tip-row ${cls}` },
    el("span", {}, label), el("b", {}, value), note ? el("p", {}, note) : null);
  scoreTip.replaceChildren(
    el("div", { class: "tip-head" }, el("b", {}, t("Opportunity score {score}", { score: Math.round(e.score) })), el("span", {}, "/ 100")),
    el("p", { class: "tip-lead" }, t("Proven demand + poor execution = high opportunity. Three parts, each 0-100%:")),
    ...e.parts.map((p) => el("div", { class: "tip-part" },
      el("div", { class: "tip-part-head" },
        el("span", {}, p.label),
        el("i", {}, t("weight {pct}", { pct: pct(p.weight) })),
        el("b", {}, pct(p.value))),
      el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round(p.value * 100)}%` })),
      el("p", {}, p.basis))),
    el("div", { class: "tip-sum" },
      row("", t("Combined"), Math.round(e.combined)),
      ...e.penalties.map((p) => row("minus", t("{label} (risk)", { label: p.label }), `-${p.points}`, p.reason)),
      row("total", t("Score"), Math.round(e.score))),
    el("p", { class: `tip-note${e.zero_part ? " warn" : ""}` }, e.zero_part
      ? t("{part} is 0%, so the score is 0: a good opportunity needs all three parts.", { part: e.zero_part })
      : t("If any part is 0%, the score is 0: a good opportunity needs all three parts.")),
  );
}

function showScoreTip(anchor, g) {
  if (!g.score_explained) return;
  fillScoreTip(g);
  scoreTip.hidden = false;
  placeTip(scoreTip, anchor);
}
// Beside the anchor, flipped to its left when there's no room, and kept inside the window.
function placeTip(tip, anchor) {
  const a = anchor.getBoundingClientRect(), t = tip.getBoundingClientRect(), gap = 10;
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  let left = a.right + gap; // beside the score; flip to the left side when there's no room
  if (left + t.width > vw - 8) left = Math.max(8, a.left - gap - t.width);
  let top = a.top + a.height / 2 - t.height / 2;
  top = Math.max(8, Math.min(top, vh - t.height - 8));
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

const hideScoreTip = () => (scoreTip.hidden = true);
document.addEventListener("keydown", (e) => e.key === "Escape" && hideScoreTip());
document.addEventListener("scroll", hideScoreTip, true);

// Makes `node` open the score card on hover and keyboard focus.
function scoreAnchor(node, g) {
  node.tabIndex = 0;
  node.setAttribute("aria-describedby", "score-tip");
  node.classList.add("score-anchor");
  node.addEventListener("mouseenter", () => showScoreTip(node, g));
  node.addEventListener("focus", () => showScoreTip(node, g));
  node.addEventListener("mouseleave", hideScoreTip);
  node.addEventListener("blur", hideScoreTip);
  return node;
}

// ---------- terms: what this project's words mean, shown by an ⓘ and listed in How it works ----------
// Change the wording here; every ⓘ and the glossary read it.
function terms() {
  return {
    demand: [t("Demand"), t("How many people bought games like this, judged by the number of reviews. Each extra review counts a little less (log scale), so one hit doesn't drown out the rest.")],
    dissatisfaction: [t("Dissatisfaction"), t("How unhappy the players are: how far the game's % positive is below 70%. A 40% game scores higher than a 65% one.")],
    fixability: [t("Fixability"), t("How many of the complaints a new game could avoid: bugs, controls, missing content, performance and the like. Complaints about price or the genre itself don't count.")],
    risk_penalty: [t("Risk penalty"), t("Points taken off the score for something that makes a game a weaker opportunity than it looks, e.g. online multiplayer, fading interest, or recent reviews showing it's already fixed. The ⚠ badge in the list shows them; a game's History tab lists every check.")],
    revenue: [t("Estimated revenue"), t("Box Method: each review stands for about 30 to 100 copies sold (45 in the middle), times the full price. A rough figure before Steam's cut, discounts, refunds and taxes. Checked against games that published their sales, x45 was right on average, but for a single game it was off by up to about 3 times either way. What the developer keeps is often half of this or less.")],
    price_range: [t("Price range"), t("The undiscounted prices of the paid games with demand in this market: the median, and the range the middle half sits in. Well-served games are the ones at 85%+ positive. Worked out from the data, not by the model. These are today's list prices: older games are often cheaper now than at launch, so a new game can usually ask a little more.")],
    recent: [t("Last 12 months"), t("Reviews written in the last 12 months, their share of all reviews, and how positive they are. Few recent reviews mean fading interest; much better recent reviews mean the problems may already be fixed.")],
    loved: [t("What players love"), t("Phrases that come up most often in the positive reviews: what people enjoy, and what a new game should keep.")],
    idea_praise: [t("Great idea, bad execution?"), t("Negative reviews that still praise the idea or its potential. A high share means players want this game, just made better.")],
    with_demand: [t("With demand"), t("Games with at least the minimum number of reviews set in the Filters.")],
    underserved: [t("Underserved"), t("Games with demand whose % positive is inside the range set in the Filters: many players, let down.")],
    well_served: [t("Well served"), t("Games with demand that players rate {pct} positive or more: these players already have a good game.", { pct: percent(state.result?.well_served ?? 85) })],
    unmet_share: [t("Unmet share"), t("Of the games with demand that are clearly rated, the share that are underserved: underserved / (underserved + well served). Higher means players have fewer good games to choose from. A filter for exploring, not a forecast: in a backtest, new games in high-share tags sold more often, but were not rated well more often.")],
    min_reviews: [t("Minimum reviews"), t("How proven the demand must be: a game needs at least this many reviews to be considered.")],
    pct_range: [t("% positive range"), t("Which games count as letting players down. 5-70% leaves out games that are simply broken (under 5%) and games players already like (over 70%).")],
    reviews_read: [t("Reviews read per game"), t("How many reviews are read to find the complaints, half the most helpful and half the newest. More is slower but more reliable.")],
  };
}

// Every risk, with what it means (the glossary lists them; a game's History tab says how it came out).
function riskTerms() {
  return [
    [t("Review bomb"), t("A burst of negative reviews about something other than the game itself. The rating is shown without it; no points are taken off.")],
    [t("Review spike"), t("A burst of reviews in one month after launch that isn't mostly negative (that would be a review bomb): a sale, a big update, a streamer or a viral moment. Interest like that often doesn't last.")],
    [t("Deep discount"), t("On a big sale right now, so the review count may be inflated by cheap copies.")],
    [t("Very cheap"), t("A very low price inflates the number of buyers and reviews.")],
    [t("Online multiplayer"), t("Needs netcode and servers: hard for a small team to do well.")],
    [t("Niche audience"), t("A small audience that's harder to reach and to market to.")],
    [t("AAA expectations"), t("Players compare it to big-budget games, which a small team can hardly match.")],
    [t("Hard tech"), t("A kind of game that is technically demanding to do well.")],
    [t("Fading demand"), t("Few reviews in the last 12 months: the audience may have moved on.")],
    [t("Already improved"), t("Recent reviews are much better than older ones: the problems may already be fixed.")],
    [t("No store page"), t("Delisted or region-locked: check it by hand.")],
    [t("Not a game"), t("A soundtrack, tool or similar: left out of the ranking.")],
  ];
}

// An ⓘ button; hover, focus or a tap shows the term's meaning. Static ones are in index.html (data-term).
const infoLabel = (key) => t("What does \"{term}\" mean?", { term: terms()[key][0] });
function info(key) {
  return el("button", { type: "button", class: "info", "data-term": key, "aria-label": infoLabel(key) }, "i");
}
function relabelInfo() {
  for (const b of document.querySelectorAll(".info[data-term]")) {
    b.textContent = "i";
    b.setAttribute("aria-label", infoLabel(b.dataset.term));
  }
}

const termTip = el("div", { id: "term-tip", class: "score-tip term-tip", role: "tooltip", hidden: true });
document.body.append(termTip);
let termAnchor = null;
function showTerm(button) {
  const [title, text] = terms()[button.dataset.term];
  termTip.replaceChildren(el("div", { class: "tip-head" }, el("b", {}, title)), el("p", {}, text));
  termTip.hidden = false;
  termAnchor = button;
  placeTip(termTip, button);
}
function hideTerm() {
  termTip.hidden = true;
  termAnchor = null;
}
// Delegated, so ⓘ buttons made later (panel, market line) work too. A click or tap only toggles the
// explanation: caught here first, so it never sorts a column, selects a row or ticks a checkbox.
document.addEventListener("click", (e) => {
  const b = e.target.closest?.(".info[data-term]");
  if (!b) return;
  e.preventDefault();
  e.stopPropagation();
  if (termAnchor === b) hideTerm(); else showTerm(b);
}, true);
document.addEventListener("mouseover", (e) => {
  const b = e.target.closest?.(".info[data-term]");
  if (b && b !== termAnchor) showTerm(b);
});
document.addEventListener("mouseout", (e) => {
  const b = e.target.closest?.(".info[data-term]");
  if (b && !b.contains(e.relatedTarget)) hideTerm();
});
document.addEventListener("focusin", (e) => e.target.matches?.(".info[data-term]") && showTerm(e.target));
document.addEventListener("focusout", (e) => e.target.matches?.(".info[data-term]") && hideTerm());
document.addEventListener("keydown", (e) => e.key === "Escape" && hideTerm());
document.addEventListener("scroll", hideTerm, true);

// The glossary in How it works: the same texts as the ⓘ buttons, then every risk.
function renderGlossary() {
  const entry = ([title, text]) => [el("dt", {}, title), el("dd", {}, text)];
  $("#help-terms").replaceChildren(...Object.values(terms()).flatMap(entry));
  $("#help-risks").replaceChildren(...riskTerms().flatMap(entry));
}

// ---------- the game drawer: Overview | Complaints | Summary | History ----------
const TABS = { overview: 0, complaints: 1, summary: 2, history: 3 };
const panelTab = () => {
  const active = document.querySelector("#panel .tabs button.active");
  return active ? [...active.parentNode.children].indexOf(active) : 0;
};

// A complaint as a bar, scaled to the biggest one shown with it.
function cbar(label, share, max) {
  return el("div", { class: "cbar" },
    el("span", { title: label }, label),
    el("div", { class: "track thick" }, el("div", { class: "fill", style: `width:${Math.round((share / Math.max(share, max, 0.01)) * 100)}%` })),
    el("span", { class: "val" }, pct(share)));
}

const stat = (label, value, small = "") => el("div", { class: "stat" }, el("span", {}, label), el("b", {}, value), small ? el("small", {}, small) : null);

// The score as a ring, colored like the pills.
function ring(score, size = 84) {
  const NS = "http://www.w3.org/2000/svg", C = 2 * Math.PI * 40;
  const node = (tag, attrs, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    return n;
  };
  const svg = node("svg", { class: "score-ring", width: size, height: size, viewBox: "0 0 96 96", role: "img",
    "aria-label": t("Opportunity score {score}. How it is calculated", { score: Math.round(score) }) });
  svg.append(
    node("circle", { class: "bg", cx: 48, cy: 48, r: 40, fill: "none", "stroke-width": 8 }),
    node("circle", { cx: 48, cy: 48, r: 40, fill: "none", stroke: scoreColor(score), "stroke-width": 8, "stroke-linecap": "round",
      "stroke-dasharray": `${(Math.max(0, Math.min(100, score)) / 100) * C} ${C}`, transform: "rotate(-90 48 48)" }),
    node("text", { x: 48, y: 57, "text-anchor": "middle", "font-size": 27 }, Math.round(score)));
  return svg;
}

function renderPanel(g, tab = 0, focus = true) {
  state.panelGame = g;
  const game = g.game;
  const year = (g.details?.release_date || "").match(/\d{4}/)?.[0];
  const sub = [g.price ? `$${decimal(g.price, 2)}` : t("Free to play"), year, `AppID ${game.appid}`].filter(Boolean).join(" · ");
  const head = el("div", { class: "panel-head" },
    el("h3", { class: "game-title" }, game.name),
    el("span", { class: "sub" }, sub, " · ", el("a", { href: g.store_url, target: "_blank", rel: "noopener" }, "Steam ↗")));

  const tabs = [
    [t("Overview"), () => overviewTab(g)],
    [t("Complaints"), () => complaintsTab(g)],
    [t("Summary"), () => gameSummaryTab(g)],
    [t("History"), () => historyTab(g)],
  ];
  // ARIA tabs: one Tab stop (the active tab); arrow keys and Home/End move between them.
  const body = el("div", { class: "tab-body", role: "tabpanel", id: "panel-tabpanel", tabindex: "0" });
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  const buttons = tabs.map(([name, render]) => {
    const b = el("button", { type: "button", role: "tab", "aria-controls": "panel-tabpanel" }, name);
    b.addEventListener("click", () => {
      for (const x of buttons) {
        x.classList.toggle("active", x === b);
        x.setAttribute("aria-selected", String(x === b));
        x.tabIndex = x === b ? 0 : -1;
      }
      body.setAttribute("aria-labelledby", b.id);
      body.replaceChildren(...[render()].flat(2).filter(Boolean));
    });
    return b;
  });
  buttons.forEach((b, i) => (b.id = `panel-tab-${i}`));
  tabBar.append(...buttons);
  tabBar.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(e.target), n = buttons.length;
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1 + n, Home: 0, End: n - 1 }[e.key];
    if (i < 0 || to === undefined) return;
    e.preventDefault();
    buttons[to % n].focus();
    buttons[to % n].click();
  });
  buttons[Math.min(tab, buttons.length - 1)].click();

  const actions = el("div", { class: "actions" }, starButton(game.appid),
    el("a", { class: "steam", href: g.store_url, target: "_blank", rel: "noopener" }, t("Open on Steam")));
  $("#panel").replaceChildren(head, tabBar, body, actions);
  $("#panel").scrollTop = 0;
  const i = state.games.findIndex((x) => x.game.appid === game.appid);
  $("#sheet-pos").textContent = i >= 0 ? t("{i} of {n}", { i: i + 1, n: state.games.length }) : "";
  openDrawer(focus);
}

const goTab = (i) => document.querySelectorAll("#panel .tabs button")[i]?.click();

function overviewTab(g) {
  const o = g.opportunity, m = g.mining;
  const adjusted = Math.round(o.effective_rating) !== Math.round(g.rating);
  const cats = m?.categories || [];
  const top = cats.slice(0, 3);
  const quote = top.find((c) => c.quotes.length)?.quotes[0];
  const risks = penalties(g);
  const loved = (m?.core_phrases || []).slice(0, 5).map(([p]) => p);
  const tags = Object.keys(g.game.tags || {}).slice(0, 10);
  return [
    el("div", { class: "score-row" },
      scoreAnchor(ring(o.score), g),
      el("p", { class: "why" }, el("span", { class: "verdict", style: `--c:${scoreColor(o.score)}` }, g.verdict), g.why)),
    el("div", { class: "facts" },
      stat(t("Rating"), percent(adjusted ? o.effective_rating : g.rating),
        adjusted ? t("without review bombs ({pct} with)", { pct: percent(g.rating) }) : ""),
      stat(t("Reviews"), fmt(g.reviews)),
      stat([t("Last 12 mo"), info("recent")], g.recent_share == null ? "-" : fmt(g.recent_reviews),
        g.recent_rating == null ? "" : t("{pct} positive", { pct: percent(g.recent_rating) })),
      stat([t("Est. revenue"), info("revenue")], g.price ? money(g.box.gross_mid) : "F2P",
        g.price ? `${money(g.box.gross_low)} – ${money(g.box.gross_high)}` : "")),
    g.rating_source_text ? el("p", { class: "muted rating-src" }, t("Review numbers: {source}", { source: g.rating_source_text })) : null,
    top.length ? el("section", {},
      el("h4", {}, t("What players complain about")),
      top.map((c) => cbar(c.label, c.share, top[0].share)),
      quote ? el("blockquote", { class: "quote" }, `“${quote}”`) : null)
      : el("div", { class: "callout" }, g.review_error ? t("Review texts unavailable: {error}", { error: g.review_error }) : t("No English negative reviews to mine.")),
    risks.length ? el("div", { class: "risk-box" },
      el("span", { "aria-hidden": "true" }, "⚠"),
      el("div", {}, risks.map((p) => [el("b", {}, t("{label} · −{points} points", { label: p.label, points: p.points })), el("p", {}, p.reason)])))
      : null,
    loved.length ? el("section", {}, el("h4", {}, t("What players love"), info("loved")), el("p", { class: "loved" }, loved.join(", ") + ".")) : null,
    tags.length ? el("div", { class: "chips" }, tags.map((tag) => el("button", {
      type: "button", class: "chip", title: t("Search {tag}", { tag }), onclick: () => searchOneTag(tag) }, tag))) : null,
    el("div", { class: "links" },
      el("button", { type: "button", class: "link-btn go", onclick: () => goTab(TABS.complaints) }, t("All complaints and quotes →")),
      el("button", { type: "button", class: "link-btn go", onclick: () => goTab(TABS.history) }, t("Review history →")),
      g.score_explained ? scoreAnchor(el("button", { type: "button", class: "link-btn how-scored" }, t("How the score works")), g) : null),
  ];
}

function complaintsTab(g) {
  const m = g.mining;
  if (g.review_error) return el("div", { class: "callout" }, t("Review texts unavailable: {error}", { error: g.review_error }));
  if (!m || !m.n_negative) return el("div", { class: "callout" }, t("No English negative reviews to mine."));
  const big = m.categories.filter((c, i) => i < 3 || c.share >= 0.1);
  const small = m.categories.slice(big.length);
  const max = m.categories[0]?.share || 0;
  return [
    el("div", { class: "stats3" },
      stat(t("Reviews read"), fmt(m.n_negative + m.n_positive)),
      stat([t("Fixability"), info("fixability")], pct(m.fixability)),
      stat([t("Idea praised"), info("idea_praise")], pct(m.idea_praise_share))),
    el("p", { class: "muted" },
      t("{neg} negative, {pos} positive · half most helpful, half newest ({recent} negative from the last 12 months) · reviews written under 2 h of play count half",
        { neg: fmt(m.n_negative), pos: fmt(m.n_positive), recent: m.n_recent_negative ?? 0 })),
    big.map((c) => el("article", { class: "complaint" },
      el("div", { class: "c-head" }, el("b", {}, c.label),
        c.trend ? el("span", { class: `trend ${c.trend_kind || "fading"}` }, c.trend) : null,
        el("span", { class: "val" }, pct(c.share))),
      el("div", { class: "track thick" }, el("div", { class: "fill", style: `width:${Math.round((c.share / Math.max(max, 0.01)) * 100)}%` })),
      el("span", { class: c.fixable ? "pillar" : "pillar unfixable" }, c.fixable ? t("A new game should: ") : "", el("b", {}, c.pillar)),
      c.quotes[0] ? el("blockquote", {}, `“${c.quotes[0]}”`) : null,
      c.quotes.length > 1 ? el("details", {}, el("summary", {}, t("{n} more quotes", { n: c.quotes.length - 1 })),
        c.quotes.slice(1).map((q) => el("blockquote", {}, `“${q}”`))) : null)),
    small.length ? el("div", { class: "minor" }, small.map((c) => el("div", {}, el("span", {}, c.label), el("span", {}, pct(c.share))))) : null,
    el("div", { class: "idea-box" },
      el("b", {}, t("Great idea, bad execution?"), info("idea_praise")),
      el("span", {}, t("{pct} of {n} negative reviews still praise the idea or its potential.", { pct: pct(m.idea_praise_share), n: m.n_negative }))),
  ];
}

// ---------- one game read by the local LLM: written on request, saved with the run ----------
function gameSummaryTab(g) {
  const s = g.summary;
  const inRun = state.games.some((x) => x.game.appid === g.game.appid);
  const busy = state.gameSummarizing === g.game.appid;
  const writeButton = (label) => {
    const b = el("button", { type: "button", class: "ghost", onclick: () => writeGameSummary(g) });
    setButtonBusy(b, busy, busy ? t("Writing...") : label);
    return b;
  };
  if (!s) {
    if (!inRun) return el("div", { class: "callout" }, t("A summary can be written for the games in the current ranking."));
    return el("div", { class: "opp-empty" },
      el("p", {}, t("Why players are unhappy, what a better game would do, and complaints no category covers. Written by the local model {model} (Ollama) in under a minute.",
        { model: state.result?.llm_model || "" })),
      writeButton(t("Write summary")));
  }
  return el("div", { class: "tab-body game-summary" },
    el("div", { class: "ai-bar" },
      el("span", {}, t("{model} on your computer · saved with the run", { model: s.model })),
      inRun ? writeButton(t("Rewrite")) : null),
    s.why ? el("section", {}, el("h5", {}, t("Why players are unhappy")), el("p", { class: "why-text" }, s.why)) : null,
    s.fix.length ? el("section", {}, el("h5", {}, t("What a better game would do")), el("ol", { class: "numbered" }, s.fix.map((f) => el("li", {}, f)))) : null,
    el("section", {}, el("h5", {}, t("Other complaints · outside the categories")),
      s.other.length
        ? s.other.map((o) => el("div", { class: "other-card" }, el("b", {}, o.text), el("span", {}, `“${o.quote}”`)))
        : el("p", { class: "muted" }, t("None found in the {n} negative reviews no category matched.", { n: s.n_uncovered }))),
    el("p", { class: "muted" }, t("Written by the local model {model}. It can be wrong: check it against the reviews.", { model: s.model })),
  );
}

async function writeGameSummary(g) {
  if (state.gameSummarizing || state.summarizing) return stillRunning(t("A summary is being written."));
  const id = state.runId, appid = g.game.appid;
  state.gameSummarizing = appid;
  if (state.panelGame?.game.appid === appid) renderPanel(state.panelGame, TABS.summary, false);
  try {
    const res = await api(`/api/tag-runs/${id}/games/${appid}/summary`, { method: "POST" });
    if (!res.ok) throw await apiError(res);
    const data = await res.json();
    const target = state.runId === id && state.games.find((x) => x.game.appid === appid);
    if (target) target.summary = data.summary;
  } catch (err) {
    notifyError(err);
  } finally {
    state.gameSummarizing = null;
    if (state.panelGame?.game.appid === appid) renderPanel(state.panelGame, TABS.summary, false);
  }
}

const severity = (s) => ({ high: t("Serious"), warn: t("Caution"), info: t("Note") })[s] || s;

function historyTab(g) {
  const POSITIVE = cssVar("--good"), NEGATIVE = cssVar("--bad-soft"); // read now: the theme may have changed
  const h = g.histogram || [];
  const o = g.opportunity;
  const out = [];
  if (h.length) {
    // positive reviews up from the middle line, negative ones down
    const W = 400, H = 190, mid = 92, room = 84;
    const max = Math.max(1, ...h.map((p) => Math.max(p.up, p.down)));
    const bw = W / h.length;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t("Monthly positive and negative reviews"));
    const add = (tag, attrs, text) => {
      const n = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      if (text != null) n.textContent = text;
      svg.append(n);
      return n;
    };
    h.forEach((p, i) => {
      const month = new Date(p.date * 1000).toISOString().slice(0, 7);
      const tip = t("{month}: {up} positive, {down} negative", { month, up: p.up, down: p.down });
      const x = i * bw + bw * 0.12, w = Math.max(0.5, bw * 0.76);
      const up = (room * p.up) / max, down = (room * p.down) / max;
      add("rect", { x, y: mid - up, width: w, height: up, fill: POSITIVE, rx: 1 }).append(Object.assign(document.createElementNS(NS, "title"), { textContent: tip }));
      add("rect", { x, y: mid + 1, width: w, height: down, fill: NEGATIVE, rx: 1 }).append(Object.assign(document.createElementNS(NS, "title"), { textContent: tip }));
    });
    add("line", { class: "axis", x1: 0, x2: W, y1: mid + 0.5, y2: mid + 0.5, "stroke-width": 1 });
    const first = new Date(h[0].date * 1000).toISOString().slice(0, 7);
    const last = new Date(h[h.length - 1].date * 1000).toISOString().slice(0, 7);
    out.push(el("section", { class: "hist" },
      el("div", { class: "hist-head" }, el("h5", {}, t("Reviews per month")), el("span", {}, `${first} → ${last}`)),
      svg,
      el("div", { class: "legend" },
        el("span", {}, el("i", { style: `background:${POSITIVE}` }), t("Positive")),
        el("span", {}, el("i", { style: `background:${NEGATIVE}` }), t("Negative"))),
      el("p", { class: "muted" }, t("A tall spike after launch can be a sale, an update or a streamer (mostly positive) or a review bomb (mostly negative)."))));
  } else {
    out.push(el("div", { class: "callout" }, t("No review histogram available.")));
  }
  if (g.recent_share != null) {
    const diff = g.recent_rating == null ? null : Math.round(g.recent_rating - o.effective_rating);
    out.push(el("div", { class: "facts" },
      stat([t("Last 12 months"), info("recent")], t("{n} reviews", { n: fmt(g.recent_reviews) }), t("{pct} of all time", { pct: pct(g.recent_share) })),
      stat(t("Recent rating"), g.recent_rating == null ? "-" : [percent(g.recent_rating), diff ? el("span", { class: `delta ${diff > 0 ? "up" : "down"}` },
        diff > 0 ? t("▲ {n} pts", { n: diff }) : t("▼ {n} pts", { n: -diff })) : null],
      t("vs {pct} all time", { pct: percent(o.effective_rating) }))));
  }
  // Every check, passed or not; flags that aren't checks (e.g. the rating without spikes) come first.
  const codes = new Set((g.checks || []).map((c) => c.code));
  const notes = g.flags.filter((f) => !codes.has(f.code));
  out.push(el("section", {},
    el("h5", {}, t("All risk checks"), info("risk_penalty")),
    el("div", { class: "checks" },
      notes.map((f) => el("div", { class: `check-row flagged ${f.severity}` },
        el("span", { class: "mark", "aria-hidden": "true" }), el("span", { class: "name" }, f.label || f.code),
        el("span", { class: "sev" }, severity(f.severity)), el("span", { class: "detail" }, f.message))),
      (g.checks || []).map((c) => c.flagged
        ? el("div", { class: `check-row flagged ${c.severity}` },
          el("span", { class: "mark", "aria-hidden": "true" }), el("span", { class: "name" }, c.label),
          el("span", { class: "sev" }, severity(c.severity) + (c.points ? ` · −${c.points}` : "")), el("span", { class: "detail" }, c.detail))
        : el("div", { class: "check-row" },
          el("span", { class: "mark", "aria-label": t("passed") }, "✓"), el("span", { class: "name" }, c.label),
          el("span", { class: "detail" }, c.detail))))));
  return out;
}

// ---------- language and theme (two switches in the top bar) ----------
// Switching the language redraws everything in place: static text, labels made in JS, and the current
// result and game fetched again, so the server's text (notices are not re-shown) comes in the new language too.
async function setLanguage(value) {
  setLang(value);
  for (const b of document.querySelectorAll("#lang button")) b.setAttribute("aria-pressed", String(b.dataset.lang === getLang()));
  applyStatic();
  relabelInfo();
  renderGlossary();
  setMapView(mapView);
  map.relabel();
  renderChips();
  if (!tagPop.hidden) openTagList();
  refreshList();
  filtersSummary();
  setSearching(state.searching);
  marketsText();
  marketsButton();
  if (markets.result) renderMarkets();
  loadShortlist(); // complaint names come in the new language
  renderTitle();
  if (state.games.length) renderTable();
  try {
    if (state.runId && state.result) {
      const res = await api(`/api/tag-runs/${state.runId}`);
      if (res.ok) {
        const job = await res.json();
        if (job.status === "done") showResult(job.result, state.runId, true);
      }
    }
    const shown = state.panelGame;
    if (shown && !state.games.some((x) => x.game.appid === shown.game.appid)) renderPanel(await fetchGame(shown.game.appid), panelTab(), false);
  } catch { /* the old language stays until the next search */ }
}
document.querySelectorAll("#lang button").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));

// The theme is set before the first paint by the script in index.html; this keeps the switch in sync,
// remembers the choice and redraws what holds colors outside CSS (the 3D scene, the ring, the History chart).
function setTheme(theme) {
  theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  for (const b of document.querySelectorAll("#theme button")) b.setAttribute("aria-pressed", String(b.dataset.theme === theme));
  try { localStorage.setItem("theme", theme); } catch { /* storage blocked: not remembered */ }
  map3d?.recolor();
  map2d.relabel(); // redraws
  if (state.panelGame) renderPanel(state.panelGame, panelTab(), false);
}
document.querySelectorAll("#theme button").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.theme)));
for (const b of document.querySelectorAll("#theme button")) {
  b.setAttribute("aria-pressed", String(b.dataset.theme === document.documentElement.dataset.theme));
}
let savedMode = "table";
try { savedMode = localStorage.getItem("gamesMode") || "table"; } catch { /* storage blocked */ }
setGamesMode(savedMode);
setLanguage(getLang());
