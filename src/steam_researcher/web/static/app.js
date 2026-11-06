import { cssVar, scoreColor, scoreInk } from "/static/palette.js";
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
  for (const c of children.flat()) {
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

// Every request says which language the server's text (notices, score card, risks) should be in.
const api = (url, opts = {}) => fetch(url, { ...opts, headers: { ...opts.headers, "X-Lang": getLang() } });

// ---------- toasts: every message the user should see goes through here ----------
const ICONS = { success: "✓", info: "i", warning: "!", error: "×" };
const LIFETIME = { success: 6000, info: 7000, warning: 12000, error: 0 }; // 0 = stays until closed

function toast(level, title, message = "", hint = "") {
  const close = el("button", { class: "close", type: "button", "aria-label": t("Dismiss") }, "×");
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

// Thrown when the user presses Cancel on a running search or market ranking.
class CancelledRun extends Error {}

// The run each banner's Cancel button stops: id once the server has started it.
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
const map2d = createMap2d($("#map"), { onSelect: onMapSelect, describe: mapLine });
let map3d = null;
try {
  const { createMap } = await import("/static/map3d.js");
  const m = createMap($("#map"), { onSelect: onMapSelect, describe: mapLine });
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
  "2d": () => t("x: demand · y: dissatisfaction · size: revenue · color: score · hover for fixability"),
  "3d": () => t("x: demand · y: dissatisfaction · z: fixability · size: revenue · color: score"),
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
let savedView = "3d";
try { savedView = localStorage.getItem("mapView") || "3d"; } catch { /* storage blocked */ }
setMapView(savedView);

// The Games view shows the ranking as a table or as the map, never both: each gets the whole card.
let gamesMode = "table";
function setGamesMode(mode) {
  gamesMode = mode === "map" ? "map" : "table";
  $("#games-view .table-wrap").hidden = gamesMode !== "table";
  $("#map").hidden = gamesMode !== "map";
  $("#map-tools").hidden = gamesMode !== "map" || tableView !== "games";
  for (const b of document.querySelectorAll("#games-mode button")) b.setAttribute("aria-pressed", String(b.dataset.mode === gamesMode));
  if (gamesMode === "map") setMapView(mapView); // resizes the shown map to its new box
  try { localStorage.setItem("gamesMode", gamesMode); } catch { /* storage blocked */ }
}
$("#games-mode").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (b) setGamesMode(b.dataset.mode);
});

// ---------- details drawer: opens with a game, closes with × or Esc ----------
// Opening moves the focus into the drawer (unless the page opened it by itself, after a search);
// closing gives it back to what opened it, or to the game's row.
let drawerReturn = null;
function openDrawer(focus = true) {
  if (!$("#drawer").hidden) return;
  drawerReturn = document.activeElement;
  $("#drawer").hidden = false;
  document.body.classList.add("drawer-open");
  if (focus) $("#drawer-close").focus({ preventScroll: true });
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
document.addEventListener("keydown", (e) => {
  // Esc first closes whatever is open on top (tag list, past runs, score card, help)
  if (e.key !== "Escape" || $("#drawer").hidden || e.defaultPrevented) return;
  if (e.target.closest?.("#tag-combo") || !tagPop.hidden || !runsPop.hidden || document.querySelector("dialog[open]") || !scoreTip.hidden) return;
  closeDrawer();
});

// ---------- state ----------
// A search and a single-game analysis can run at the same time. keepPanel: the user analyzed a game
// during the current search, so its results must not replace that game in the panel.
const state = { games: [], selected: null, sort: { key: "rank", asc: true }, runId: null, shortlist: [],
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
  setButtonBusy($("#run"), on, on ? t("Searching...") : t("Find opportunities"));
}

function setAnalyzing(on) {
  state.analyzing = on;
  setButtonBusy($("#game-form button"), on, on ? t("Analyzing...") : t("Analyze"));
}

function stillRunning(what) {
  toast("info", t("Please wait"), what, t("Wait for it to finish, then try again."));
}

// ---------- sidebar ----------
function openFilters(open = true) {
  $("#filters").hidden = !open;
  $("#filters-toggle").setAttribute("aria-expanded", String(open));
}
$("#filters-toggle").addEventListener("click", () => {
  openFilters($("#filters").hidden);
  try { localStorage.setItem("filtersOpen", String(!$("#filters").hidden)); } catch { /* storage blocked */ }
});
try {
  const open = localStorage.getItem("filtersOpen");
  openFilters(open ? open === "true" : !matchMedia("(max-width: 1000px)").matches);
} catch { /* storage blocked: stays open */ }
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

// ---------- tag picker: tick any number of Steam tags (games must have all of them) ----------
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
}

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
  saveFilters();
  $("#tag-chips").replaceChildren(...tagPicker.picked.map((tag) =>
    el("span", { class: "tag-chip" }, tag,
      el("button", { type: "button", "aria-label": t("Remove {tag}", { tag }),
        onmousedown: (e) => e.preventDefault(), // don't steal focus from the filter box
        onclick: (e) => { e.stopPropagation(); togglePick(tag); } }, "×"))));
  if (tagPicker.freeText) return;
  const open = !tagPop.hidden;
  tagInput.placeholder = open ? t("Filter tags...") : tagPicker.picked.length ? "" : t("Pick Steam tags...");
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

// Ticked tags first (as of opening), then the rest. Typing in the box only narrows the list.
function openTagList(query = tagInput.value) {
  if (!tagPicker.tags.length) return;
  const matches = matchTags(query);
  const picked = matches.filter(isPicked), rest = matches.filter((tag) => !isPicked(tag));
  tagPicker.shown = picked.concat(rest);
  tagPicker.active = -1;
  let i = 0;
  const option = (tag) => el("li", { role: "option", id: `tag-opt-${i++}`, "data-tag": tag, onclick: () => togglePick(tag) },
    el("span", { class: "check", "aria-hidden": "true" }, "✓"), tag);
  const group = (title) => el("li", { class: "group", role: "presentation" }, title);
  const rows = [];
  if (picked.length) rows.push(group(t("Selected")), ...picked.map(option));
  if (rest.length) rows.push(...(picked.length ? [group(t("All tags"))] : []), ...rest.map(option));
  if (!matches.length) rows.push(el("li", { class: "none" }, t("No Steam tag contains \"{query}\"", { query: query.trim() })));
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
    const res = await api("/api/tags");
    if (!res.ok) throw await apiError(res);
    tagPicker.tags = (await res.json()).tags || [];
    const known = tagPicker.picked.filter((tag) => tagPicker.tags.includes(tag)); // e.g. a tag Steam renamed
    if (known.length !== tagPicker.picked.length) { tagPicker.picked = known; renderChips(); }
    if (document.activeElement === tagInput) openTagList();
  } catch (err) {
    // Fallback: type tags by hand, comma-separated.
    $("#tag-toggle").hidden = true;
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
    return fieldError(tagInput, t("Pick at least one tag."),
      !tagPicker.freeText ? t("Tick one or more tags in the list.") : t("Type tags separated by commas, e.g. Crafting, Survival."));
  }
  if (body.tags.length > MAX_TAGS) {
    return fieldError(tagInput, t("Use at most {n} tags.", { n: MAX_TAGS }), t("Games must have every tag, so a few tags is usually enough."));
  }
  const label = tagsLabel(body.tags);
  if (body.lo > body.hi) return rangeError(body);
  state.keepPanel = false;
  setSearching(true);
  startRun("games");
  try {
    // Inside the try: if anything here fails, the button and banner reset and the error is shown,
    // instead of a "Searching..." that never ends.
    searchStatus(label, 0, "", t("Fetching games tagged {tag}...", { tag: label }));
    const res = await api("/api/tag-runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw await apiError(res);
    const { id, notices } = await res.json();
    runStarted("games", id);
    notifyAll(notices);
    await poll(id, label);
  } catch (err) {
    if (err instanceof CancelledRun) {
      toast("info", t("Search cancelled"), state.games.length ? t("The previous results are still shown.") : "", "");
    } else {
      notifyError(err, t("Search failed"));
    }
  } finally {
    setSearching(false);
    searchStatus(null);
  }
});

