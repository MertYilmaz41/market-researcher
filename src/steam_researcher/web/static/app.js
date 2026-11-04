import { createMap } from "/static/map3d.js";

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
const scoreCss = (s) => `hsl(${(Math.max(0, Math.min(100, s)) / 100) * 140} 75% 55%)`;

// ---------- state ----------
const state = { games: [], selected: null, sort: { key: "rank", asc: true }, runId: null };
const map = createMap($("#map"), { onSelect: (appid) => selectGame(appid, { fromMap: true }) });

// ---------- top bar ----------
$("#filters-toggle").addEventListener("click", () => {
  const pop = $("#filters");
  pop.hidden = !pop.hidden;
  $("#filters-toggle").setAttribute("aria-expanded", String(!pop.hidden));
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#filters, #filters-toggle")) $("#filters").hidden = true;
});

$("#tag-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#filters").hidden = true;
  const body = {
    tag: $("#tag").value.trim(),
    min_reviews: +$("#min-reviews").value,
    lo: +$("#lo").value,
    hi: +$("#hi").value,
    max_games: +$("#max-games").value,
    reviews: +$("#reviews").value,
  };
  showError(null);
  $("#run").disabled = true;
  progress(0, "Fetching games tagged " + body.tag + "...");
  try {
    const res = await fetch("/api/tag-runs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await errorText(res));
    const { id } = await res.json();
    state.runId = id;
    await poll(id);
  } catch (err) {
    showError(err.message);
  } finally {
    $("#run").disabled = false;
    progress(null);
  }
});

async function poll(id) {
  for (;;) {
    const res = await fetch(`/api/tag-runs/${id}`);
    if (!res.ok) throw new Error(await errorText(res));
    const job = await res.json();
    if (job.status === "error") throw new Error(job.error);
    if (job.status === "done") return showResult(job.result, id);
    progress(job.total ? job.done / job.total : 0, job.message);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

$("#game-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const raw = $("#appid").value.trim();
  const appid = (raw.match(/\/app\/(\d+)/) || raw.match(/^(\d+)$/) || [])[1];
  if (!appid) return showError("Enter a Steam AppID (e.g. 1330660) or a store URL.");
  showError(null);
  const known = state.games.find((g) => g.game.appid === +appid);
  if (known) return selectGame(+appid);
  progress(0.3, "Analyzing AppID " + appid + "... (first time can take ~15s)");
  try {
    const res = await fetch(`/api/games/${appid}?reviews=${+$("#reviews").value}`);
    if (!res.ok) throw new Error(await errorText(res));
    state.selected = null;
    map.select(null);
    highlightRow();
    renderPanel(await res.json());
  } catch (err) {
    showError(err.message);
  } finally {
    progress(null);
  }
});

async function errorText(res) {
  try {
    const j = await res.json();
    if (Array.isArray(j.detail)) return j.detail.map((d) => d.msg).join("; ");
    return j.detail || res.statusText;
  } catch {
    return res.statusText;
  }
}

function progress(frac, text) {
  const box = $("#progress");
  box.hidden = frac == null;
  if (frac == null) return;
  $("#progress-fill").style.width = `${Math.round(frac * 100)}%`;
  $("#progress-text").textContent = text || "";
}

function showError(msg) {
  $("#error").hidden = !msg;
  $("#error").textContent = msg || "";
}

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
  if (state.games.length) selectGame(state.games[0].game.appid);
  else $("#panel").replaceChildren(el("div", { class: "empty" }, "No games pass these filters. Try a lower minimum or a wider % range."));
}

const sortValue = {
  rank: (g) => g.rank,
  name: (g) => g.game.name.toLowerCase(),
  score: (g) => g.opportunity.score,
  reviews: (g) => g.reviews,
  rating: (g) => g.rating,
  gross: (g) => g.box.gross_mid,
  complaint: (g) => g.mining?.categories[0]?.share ?? -1,
  risks: (g) => riskCodes(g).length,
};

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
        el("td", { class: "num" }, el("span", { class: "score-pill", style: `background:${scoreCss(o.score)}` }, Math.round(o.score))),
        el("td", { class: "num" }, g.reviews.toLocaleString()),
        el("td", { class: "num" }, `${Math.round(g.rating)}%${adj}`),
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

function selectGame(appid, { fromMap = false } = {}) {
  const g = state.games.find((x) => x.game.appid === appid);
  if (!g) return;
  state.selected = appid;
  if (!fromMap) map.select(appid);
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
      el("div", { class: "score-ring", style: `--p:${o.score};--ring:${scoreCss(o.score)}` }, el("span", {}, Math.round(o.score))),
      el("div", { class: "facts" },
        el("div", {}, el("span", {}, "Reviews"), el("b", {}, g.reviews.toLocaleString())),
        el("div", {}, el("span", {}, "% positive"), el("b", {}, `${Math.round(g.rating)}%`, adjusted ? ` (${Math.round(o.effective_rating)}% adj.)` : "")),
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
    rect(x, H - pad - upH, w, upH, "#60a5fa", tip);
    rect(x, H - pad - upH - downH, w, downH, "#f87171", tip);
  });
  const first = new Date(h[0].date * 1000).toISOString().slice(0, 7);
  const last = new Date(h[h.length - 1].date * 1000).toISOString().slice(0, 7);
  return el("div", { class: "hist" },
    svg,
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: "background:#60a5fa" }), "Positive"),
      el("span", {}, el("i", { style: "background:#f87171" }), "Negative"),
      el("span", { style: "margin-left:auto" }, `${first} → ${last}`),
    ),
    el("p", { class: "muted" }, "Monthly reviews. A tall spike after launch can mean a streamer effect (mostly blue) or a review bomb (mostly red)."),
  );
}
