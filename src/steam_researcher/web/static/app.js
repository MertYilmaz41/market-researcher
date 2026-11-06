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
const map2d = createMap2d($("#map"), { onSelect: onMapSelect });
let map3d = null;
try {
  const { createMap } = await import("/static/map3d.js");
  const m = createMap($("#map"), { onSelect: onMapSelect });
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
  setButtonBusy($("#run"), on, on ? t("Searching...") : t("Find opportunities"));
}

function setAnalyzing(on) {
  state.analyzing = on;
  setButtonBusy($("#game-form button"), on, on ? t("Analyzing...") : t("Analyze"));
}

function stillRunning(what) {
  toast("info", t("Please wait"), what, t("Wait for it to finish, then try again."));
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
const tagPicker = { tags: [], picked: ["Job Simulator"], shown: [], active: -1, freeText: false };

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
      el("button", { type: "button", tabindex: "-1", "aria-label": t("Remove {tag}", { tag }),
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
  openFilters(false);
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
    searchStatus(tag, job.total ? job.done / job.total : 0, progressCount(job.total ? `${job.done} / ${job.total}` : "", job.eta), job.message);
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
  renderMarketStrip(result.market, result.well_served);
  state.runId = id;
  renderSummary();
  $("#download").href = `/api/tag-runs/${id}/report.md?lang=${getLang()}`;
  $("#download-csv").href = `/api/tag-runs/${id}/ranking.csv?lang=${getLang()}`;
  if (!quiet) setTableView("games");
  else $("#table-title").textContent = tableTitles[tableView]();

  map.setGames(state.games);
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
    selectGame(state.games[0].game.appid);
  } else {
    state.selected = null;
    const why = (result.notices || []).find((n) => n.level === "warning");
    $("#panel").replaceChildren(el("div", { class: "empty" },
      why ? `${why.title}. ${why.hint}` : t("No games to show. Try a lower minimum or a wider % range.")));
  }
}

// The whole tag, not just the analyzed games: is this audience underserved or already well served?
function renderMarketStrip(m, wellServed) {
  const strip = $("#market-strip");
  strip.hidden = !m;
  if (!m) return;
  const stat = (value, label, cls = "", title = "") => el("div", { class: cls, title }, el("b", {}, value), el("span", {}, label));
  const rated = m.n_underserved + m.n_well_served;
  const verdict = rated < 5 ? t("Too few games with demand to judge this market.")
    : m.gap >= 0.5 ? t("Many disappointed players and few good games: an underserved audience.")
    : m.gap >= 0.3 ? t("A mixed market: some good games already serve these players.")
    : t("Mostly well served: players here already have good games.");
  strip.replaceChildren(
    stat(fmt(m.n_games), t("Games in tag")),
    stat(fmt(m.n_demand), t("With demand")),
    stat(fmt(m.n_underserved), t("Underserved"), "good"),
    stat(fmt(m.n_well_served), t("Well served ({pct}+)", { pct: percent(wellServed) })),
    stat(pct(m.gap), t("Gap"), m.gap >= 0.5 ? "good" : "", t("Underserved / (underserved + well served)")),
    stat(money(m.underserved_gross), t("Underserved $"), "", t("Box Method (x45) gross of the underserved games")),
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
};
let tableView = "games";

function setTableView(view) {
  tableView = view;
  for (const b of document.querySelectorAll("#table-view button")) b.setAttribute("aria-pressed", String(b.dataset.view === view));
  $("#games-view").hidden = view !== "games";
  $("#markets-view").hidden = view !== "markets";
  $("#table-title").textContent = tableTitles[view]();
  for (const a of [$("#download"), $("#download-csv")]) a.hidden = view !== "games" || !state.games.length;
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
  for (const th of document.querySelectorAll("#markets th")) {
    th.classList.toggle("sorted", th.dataset.key === key);
    th.classList.toggle("asc", th.dataset.key === key && asc);
  }
  const n = fmt;
  $("#markets tbody").replaceChildren(...rows.map((r) =>
    el("tr", { onclick: () => searchTag(r.tag), title: t("Search {tag}", { tag: r.tag }) },
      el("td", { class: "num" }, r.rank),
      el("td", {}, r.tag),
      el("td", { class: "num" }, n(r.n_games)),
      el("td", { class: "num" }, n(r.n_demand)),
      el("td", { class: "num" }, el("b", {}, n(r.n_underserved))),
      el("td", { class: "num" }, n(r.n_well_served)),
      el("td", { class: "num" }, pct(r.gap)),
      el("td", { class: "num" }, money(r.underserved_gross)),
      el("td", { class: "num" }, r.n_demand ? percent(r.median_rating) : "-"),
    )));
}

$("#markets thead").addEventListener("click", (e) => {
  const key = e.target.closest("th")?.dataset.key;
  if (!key) return;
  const s = markets.sort;
  markets.sort = { key, asc: s.key === key ? !s.asc : key === "tag" || key === "rank" };
  renderMarkets();
});

// From the Markets table: search that one tag as a normal games search.
function searchTag(tag) {
  if (state.searching) return stillRunning(t("A search is still running."));
  if (tagPicker.freeText) tagInput.value = tag;
  else { tagPicker.picked = [tag]; renderChips(); }
  setTableView("games");
  $("#tag-form").requestSubmit();
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
      const item = el("li", { class: r.id === state.runId ? "current" : "", onclick: () => openRun(r) },
        el("div", { class: "run-main" },
          el("b", {}, r.kind === "market" ? t("Markets: all tags") : r.label),
          el("span", {}, `${dateTime(r.created)} · ${count(r)}`)),
        el("button", { type: "button", class: "run-del", title: t("Delete this run"), "aria-label": t("Delete run {label}", { label: r.label }),
          onclick: (e) => { e.stopPropagation(); deleteRun(r, item); } }, "×"));
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
  risks: (g) => risks(g).length,
};

const recentText = (g) => g.recent_share == null ? "-"
  : `${fmt(g.recent_reviews)} (${pct(g.recent_share)})` + (g.recent_rating == null ? "" : t(", {pct} pos", { pct: percent(g.recent_rating) }));
const adjText = (g) => t(" ({pct} adj.)", { pct: percent(g.opportunity.effective_rating) });

// Score change since the previous run with the same tags and filters (only present when one exists).
function delta(g) {
  if (g.new) return el("span", { class: "delta new", title: t("Not in your previous run with these tags") }, t("new"));
  if (g.score_change == null) return null;
  const d = Math.round(g.score_change);
  return el("span", { class: `delta ${d > 0 ? "up" : d < 0 ? "down" : "same"}`, title: t("Change since your previous run with these tags and filters") },
    d > 0 ? `▲${d}` : d < 0 ? `▼${-d}` : "=");
}

const risks = (g) => g.flags.filter((f) => f.severity !== "info");

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
      const adj = Math.round(o.effective_rating) !== Math.round(g.rating) ? adjText(g) : "";
      const top = g.mining?.categories[0];
      return el("tr", { "data-appid": g.game.appid, onclick: () => selectGame(g.game.appid) },
        el("td", { class: "num" }, g.rank),
        el("td", {}, g.game.name),
        el("td", { class: "num" }, scoreAnchor(el("span", { class: "score-pill", style: `background:${scoreColor(o.score)};color:${scoreInk(o.score)}`,
          "aria-label": t("Score {score}. How it is calculated", { score: Math.round(o.score) }) }, Math.round(o.score)), g), delta(g)),
        el("td", { class: "num" }, fmt(g.reviews)),
        el("td", { class: "num" }, `${percent(g.rating)}${adj}`),
        el("td", { class: "num" }, recentText(g)),
        el("td", { class: "num" }, g.price ? money(g.box.gross_mid) : "F2P"),
        el("td", { class: "complaint-cell" }, top ? `${top.label} (${pct(top.share)})` : "-"),
        el("td", { class: "risks-cell" }, risks(g).map((f) => f.label || f.code).join(", ") || "-"),
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
      row("", t("Combined (weighted geometric mean)"), Math.round(e.combined)),
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
  const a = anchor.getBoundingClientRect(), t = scoreTip.getBoundingClientRect(), gap = 10;
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  let left = a.right + gap; // beside the score; flip to the left side when there's no room
  if (left + t.width > vw - 8) left = Math.max(8, a.left - gap - t.width);
  let top = a.top + a.height / 2 - t.height / 2;
  top = Math.max(8, Math.min(top, vh - t.height - 8));
  scoreTip.style.left = `${left}px`;
  scoreTip.style.top = `${top}px`;
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

// ---------- detail panel ----------
function bar(labelText, value, text) {
  return el("div", { class: "bar" },
    el("span", {}, labelText),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` })),
    el("span", { class: "val" }, text ?? pct(value)),
  );
}

function renderPanel(g, tab = 0) {
  state.panelGame = g;
  const o = g.opportunity;
  const game = g.game;
  const adjusted = Math.round(o.effective_rating) !== Math.round(g.rating);

  const head = [
    el("h3", {}, game.name),
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
        el("div", {}, el("span", {}, t("Last 12 months")), el("b", {}, recentText(g))),
        el("div", {}, el("span", {}, t("Est. gross (x45)")), el("b", {}, g.price ? money(g.box.gross_mid) : "F2P")),
        el("div", {}, el("span", {}, t("Range (x30-x100)")), el("b", {}, g.price ? `${money(g.box.gross_low)} - ${money(g.box.gross_high)}` : "-")),
      ),
    ),
    g.rating_source_text ? el("p", { class: "muted rating-src" }, t("Review numbers: {source}", { source: g.rating_source_text })) : null,
    el("div", { class: "bars" },
      bar(t("Demand"), o.demand),
      bar(t("Dissatisfaction"), o.dissatisfaction),
      bar(t("Fixability"), o.fixability),
    ),
    o.penalty ? el("div", { class: "penalty" }, t("Risk penalty -{points} ({names})", { points: Math.round(o.penalty),
      names: (g.score_explained?.penalties || []).map((p) => p.label).join(", ") || o.penalized.join(", ") })) : null,
    g.score_explained ? scoreAnchor(el("button", { type: "button", class: "how-scored" }, t("How is this score calculated?")), g) : null,
    Object.keys(game.tags || {}).length
      ? el("div", { class: "chips" }, Object.keys(game.tags).slice(0, 10).map((t) => el("span", { class: "chip" }, t)))
      : null,
  ];

  const tabs = [
    [t("Complaints"), () => complaintsTab(g)],
    [t("Core fantasy"), () => fantasyTab(g)],
    [t("Risks") + (g.flags.length ? ` (${g.flags.length})` : ""), () => risksTab(g)],
    [t("History"), () => historyTab(g)],
    [t("Summary"), () => gameSummaryTab(g)],
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
    if (i === tab) { b.classList.add("active"); body.replaceChildren(render()); }
  });

  $("#panel").replaceChildren(...head.filter(Boolean), tabBar, body);
  $("#panel").scrollTop = 0;
}

function complaintsTab(g) {
  const m = g.mining;
  if (g.review_error) return el("div", { class: "callout" }, t("Review texts unavailable: {error}", { error: g.review_error }));
  if (!m || !m.n_negative) return el("div", { class: "callout" }, t("No English negative reviews to mine."));
  return el("div", {},
    el("div", { class: "callout" },
      el("b", {}, t("Great idea, bad execution?") + " "),
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
          el("div", { class: c.fixable ? "pillar" : "pillar unfixable" }, (c.fixable ? t("Do: ") : "") + c.pillar)),
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
    m.core_phrases.length ? el("p", { class: "muted" }, t("Common phrases in {n} positive reviews", { n: m.n_positive })) : null,
    el("div", { class: "bars" }, m.core_phrases.map(([p, n]) => bar(p, n / max, String(n)))),
    m.liked.length ? el("div", {}, el("p", { class: "muted" }, t("Players liked")),
      el("div", { class: "chips" }, m.liked.map(([p]) => el("span", { class: "chip" }, p)))) : null,
  );
}

const severity = (s) => ({ high: t("high"), warn: t("warn"), info: t("info") })[s] || s;

function risksTab(g) {
  if (!g.flags.length) return el("div", { class: "callout" }, t("No risk flags."));
  return el("div", {}, g.flags.map((f) =>
    el("div", { class: "risk" },
      el("span", { class: `sev ${f.severity}` }, severity(f.severity)),
      el("div", {}, el("b", { title: f.code }, f.label || f.code), el("div", {}, f.message)),
    ),
  ));
}

const POSITIVE = cssVar("--accent-2"), NEGATIVE = cssVar("--bad"); // History bars

function historyTab(g) {
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
setLanguage(getLang());