function rangeError(body) {
  $("#lo").classList.add("invalid");
  return fieldError($("#hi"), t("'% positive from' ({lo}) is higher than '% positive to' ({hi}).", body),
    t("Swap the two values, e.g. 5 to 70."));
}

// A progress banner (over the faded previous results while a search runs); title null hides it.
function statusBox(box, title, frac, count, message) {
  box.hidden = title == null;
  if (title == null) return;
  box.querySelector(".search-status-title").textContent = title;
  box.querySelector(".search-status-count").textContent = count;
  box.querySelector(".search-status-fill").style.width = `${Math.round(frac * 100)}%`;
  box.querySelector(".search-status-text").textContent = message || "";
}

// "12 / 15 · ~3 min left": the server estimates the time left from the pace so far (null: no estimate yet).
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

function progressCount(count, eta) {
  if (eta == null || !count) return count;
  const left = eta < 60 ? t("under a minute left") : t("~{n} min left", { n: Math.round(eta / 60) });
  return `${count} · ${left}`;
}

function searchStatus(tag, frac, count, message) {
  statusBox($("#search-status"), tag == null ? null : t("Searching \"{tag}\"...", { tag }), frac, count, message);
}

async function poll(id, tag) {
  for (;;) {
    const res = await api(`/api/tag-runs/${id}`);
    if (res.status === 404) {
      throw new ApiError({ level: "error", title: t("The search was interrupted"),
        message: t("The server was restarted, so this run was lost."), hint: t("Press Find opportunities again.") });
    }
    if (!res.ok) throw await apiError(res);
    const job = await res.json();
    if (job.status === "cancelled" || runCtl.games.cancelled) throw new CancelledRun();
    if (job.status === "error") throw new ApiError(job.error);
    if (job.status === "done") return showResult(job.result, id);
    const count = job.total ? `${job.done} / ${job.total}` : "";
    searchStatus(tag, job.total ? job.done / job.total : 0,
      progressCount(count && job.step ? t("Step {n} · {count}", { n: job.step, count }) : count, job.eta), job.message);
    await new Promise((r) => setTimeout(r, 1000));
    if (runCtl.games.cancelled) throw new CancelledRun();
  }
}

$("#search-status .cancel-run").addEventListener("click", () => cancelRun("games"));
$("#markets-status .cancel-run").addEventListener("click", () => cancelRun("markets"));

