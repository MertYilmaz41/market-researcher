"""Click-to-label page for review fixtures (tests/fixtures/LABELING.md has the rules).

    uv run python scripts/label_server.py tests/fixtures/labeled_reviews_holdout2.jsonl --out holdout2.user.jsonl
    uv run python scripts/label_server.py tests/fixtures/claude_labeled_reviews.jsonl --out check.user.jsonl --sample 60
    uv run python scripts/label_server.py tests/fixtures/claude_labeled_reviews.jsonl --out check2.user.jsonl --sample 40 --exclude check.user.jsonl

Shows one review at a time with a checkbox per complaint category; the input's own labels are never
shown (a check of someone else's labels is blind). Every answer is written to --out at once, so the
page can be closed and reopened. --sample N picks N reviews spread over the games (fixed seed);
--exclude leaves out the reviews already answered in earlier answer files.
"""

import argparse
import json
import random
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

CATEGORIES = [  # code, Turkish name, hint (see LABELING.md)
    ("controls", "Kötü kontroller / hantal his", "kontrol, kamera, direksiyon, hareket, fizik hissi"),
    ("bugs", "Oyunu bozan hatalar", "hata, çökme, donma, takılma, kayıt kaybı, saçma yapay zekâ"),
    ("ui_ux", "Kafa karıştıran arayüz", "menüler, öğretici yok, ne yapılacağı anlaşılmıyor"),
    ("content", "Az içerik / sığ ilerleme", "yapacak az şey, kısa, tekrarlıyor, boş, sığ"),
    ("performance", "Kötü performans", "düşük FPS, takılma, uzun yükleme, optimizasyon"),
    ("abandoned", "Geliştirici bıraktı", "güncelleme yok, vaat tutulmadı, yıllardır bitmemiş"),
    ("realism", "Gerçekçi simülasyon değil", "arcade gibi, gerçek hayata uymuyor"),
    ("scope_unrealistic", "AAA beklentisi", "indie'den GTA ölçeği bekliyor"),
]
CODES = [c for c, _n, _h in CATEGORIES]


class Answer(BaseModel):
    id: str
    labels: list[str] = []
    idea_praise: bool = False
    unsure: bool = False


def pick(rows: list[dict], n: int | None, seed: int = 7) -> list[dict]:
    """n reviews spread evenly over the games (all of them when n is None), in a shuffled order."""
    rng = random.Random(seed)
    if n is None or n >= len(rows):
        out = list(rows)
    else:
        by_game: dict[int, list[dict]] = {}
        for r in rows:
            by_game.setdefault(r["appid"], []).append(r)
        for group in by_game.values():
            rng.shuffle(group)
        out, i = [], 0
        while len(out) < n:  # round robin over the games
            for group in by_game.values():
                if i < len(group) and len(out) < n:
                    out.append(group[i])
            i += 1
    rng.shuffle(out)
    return out


def make_app(items: list[dict], out: Path) -> FastAPI:
    app = FastAPI()
    lock = threading.Lock()
    by_id = {str(r["id"]): r for r in items}
    answers: dict[str, dict] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = json.loads(line)
                answers[a["id"]] = a

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.get("/api/items")
    def get_items() -> dict:
        return {"categories": [{"code": c, "name": n, "hint": h} for c, n, h in CATEGORIES],
                "items": [{"id": str(r["id"]), "text": r["text"]} for r in items],
                "answers": answers}

    @app.post("/api/answer")
    def save(a: Answer) -> dict:
        r = by_id[a.id]
        labels = [] if a.unsure else [c for c in CODES if c in a.labels]
        row = {"id": a.id, "appid": r["appid"], "playtime_minutes": r.get("playtime_minutes"), "text": r["text"],
               "labels": labels, "idea_praise": a.idea_praise and not a.unsure, "unsure": a.unsure,
               "labeler": "user"}
        with lock:
            answers[a.id] = row
            out.write_text("".join(json.dumps(answers[str(x["id"])], ensure_ascii=False) + "\n"
                                   for x in items if str(x["id"]) in answers), encoding="utf-8")
        return {"saved": len(answers)}

    return app


PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>İnceleme etiketleme</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#667085; --line:#d9dee7; --accent:#2f6fde; --pick:#e8f0ff; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14171d; --card:#1d2129; --text:#e7eaf0; --muted:#98a2b3; --line:#323844; --accent:#6c9cff; --pick:#22304a; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, sans-serif; }
  main { max-width: 860px; margin: 0 auto; padding: 16px; }
  header { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px; }
  .bar { height:6px; background:var(--line); border-radius:3px; overflow:hidden; flex:1; }
  .bar span { display:block; height:100%; background:var(--accent); width:0; }
  .review { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; white-space:pre-wrap; min-height:120px; }
  .cats { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:8px; margin:12px 0; }
  label.cat { display:flex; gap:10px; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px; cursor:pointer; user-select:none; }
  label.cat:has(input:checked) { background:var(--pick); border-color:var(--accent); }
  label.cat small { display:block; color:var(--muted); }
  label.cat kbd { color:var(--muted); font-size:12px; }
  .actions { display:flex; flex-wrap:wrap; gap:8px; }
  button { font:inherit; padding:10px 16px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--text); cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; flex:1; }
  .muted { color:var(--muted); font-size:13px; }
  .done { text-align:center; padding:40px 0; }
</style></head>
<body><main>
  <header><b id="count"></b><div class="bar"><span id="fill"></span></div><span class="muted" id="state"></span></header>
  <div class="review" id="text"></div>
  <div class="cats" id="cats"></div>
  <div class="actions">
    <button id="back">&larr; Geri</button>
    <button id="unsure">Emin değilim</button>
    <button id="next" class="primary">Kaydet ve ileri &rarr;</button>
  </div>
  <p class="muted">Kategori yoksa hiçbir şeyi işaretlemeden ilerleyin. Kısayollar: 1-8 kategoriler, 9 fikri övüyor, Enter ileri. Kurallar: tests/fixtures/LABELING.md</p>
</main>
<script>
let data, i = 0;
const $ = (s) => document.querySelector(s);
function box(code, name, hint, key) {
  const label = document.createElement("label"); label.className = "cat";
  const input = document.createElement("input"); input.type = "checkbox"; input.value = code;
  const span = document.createElement("span");
  const b = document.createElement("b"); b.textContent = name + " ";
  const k = document.createElement("kbd"); k.textContent = key;
  const small = document.createElement("small"); small.textContent = hint;
  b.append(k); span.append(b, small); label.append(input, span);
  return label;
}
function show() {
  const n = data.items.length, done = Object.keys(data.answers).length;
  $("#count").textContent = Math.min(i + 1, n) + " / " + n;
  $("#fill").style.width = (100 * done / n) + "%";
  $("#state").textContent = done + " kaydedildi";
  if (i >= n) {
    $("#text").textContent = "Bitti, hepsi kaydedildi. Bu sekmeyi kapatabilirsiniz.";
    $("#cats").hidden = true; return;
  }
  $("#cats").hidden = false;
  const item = data.items[i], a = data.answers[item.id];
  $("#text").textContent = item.text;
  for (const input of document.querySelectorAll("#cats input")) {
    input.checked = a ? (input.value === "idea_praise" ? a.idea_praise : a.labels.includes(input.value)) : false;
  }
  $("#state").textContent += a ? (a.unsure ? " · bu inceleme: emin değilim" : " · bu inceleme kaydedilmiş") : "";
  window.scrollTo(0, 0);
}
async function save(unsure) {
  const item = data.items[i]; if (!item) return;
  const checked = [...document.querySelectorAll("#cats input:checked")].map((x) => x.value);
  const body = { id: item.id, labels: checked.filter((c) => c !== "idea_praise"), idea_praise: checked.includes("idea_praise"), unsure };
  const res = await fetch("/api/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) { alert("Kaydedilemedi (HTTP " + res.status + ")"); return; }
  data.answers[item.id] = { ...body, labels: unsure ? [] : body.labels };
  i++; show();
}
$("#next").onclick = () => save(false);
$("#unsure").onclick = () => save(true);
$("#back").onclick = () => { if (i > 0) { i--; show(); } };
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); save(false); return; }
  const boxes = document.querySelectorAll("#cats input");
  const k = Number(e.key);
  if (k >= 1 && k <= boxes.length) boxes[k - 1].click();
});
fetch("/api/items").then((r) => r.json()).then((d) => {
  data = d;
  d.categories.forEach((c, n) => $("#cats").append(box(c.code, c.name, c.hint, n + 1)));
  $("#cats").append(box("idea_praise", "Fikri / potansiyeli övüyor", "harika fikir ama..., çok potansiyeli var", 9));
  i = d.items.findIndex((x) => !(x.id in d.answers)); if (i < 0) i = d.items.length;
  show();
});
</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--port", type=int, default=8502)
    ap.add_argument("--exclude", type=Path, nargs="*", default=[])
    args = ap.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = {str(json.loads(line)["id"]) for f in args.exclude for line in f.read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = [r for r in rows if str(r["id"]) not in done]
    app = make_app(pick(rows, args.sample), args.out)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Labeling {args.sample or len(rows)} reviews at {url} (answers go to {args.out}). Ctrl+C to stop.")
    threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