$("#game-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.analyzing) return stillRunning(t("The analysis of the previous game is still running."));
  const input = $("#appid");
  input.classList.remove("invalid");
  const raw = input.value.trim();
  if (!raw) {
    return fieldError(input, t("Enter a Steam AppID or store link."),
      t("For example 1330660 or https://store.steampowered.com/app/1330660/"));
  }
  const appid = (raw.match(/\/app\/(\d+)/) || raw.match(/^(\d+)$/) || [])[1];
  if (!appid || +appid <= 0) {
    return fieldError(input, t("\"{text}\" isn't an AppID or a Steam store link.", { text: raw.slice(0, 60) }),
      t("Use the number from the store URL, e.g. 1330660 from store.steampowered.com/app/1330660/"));
  }
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
});

async function fetchGame(appid) {
  const res = await api(`/api/games/${appid}?reviews=${+$("#reviews").value || 300}`);
  if (!res.ok) throw await apiError(res);
  return res.json();
}

// ---------- results ----------
// quiet: the same result again in another language, so no toasts and the sort and selection stay.
function showResult(result, id, quiet = false) {
  state.games = result.games.map((g, i) => ({ ...g, rank: i + 1 }));
  if (!quiet) state.sort = { key: "rank", asc: true };
  state.result = result;
  const notes = [
    t("{candidates} of {total} games have ≥ {min} reviews and {range} positive; analyzed the {n} with most reviews.", {
      candidates: fmt(result.n_candidates), total: fmt(result.n_tag_games), min: fmt(result.min_reviews),
      range: getLang() === "tr" ? `%${result.lo}-${result.hi}` : `${result.lo}-${result.hi}%`, n: state.games.length }),
  ];
  if (result.not_games.length) notes.push(t("Excluded non-games: {names}.", { names: result.not_games.join(", ") }));
  if (result.compared) notes.push(t("▲/▼ = score change since your previous run with these tags and filters."));
  $("#table-note").textContent = notes.join(" ");
  renderResultNotices(result.notices);
  renderMarketStrip(result.market, result.well_served);
  state.runId = id;
  renderSummary();
  $("#download").href = `/api/tag-runs/${id}/report.md?lang=${getLang()}`;
  $("#download-csv").href = `/api/tag-runs/${id}/ranking.csv?lang=${getLang()}`;
  if (!quiet) setTableView("games");
  else $("#table-title").textContent = tableTitles[tableView]();

  $("#quick-filter").hidden = !state.games.length;
  $("#table-empty").hidden = state.games.length > 0;
  map.setGames(visibleGames());
  renderTable();
  if (quiet) {
    const g = state.games.find((x) => x.game.appid === state.selected);
    if (g) renderPanel(g);
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

// The whole tag, not just the analyzed games: is this audience underserved or already well served?
function renderMarketStrip(m, wellServed) {
  const strip = $("#market-strip");
  strip.hidden = !m;
  if (!m) return;
  const stat = (value, label, cls = "", term = null) => el("div", { class: cls }, el("b", {}, value), el("span", {}, label, term ? info(term) : null));
  const rated = m.n_underserved + m.n_well_served;
  const verdict = rated < 5 ? t("Too few games with demand to judge this market.")
    : m.gap >= 0.5 ? t("Many disappointed players and few good games: an underserved audience.")
    : m.gap >= 0.3 ? t("A mixed market: some good games already serve these players.")
    : t("Mostly well served: players here already have good games.");
  strip.replaceChildren(
    stat(fmt(m.n_games), t("Games in tag")),
    stat(fmt(m.n_demand), t("With demand"), "", "with_demand"),
    stat(fmt(m.n_underserved), t("Underserved"), "good", "underserved"),
    stat(fmt(m.n_well_served), t("Well served ({pct}+)", { pct: percent(wellServed) }), "", "well_served"),
    stat(pct(m.gap), t("Unmet share"), m.gap >= 0.5 ? "good" : "", "unmet_share"),
    stat(money(m.underserved_gross), t("Underserved revenue"), "", "revenue"),
    el("div", { class: "verdict" }, verdict),
  );
}

// ---------- opportunity summary: written on request by a local LLM (Ollama), saved with the run ----------
function renderSummary() {
  const box = $("#opp-summary");
  const r = state.result;
  box.hidden = !r || !state.games.length;
  if (box.hidden) return;
  const s = r.summary;
  box.querySelector(".opp-state").textContent = s ? "" : state.summarizing ? t("Writing... (about a minute)") : t("not written yet");
  const body = box.querySelector(".opp-body");
  if (!s) {
    const button = el("button", { type: "button", class: "ghost", onclick: writeSummary });
    setButtonBusy(button, !!state.summarizing, state.summarizing ? t("Writing...") : t("Write summary"));
    body.replaceChildren(el("div", { class: "opp-empty" },
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
    el("p", { class: "opp-note muted" }, t("Written by the local model {model}. It can be wrong: check each point against the games it names.", { model: s.model })),
    el("div", { class: "opp-sections" },
      section(t("What players love"), s.loved),
      section(t("Shared complaints"), s.complaints),
      section(t("A better game would"), s.build),
      section(t("Caveats"), s.caveats)),
  );
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
      $("#opp-summary").open = true;
    }
  } catch (err) {
    notifyError(err);
  } finally {
    state.summarizing = false;
    renderSummary();
  }
}

// ---------- Games | Markets ----------
const tableTitles = {
  games: () => (state.result ? t("{tag}: opportunity ranking", { tag: state.result.tag }) : t("Ranking")),
  markets: () => t("Markets: which audiences are underserved?"),
  shortlist: () => t("Shortlist"),
};
let tableView = "games";

function setTableView(view) {
  tableView = view;
  for (const b of document.querySelectorAll("#table-view button")) b.setAttribute("aria-pressed", String(b.dataset.view === view));
  $("#games-view").hidden = view !== "games";
  $("#markets-view").hidden = view !== "markets";
  $("#shortlist-view").hidden = view !== "shortlist";
  if (view === "shortlist") renderShortlist();
  $("#table-title").textContent = tableTitles[view]();
  for (const a of [$("#download"), $("#download-csv")]) a.hidden = view !== "games" || !state.games.length;
  $("#games-mode").hidden = view !== "games";
  $("#map-tools").hidden = view !== "games" || gamesMode !== "map";
}
$("#table-view").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b) setTableView(b.dataset.view);
});

const markets = { rows: [], sort: { key: "rank", asc: true }, running: false, result: null };

function marketsButton() {
  setButtonBusy($("#markets-run"), markets.running,
    markets.running ? t("Building...") : markets.result ? t("Rebuild market ranking") : t("Build market ranking"));
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
    statusBox(box, t("Building the market ranking..."), 0, "", t("Reading the Steam tag list"));
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
      statusBox(box, t("Building the market ranking..."), job.total ? job.done / job.total : 0,
        progressCount(job.total ? t("{done} / {total} tags", { done: job.done, total: job.total }) : "", job.eta), job.message);
      await new Promise((r2) => setTimeout(r2, 1000));
      if (runCtl.markets.cancelled) throw new CancelledRun();
    }
  } catch (err) {
    if (err instanceof CancelledRun) toast("info", t("Market ranking cancelled"), t("Tags read so far stay cached, so the next build is faster."));
    else notifyError(err, t("Market ranking failed"));
  } finally {
    markets.running = false;
    marketsButton();
    statusBox(box, null);
  }
});

// The intro until a ranking is built; then what the ranking holds.
function marketsText() {
  const result = markets.result;
  $("#markets-well-head").textContent = t("Well served ({pct}+)", { pct: percent(result?.well_served ?? 85) });
  if (!result) {
    $("#markets-note").textContent = t("Which audiences are underserved? Rank every Steam tag by its games with demand that players rate poorly. Uses the Filters; the first build takes ~7 minutes, then ~1 day from the cache.");
    return;
  }
  const notes = [t("{n} tags, games with ≥ {min} reviews; underserved = {range} positive. Ranked by gap; broad tags (1,000+ games) and tags with under 3 underserved games come last. Click a tag to search it.", {
    n: markets.rows.length, min: fmt(result.min_reviews),
    range: getLang() === "tr" ? `%${result.lo}-${result.hi}` : `${result.lo}-${result.hi}%` })];
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

function renderMarkets() {
  const { key, asc } = markets.sort;
  const val = (r) => (key === "tag" ? r.tag.toLowerCase() : r[key]);
  const rows = [...markets.rows].sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (asc ? 1 : -1));
  markSorted(document.querySelectorAll("#markets th"), key, asc);
  const n = fmt;
  $("#markets tbody").replaceChildren(...rows.map((r) =>
    clickable(el("tr", { title: t("Search {tag}", { tag: r.tag }) },
      el("td", { class: "num" }, r.rank),
      el("td", {}, r.tag),
      el("td", { class: "num" }, n(r.n_games)),
      el("td", { class: "num" }, n(r.n_demand)),
      el("td", { class: "num" }, el("b", {}, n(r.n_underserved))),
      el("td", { class: "num" }, n(r.n_well_served)),
      el("td", { class: "num" }, pct(r.gap)),
      el("td", { class: "num" }, money(r.underserved_gross)),
      el("td", { class: "num" }, r.n_demand ? percent(r.median_rating) : "-"),
    ), () => searchTag(r.tag))));
}

document.querySelectorAll("#markets th[data-key]").forEach((th) => clickable(th, () => {
  const key = th.dataset.key, s = markets.sort;
  markets.sort = { key, asc: s.key === key ? !s.asc : key === "tag" || key === "rank" };
  renderMarkets();
}));

// From the Markets table: search that one tag as a normal games search.
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

// ---------- Past runs: every finished search and market ranking is saved on the server ----------
const runsPop = $("#runs-pop");

function closeRuns() {
  runsPop.hidden = true;
  $("#runs-toggle").setAttribute("aria-expanded", "false");
}

async function openRuns() {
  runsPop.hidden = false;
  $("#runs-toggle").setAttribute("aria-expanded", "true");
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
        el("button", { type: "button", class: "run-del", title: t("Delete this run"), "aria-label": t("Delete run {label}", { label: r.label }),
          onclick: (e) => { e.stopPropagation(); deleteRun(r, item); } }, "×")), () => openRun(r));
      return item;
    }));
  } catch (err) {
    closeRuns();
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
  closeRuns();
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
    // Put its tags and filters back, so "Find opportunities" reruns exactly this search.
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

$("#runs-toggle").addEventListener("click", () => (runsPop.hidden ? openRuns() : closeRuns()));
document.addEventListener("click", (e) => {
  if (!runsPop.hidden && !e.target.closest(".runs-wrap, #toasts")) closeRuns();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !runsPop.hidden) closeRuns();
});

const sortValue = {
  rank: (g) => g.rank,
  name: (g) => g.game.name.toLowerCase(),
  score: (g) => g.opportunity.score,
  reviews: (g) => g.reviews,
  rating: (g) => g.rating,
  recent: (g) => g.recent_share ?? -1,
  gross: (g) => g.box.gross_mid,
  complaint: (g) => g.mining?.categories[0]?.share ?? -1,
  risks: (g) => g.opportunity.penalty,
};

const recentText = (g) => g.recent_share == null ? "-"
  : `${fmt(g.recent_reviews)} (${pct(g.recent_share)})` + (g.recent_rating == null ? "" : t(", {pct} pos", { pct: percent(g.recent_rating) }));
const adjText = (g) => t(" ({pct} without review bombs)", { pct: percent(g.opportunity.effective_rating) });
// The map tooltip's summary line: the same rating text as the table and the drawer, plus the revenue the
// bubble size stands for. A declaration, so the maps (made near the top) can use it.
function mapLine(g) {
  const o = g.opportunity;
  const adj = Math.round(o.effective_rating) !== Math.round(g.rating) ? adjText(g) : "";
  return t("Score {score} · {n} reviews · {pct} pos", { score: Math.round(o.score), n: fmt(g.reviews), pct: percent(g.rating) })
    + adj + " · " + (g.price ? t("Est. revenue {money}", { money: money(g.box.gross_mid) }) : "F2P");
}

// Score change since the previous run with the same tags and filters (only present when one exists).
function delta(g) {
  if (g.new) return el("span", { class: "delta new", title: t("Not in your previous run with these tags") }, t("new"));
  if (g.score_change == null) return null;
  const d = Math.round(g.score_change);
  return el("span", { class: `delta ${d > 0 ? "up" : d < 0 ? "down" : "same"}`, title: t("Change since your previous run with these tags and filters") },
    d > 0 ? `▲${d}` : d < 0 ? `▼${-d}` : "=");
}

// The risks that cost points, as in the score card: the same games the risk-penalty filter hides.
function penaltyText(g) {
  const list = g.score_explained?.penalties || [];
  if (list.length) return list.map((p) => `${p.label} -${p.points}`).join(", ");
  return g.opportunity.penalty > 0 ? `-${Math.round(g.opportunity.penalty)}` : "-";
}

// Quick filter above the ranking: by name, and without games that have a risk penalty.
// Ranks stay those of the full ranking.
function visibleGames() {
  const q = $("#name-filter").value.trim().toLocaleLowerCase();
  const hideRisky = $("#hide-risky").checked;
  return state.games.filter((g) => (!q || g.game.name.toLocaleLowerCase().includes(q))
    && !(hideRisky && g.opportunity.penalty > 0));
}

function applyQuickFilter() {
  map.setGames(visibleGames());
  renderTable();
}
$("#name-filter").addEventListener("input", applyQuickFilter);
$("#hide-risky").addEventListener("change", applyQuickFilter);

function renderTable() {
  const { key, asc } = state.sort;
  const shown = visibleGames();
  $("#filter-count").textContent = shown.length < state.games.length
    ? t("{n} of {total} games shown", { n: shown.length, total: state.games.length }) : "";
  const rows = shown.sort((a, b) => {
    const va = sortValue[key](a), vb = sortValue[key](b);
    return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
  });
  markSorted(document.querySelectorAll("#ranking th"), key, asc);
  $("#ranking tbody").replaceChildren(
    ...rows.map((g) => {
      const o = g.opportunity;
      const adj = Math.round(o.effective_rating) !== Math.round(g.rating) ? adjText(g) : "";
      const top = g.mining?.categories[0];
      return clickable(el("tr", { "data-appid": g.game.appid },
        el("td", {}, starButton(g.game.appid)),
        el("td", { class: "num" }, g.rank),
        el("td", {}, g.game.name),
        el("td", { class: "num" }, scoreAnchor(el("span", { class: "score-pill", style: `background:${scoreColor(o.score)};color:${scoreInk(o.score)}`,
          "aria-label": t("Score {score}. How it is calculated", { score: Math.round(o.score) }) }, Math.round(o.score)), g), delta(g)),
        el("td", { class: "num" }, fmt(g.reviews)),
        el("td", { class: "num" }, `${percent(g.rating)}${adj}`),
        el("td", { class: "num" }, recentText(g)),
        el("td", { class: "num" }, g.price ? money(g.box.gross_mid) : "F2P"),
        el("td", { class: "complaint-cell" }, top ? `${top.label} (${pct(top.share)})` : "-"),
        el("td", { class: "risks-cell" }, penaltyText(g)),
      ), () => selectGame(g.game.appid));
    }),
  );
  highlightRow();
}

document.querySelectorAll("#ranking th[data-key]").forEach((th) =>
  clickable(th, () => {
    const key = th.dataset.key;
    state.sort = { key, asc: state.sort.key === key ? !state.sort.asc : ["rank", "name"].includes(key) };
    renderTable();
  }),
);

// ---------- shortlist: starred games with a note, kept on the server across runs ----------
const isStarred = (appid) => state.shortlist.some((s) => s.appid === appid);

// A star for a game of the current ranking (the server keeps a snapshot of it from this run).
function starButton(appid) {
  const on = isStarred(appid);
  const label = on ? t("Remove from shortlist") : t("Add to shortlist");
  return el("button", { type: "button", class: on ? "star on" : "star", "data-appid": appid, "aria-pressed": String(on),
    "aria-label": label, title: label, onclick: (e) => { e.stopPropagation(); toggleStar(appid); } }, on ? "★" : "☆");
}

function refreshStars() {
  for (const b of document.querySelectorAll(".star[data-appid]")) b.replaceWith(starButton(+b.dataset.appid));
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

function renderShortlist() {
  const list = state.shortlist;
  $("#shortlist-note").textContent = list.length
    ? t("{n} starred games. Score, rating and complaint are from the search you starred them in.", { n: list.length })
    : t("No games yet. Star a game in the ranking (☆) to keep it here.");
  $("#shortlist-csv").hidden = !list.length;
  $("#shortlist tbody").replaceChildren(...list.map((s) => {
    const note = el("input", { class: "note", type: "text", maxlength: "2000", placeholder: t("Add a note..."),
      "aria-label": t("Note for {name}", { name: s.name }) });
    note.value = s.note;
    note.addEventListener("change", async () => {
      try {
        await shortlistCall(`/api/shortlist/${s.appid}`, { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: note.value }) });
        toast("success", t("Note saved"), s.name);
      } catch (err) { notifyError(err); }
    });
    return el("tr", { "data-appid": s.appid },
      clickable(el("td", { class: "name" }, s.name), () => openGame(s.appid)),
      el("td", { class: "num" }, Math.round(s.score)),
      el("td", { class: "num" }, percent(s.rating)),
      el("td", { class: "num" }, fmt(s.reviews)),
      el("td", { class: "complaint-cell" }, s.complaint ? `${s.complaint} (${pct(s.complaint_share)})` : "-"),
      el("td", {}, s.source),
      el("td", {}, note),
      el("td", {}, el("button", { type: "button", class: "ghost remove", "aria-label": t("Remove {name} from the shortlist", { name: s.name }),
        onclick: () => toggleStar(s.appid) }, "×")),
    );
  }));
}

// A shortlisted game: selected if it is in the current ranking, else analyzed into the panel.
function openGame(appid) {
  if (state.games.some((g) => g.game.appid === appid)) return selectGame(appid);
  $("#appid").value = String(appid);
  $("#game-form").requestSubmit();
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
    risk_penalty: [t("Risk penalty"), t("Points taken off the score for something that makes a game a weaker opportunity than it looks, e.g. online multiplayer, fading interest, or recent reviews showing it's already fixed. The Risks column lists them with their points.")],
    risks: [t("Risks"), t("The risks that cost this game points, with how many. Other notes, such as review bombs, are in the game's Risks tab.")],
    revenue: [t("Estimated revenue"), t("Box Method: each review stands for about 30 to 100 copies sold (45 in the middle), times the full price. A rough figure before Steam's cut, discounts, refunds and taxes. Checked against games that published their sales, x45 was right on average, but for a single game it was off by up to about 3 times either way. What the developer keeps is often half of this or less.")],
    recent: [t("Last 12 months"), t("Reviews written in the last 12 months, their share of all reviews, and how positive they are. Few recent reviews mean fading interest; much better recent reviews mean the problems may already be fixed.")],
    loved: [t("What players love"), t("Phrases that come up most often in the positive reviews: what people enjoy, and what a new game should keep.")],
    idea_praise: [t("Great idea, bad execution?"), t("Negative reviews that still praise the idea or its potential. A high share means players want this game, just made better.")],
    with_demand: [t("With demand"), t("Games with at least the minimum number of reviews set in the Filters.")],
    underserved: [t("Underserved"), t("Games with demand whose % positive is inside the range set in the Filters: many players, let down.")],
    well_served: [t("Well served"), t("Games with demand that players rate {pct} positive or more: these players already have a good game.", { pct: percent(state.result?.well_served ?? 85) })],
    unmet_share: [t("Unmet share"), t("Of the games with demand that are clearly rated, the share that are underserved: underserved / (underserved + well served). Higher means players have fewer good games to choose from.")],
    min_reviews: [t("Minimum reviews"), t("How proven the demand must be: a game needs at least this many reviews to be considered.")],
    pct_range: [t("% positive range"), t("Which games count as letting players down. 5-70% leaves out games that are simply broken (under 5%) and games players already like (over 70%).")],
    reviews_read: [t("Reviews read per game"), t("How many reviews are read to find the complaints, half the most helpful and half the newest. More is slower but more reliable.")],
  };
}

// Every risk, with what it means (the glossary lists them; a game's Risks tab says why it got one).
function riskTerms() {
  return [
    [t("Review bomb"), t("A burst of negative reviews about something other than the game itself. The rating is shown without it; no points are taken off.")],
    [t("Streamer spike"), t("A burst of reviews after a streamer played it. Interest like that often doesn't last.")],
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
// Delegated, so ⓘ buttons made later (panel, market strip) work too. A click or tap only toggles the
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

// ---------- detail panel ----------
function bar(labelText, value, text) {
  return el("div", { class: "bar" },
    el("span", {}, labelText),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` })),
    el("span", { class: "val" }, text ?? pct(value)),
  );
}

function renderPanel(g, tab = 0, focus = true) {
  state.panelGame = g;
  const o = g.opportunity;
  const game = g.game;
  const adjusted = Math.round(o.effective_rating) !== Math.round(g.rating);

  const head = [
    el("div", { class: "title-row" }, el("h3", {}, game.name),
      starButton(game.appid)),
    el("div", { class: "sub" },
      el("a", { href: g.store_url, target: "_blank", rel: "noopener" }, t("Steam store")),
      ` · AppID ${game.appid}`,
      g.details ? t(" · Released {date}", { date: g.details.release_date }) : "",
      game.developer ? ` · ${game.developer}` : "",
    ),
    el("div", { class: "score-row" },
      scoreAnchor(el("div", { class: "score-ring", style: `--p:${o.score};--ring:${scoreColor(o.score)}`,
        "aria-label": t("Opportunity score {score}. How it is calculated", { score: Math.round(o.score) }) }, el("span", {}, Math.round(o.score))), g),
      el("div", { class: "facts" },
        el("div", {}, el("span", {}, t("Reviews")), el("b", {}, fmt(g.reviews))),
        el("div", {}, el("span", {}, t("% positive")), el("b", {}, percent(g.rating), adjusted ? adjText(g) : "")),
        el("div", {}, el("span", {}, t("Last 12 months"), info("recent")), el("b", {}, recentText(g))),
        el("div", {}, el("span", {}, t("Est. revenue (x45)"), info("revenue")), el("b", {}, g.price ? money(g.box.gross_mid) : "F2P")),
        el("div", {}, el("span", {}, t("Range (x30-x100)")), el("b", {}, g.price ? `${money(g.box.gross_low)} - ${money(g.box.gross_high)}` : "-")),
      ),
    ),
    g.rating_source_text ? el("p", { class: "muted rating-src" }, t("Review numbers: {source}", { source: g.rating_source_text })) : null,
    el("div", { class: "bars" },
      bar([t("Demand"), info("demand")], o.demand),
      bar([t("Dissatisfaction"), info("dissatisfaction")], o.dissatisfaction),
      bar([t("Fixability"), info("fixability")], o.fixability),
    ),
    o.penalty ? el("div", { class: "penalty" }, t("Risk penalty -{points} ({names})", { points: Math.round(o.penalty),
      names: (g.score_explained?.penalties || []).map((p) => p.label).join(", ") || o.penalized.join(", ") }), info("risk_penalty")) : null,
    g.score_explained ? scoreAnchor(el("button", { type: "button", class: "how-scored" }, t("How is this score calculated?")), g) : null,
    Object.keys(game.tags || {}).length
      ? el("div", { class: "chips" }, Object.keys(game.tags).slice(0, 10).map((tag) => el("button", {
        type: "button", class: "chip", title: t("Search {tag}", { tag }), onclick: () => searchOneTag(tag) }, tag)))
      : null,
  ];

  const tabs = [
    [t("Complaints"), () => complaintsTab(g)],
    [t("What players love"), () => fantasyTab(g)],
    [t("Risks") + (g.flags.length ? ` (${g.flags.length})` : ""), () => risksTab(g)],
    [t("History"), () => historyTab(g)],
    [t("Summary"), () => gameSummaryTab(g)],
  ];
  // ARIA tabs: one Tab stop (the active tab); arrow keys and Home/End move between them.
  const body = el("div", { role: "tabpanel", id: "panel-tabpanel", tabindex: "0" });
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
      body.replaceChildren(render());
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

  $("#panel").replaceChildren(...head.filter(Boolean), tabBar, body);
  $("#panel").scrollTop = 0;
  openDrawer(focus);
}

function complaintsTab(g) {
  const m = g.mining;
  if (g.review_error) return el("div", { class: "callout" }, t("Review texts unavailable: {error}", { error: g.review_error }));
  if (!m || !m.n_negative) return el("div", { class: "callout" }, t("No English negative reviews to mine."));
  return el("div", {},
    el("div", { class: "callout" },
      el("b", {}, t("Great idea, bad execution?")), info("idea_praise"), " ",
      t("{pct} of {n} negative reviews still praise the idea or its potential.", { pct: pct(m.idea_praise_share), n: m.n_negative }) + " ",
      t("{pct} of complaint mentions are fixable.", { pct: pct(m.fixability) })),
    el("p", { class: "muted" },
      t("Half most helpful, half newest reviews ({n} negative from the last 12 months); reviews written under 2 h of play count half.",
        { n: m.n_recent_negative ?? 0 })),
    m.categories.map((c) =>
      el("details", { class: "complaint" },
        el("summary", {},
          bar(c.label, c.share),
          c.trend ? el("div", { class: `trend ${c.trend_kind || "fading"}` }, c.trend) : null,
          el("div", { class: c.fixable ? "pillar" : "pillar unfixable" }, (c.fixable ? t("A new game should: ") : "") + c.pillar)),
        c.quotes.map((q) => el("blockquote", {}, `"${q}"`)),
      ),
    ),
  );
}

// ---------- one game read by the local LLM: written on request, saved with the run ----------
const SUMMARY_TAB = 4;

function gameSummaryTab(g) {
  const s = g.summary;
  if (!s) {
    const inRun = state.games.some((x) => x.game.appid === g.game.appid);
    if (!inRun) return el("div", { class: "callout" }, t("A summary can be written for the games in the current ranking."));
    const busy = state.gameSummarizing === g.game.appid;
    const button = el("button", { type: "button", class: "ghost", onclick: () => writeGameSummary(g) });
    setButtonBusy(button, busy, busy ? t("Writing...") : t("Write summary"));
    return el("div", { class: "opp-empty" },
      el("p", {}, t("Why players are unhappy, what a better game would do, and complaints no category covers. Written by the local model {model} (Ollama) in under a minute.",
        { model: state.result?.llm_model || "" })),
      button);
  }
  return el("div", { class: "game-summary" },
    el("p", { class: "muted" }, t("Written by the local model {model}. It can be wrong: check it against the reviews.", { model: s.model })),
    s.why ? el("p", { class: "opp-pitch" }, s.why) : null,
    s.fix.length ? el("div", {}, el("h4", {}, t("A better game would")), el("ul", {}, s.fix.map((f) => el("li", {}, f)))) : null,
    el("h4", {}, t("Complaints no category covers")),
    s.other.length
      ? s.other.map((o) => el("div", { class: "other-complaint" }, el("p", {}, o.text), el("blockquote", {}, `"${o.quote}"`)))
      : el("p", { class: "muted" }, t("None found in the {n} negative reviews no category matched.", { n: s.n_uncovered })),
  );
}

async function writeGameSummary(g) {
  if (state.gameSummarizing || state.summarizing) return stillRunning(t("A summary is being written."));
  const id = state.runId, appid = g.game.appid;
  state.gameSummarizing = appid;
  if (state.panelGame?.game.appid === appid) renderPanel(state.panelGame, SUMMARY_TAB);
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
    if (state.panelGame?.game.appid === appid) renderPanel(state.panelGame, SUMMARY_TAB);
  }
}

function fantasyTab(g) {
  const m = g.mining;
  if (!m || !(m.core_phrases.length || m.liked.length)) return el("div", { class: "callout" }, t("No positive-review phrases found."));
  const max = Math.max(1, ...m.core_phrases.map(([, n]) => n));
  return el("div", {},
    m.core_phrases.length ? el("p", { class: "muted" }, t("Common phrases in {n} positive reviews", { n: m.n_positive }), info("loved")) : null,
    el("div", { class: "bars" }, m.core_phrases.map(([p, n]) => bar(p, n / max, String(n)))),
    m.liked.length ? el("div", {}, el("p", { class: "muted" }, t("Players liked")),
      el("div", { class: "chips" }, m.liked.map(([p]) => el("span", { class: "chip" }, p)))) : null,
  );
}

const severity = (s) => ({ high: t("Serious"), warn: t("Caution"), info: t("Note") })[s] || s;

function risksTab(g) {
  if (!g.flags.length) return el("div", { class: "callout" }, t("No risk flags."));
  return el("div", {}, g.flags.map((f) =>
    el("div", { class: "risk" },
      el("span", { class: `sev ${f.severity}` }, severity(f.severity)),
      el("div", {}, el("b", { title: f.code }, f.label || f.code), el("div", {}, f.message)),
    ),
  ));
}


function historyTab(g) {
  const POSITIVE = cssVar("--accent-2"), NEGATIVE = cssVar("--bad"); // read now: the theme may have changed
  const h = g.histogram || [];
  if (!h.length) return el("div", { class: "callout" }, t("No review histogram available."));
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
    const tip = t("{month}: {up} positive, {down} negative", { month, up: p.up, down: p.down });
    rect(x, H - pad - upH, w, upH, POSITIVE, tip);
    rect(x, H - pad - upH - downH, w, downH, NEGATIVE, tip);
  });
  const first = new Date(h[0].date * 1000).toISOString().slice(0, 7);
  const last = new Date(h[h.length - 1].date * 1000).toISOString().slice(0, 7);
  return el("div", { class: "hist" },
    svg,
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: `background:${POSITIVE}` }), t("Positive")),
      el("span", {}, el("i", { style: `background:${NEGATIVE}` }), t("Negative")),
      el("span", { style: "margin-left:auto" }, `${first} → ${last}`),
    ),
    el("p", { class: "muted" }, t("Monthly reviews. A tall spike after launch can mean a streamer effect (mostly blue) or a review bomb (mostly red).")),
  );
}

// ---------- EN | TR ----------
// Switching redraws everything in place: static text, labels made in JS, and the current result and
// game fetched again, so the server's text (notices are not re-shown) comes in the new language too.
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
  setSearching(state.searching);
  setAnalyzing(state.analyzing);
  marketsText();
  marketsButton();
  if (markets.result) renderMarkets();
  loadShortlist(); // complaint names come in the new language
  $("#table-title").textContent = tableTitles[tableView]();
  try {
    if (state.runId && state.result) {
      const res = await api(`/api/tag-runs/${state.runId}`);
      if (res.ok) {
        const job = await res.json();
        if (job.status === "done") showResult(job.result, state.runId, true);
      }
    }
    const shown = state.panelGame;
    if (shown && !state.games.some((x) => x.game.appid === shown.game.appid)) renderPanel(await fetchGame(shown.game.appid));
  } catch { /* the old language stays until the next search */ }
}
document.querySelectorAll("#lang button").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));

// ---------- dark | light ----------
// The theme is set before the first paint by the script in index.html; this keeps the switch in sync,
// remembers the choice and redraws what holds colors outside CSS (the 3D scene, the History chart).
function setTheme(theme) {
  theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  for (const b of document.querySelectorAll("#theme button")) b.setAttribute("aria-pressed", String(b.dataset.theme === theme));
  try { localStorage.setItem("theme", theme); } catch { /* storage blocked: not remembered */ }
  map3d?.recolor();
  map2d.relabel(); // redraws
  const active = document.querySelector("#panel .tabs button.active");
  if (state.panelGame && active) renderPanel(state.panelGame, [...active.parentNode.children].indexOf(active));
}
document.querySelectorAll("#theme button").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.theme)));
for (const b of document.querySelectorAll("#theme button")) {
  b.setAttribute("aria-pressed", String(b.dataset.theme === document.documentElement.dataset.theme));
}
let savedMode = "table";
try { savedMode = localStorage.getItem("gamesMode") || "table"; } catch { /* storage blocked */ }
setGamesMode(savedMode);
setLanguage(getLang());
