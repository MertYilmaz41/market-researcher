"""Compare local models on the opportunity summary, the same way for each.

    uv run python -m steam_researcher.summary_eval --models gemma3:12b qwen3.5:9b gemma4:12b

Each model writes the Turkish summary of the same saved runs (the latest few tag runs with 5+ games,
or --runs IDS), with the app's own prompt and settings. Counted per model:
- format: an empty or JSON-looking pitch, a section outside the asked 3-5 points, a point repeated;
- names the app had to remove (not one of the run's games) and points dropped for naming none;
- unsupported claims: a complaint (or a fix of one) pinned on a game whose evidence (the 4 complaints
  per game the model reads) doesn't have it at 5%+ share; "loved" or a complaint pinned on a game with no mined reviews;
- seconds per summary.
The complaint is read from the point's words (Turkish or English keywords below), so a point that
names no complaint is counted as unclassified, not as right or wrong.

It also writes the summaries shuffled and unnamed (reports/summary-eval/blind.md) for judging the
Turkish by eye, with the key in key.json, and the models' raw answers (raw.json), so
--recheck can count again after a change here without asking the models again.
Reads saved runs only: no Steam requests, no cache.
"""

import argparse
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, summary
from .mining import llm
from .models import Analysis
from .runs import RunStore

OUT = Path("reports/summary-eval")
MIN_SHARE = 0.05  # a complaint below this share in a game's evidence doesn't support a claim about it
LANG = "tr"  # --lang en writes to reports/summary-eval-en instead

# Words that say which complaint a point is about (Turkish and English, lower case).
CATEGORY_WORDS = {
    "bugs": r"bug|crash|glitch|çök|hata|broken|bozuk|donma|donuyor|freez",
    "controls": r"kontrol|control|clunky|janky|hantal|tepkisiz",
    "ui_ux": r"arayüz|interface|\bui\b|\bux\b|menü|menu|tutorial|öğretici",
    "content": r"içerik|content|ilerleme|progression|shallow|sığ|tekrar|repetitive",
    "performance": r"performans|performance|\bfps\b|kare hız|optimi|takılma|stutter|\blag\b",
    "abandoned": r"terk|abandon|güncelleme|update|bitmemiş|unfinished|yarım kal",
    # only a lack of realism: "realistic physics" is often what players love
    "realism": r"unrealistic|not realistic|lack of realism|gerçekçi değil|gerçekçilikten uzak|gerçekçilik eksik",
    "scope_unrealistic": r"kapsam|scope|ambitio|iddialı",
}


NOT_A_CATEGORY = r"çeviri hata\w*|translation (?:error|mistake)s?"  # "hata" alone means a bug


def categories_in(text: str) -> set[str]:
    low = re.sub(NOT_A_CATEGORY, " ", text.lower())
    return {code for code, pattern in CATEGORY_WORDS.items() if re.search(pattern, low)}


@dataclass
class Check:
    seconds: float = 0.0
    format_errors: list[str] = field(default_factory=list)
    removed_names: list[str] = field(default_factory=list)  # names in the answer that aren't run games
    dropped_points: int = 0  # points left with no run game (the app hides them)
    supported: int = 0  # (point, game) pairs the evidence backs
    unsupported: list[str] = field(default_factory=list)  # the pairs it doesn't, described
    unclassified: int = 0  # complaint/build points whose complaint couldn't be read from the words


def check(raw: dict, parsed, games: dict[str, Analysis]) -> Check:
    """Pure: what's wrong with one summary. raw = the model's JSON, parsed = summary.parse() of it."""
    out = Check()
    pitch = parsed.pitch.strip()
    if not pitch:
        out.format_errors.append("empty pitch")
    elif pitch[0] in "[{":
        out.format_errors.append("pitch is JSON, not text")
    texts = [pitch] if pitch else []
    for section in summary.SECTIONS:
        points = getattr(parsed, section)
        if not 3 <= len(points) <= 5:
            out.format_errors.append(f"{section}: {len(points)} points")
        texts += [p.text for p in points]
        for p in raw.get(section) or []:
            if not isinstance(p, dict):
                continue
            named = [str(g) for g in p.get("games") or []]
            out.removed_names += [g for g in named if summary._match(g, list(games)) is None]
            if section != "caveats" and str(p.get("text", "")).strip() and \
                    not any(summary._match(g, list(games)) for g in named):
                out.dropped_points += 1
    norm = [" ".join(t.lower().split()) for t in texts]
    if len(set(norm)) < len(norm):
        out.format_errors.append("a point is repeated")

    for section in ("loved", "complaints", "build"):
        for p in getattr(parsed, section):
            cats = categories_in(p.text) if section != "loved" else set()
            if section != "loved" and not cats:
                out.unclassified += 1
            for name in p.games:
                m = games[name].mining
                if m is None or (section == "loved" and not (m.core_phrases or m.liked)) \
                        or (section == "complaints" and not m.categories):
                    out.unsupported.append(f"{section}: {name} has no mined reviews for this")
                    continue
                if not cats:
                    continue
                shares = {c.code: c.share for c in m.categories[:summary.EVIDENCE_CATEGORIES]}
                if any(shares.get(c, 0) >= MIN_SHARE for c in cats):
                    out.supported += 1
                else:
                    out.unsupported.append(f"{section}: {name} has no {'/'.join(sorted(cats))} complaint "
                                           f"at {MIN_SHARE:.0%}+ (\"{p.text[:80]}\")")
    return out


def pick_runs(store: RunStore, n: int) -> list[dict]:
    """The latest tag runs with 5+ games, one per label."""
    out, labels = [], set()
    for r in store.list(200):
        if r["kind"] == "tag" and r["n"] >= 5 and r["label"] not in labels:
            labels.add(r["label"])
            out.append(r)
    return out[:n]


def run(models: list[str], run_ids: list[str], n_runs: int, recheck: bool = False) -> None:
    store = RunStore()
    answers = json.loads((OUT / "raw.json").read_text(encoding="utf-8")) if recheck else []
    if recheck:
        run_ids, models = list(dict.fromkeys(x["run_id"] for x in answers)), list(dict.fromkeys(x["model"] for x in answers))
    runs = [store.load(i) for i in (run_ids or [r["id"] for r in pick_runs(store, n_runs)])]
    checks: dict[str, list[Check]] = {m: [] for m in models}
    written = []  # (run label, model, parsed summary)
    raw_out = []
    for saved in runs:
        res, label = saved["result"], saved["label"]
        text, names = summary.evidence(label, res.analyses, res.market)
        games = {a.game.name: a for a in res.analyses if a.game.name in names}
        for model in models:
            if recheck:
                old = next(x for x in answers if x["run_id"] == saved["id"] and x["model"] == model)
                content, seconds = old["content"], old["seconds"]
            else:
                start = time.monotonic()
                content = llm.post_chat(summary.request(text, LANG, model))
                seconds = time.monotonic() - start
            raw_out.append({"run_id": saved["id"], "model": model, "seconds": round(seconds, 1), "content": content})
            try:
                raw = json.loads(content)
                parsed = summary.parse(content, names)
            except (json.JSONDecodeError, AttributeError) as e:
                c = Check(seconds=seconds, format_errors=[f"not valid JSON: {e}"])
                checks[model].append(c)
                print(f"{label} / {model}: {seconds:.0f} s, not valid JSON", flush=True)
                continue
            c = check(raw, parsed, games)
            c.seconds = seconds
            checks[model].append(c)
            written.append((label, model, parsed))
            print(f"{label} / {model}: {seconds:.0f} s, {len(c.unsupported)} unsupported, "
                  f"{len(c.format_errors)} format errors", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "raw.json").write_text(json.dumps(raw_out, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "results.md").write_text(render(checks, [r["label"] for r in runs]), encoding="utf-8")
    blind(written)
    print(f"wrote {OUT / 'results.md'}, {OUT / 'blind.md'} and {OUT / 'key.json'}")


def render(checks: dict[str, list[Check]], labels: list[str]) -> str:
    lines = [f"# Summary models compared\n\nRuns: {', '.join(labels)}. Language: {LANG}. "
             f"Unsupported = a claim the run's evidence doesn't back (see summary_eval.py).\n",
             "| Model | s / summary | Format errors | Removed names | Dropped points | Supported | Unsupported | "
             "Unclassified |", "|---|---|---|---|---|---|---|---|"]
    for model, cs in checks.items():
        n = len(cs) or 1
        lines.append(f"| {model} | {sum(c.seconds for c in cs) / n:.0f} | {sum(len(c.format_errors) for c in cs)} | "
                     f"{sum(len(c.removed_names) for c in cs)} | {sum(c.dropped_points for c in cs)} | "
                     f"{sum(c.supported for c in cs)} | {sum(len(c.unsupported) for c in cs)} | "
                     f"{sum(c.unclassified for c in cs)} |")
    for model, cs in checks.items():
        lines.append(f"\n## {model}\n")
        for label, c in zip(labels, cs):
            issues = c.format_errors + [f"removed name: {x}" for x in c.removed_names] + c.unsupported
            lines.append(f"- **{label}**: " + ("; ".join(issues) if issues else "no issues found"))
    return "\n".join(lines) + "\n"


def blind(written: list) -> None:
    """The summaries shuffled under letters, for judging the Turkish without knowing the model."""
    order = list(written)
    random.Random(7).shuffle(order)
    parts, key = ["# Özetler (hangi modelin yazdığı gizli)\n\nHer özete 1-5 puan ver: Türkçesi ne kadar doğal, "
                  "ne kadar somut ve işe yarar. Anahtar key.json'da.\n"], {}
    for i, (label, model, s) in enumerate(order):
        letter = f"{chr(65 + i % 26)}{i // 26 or ''}"
        key[letter] = {"run": label, "model": model}
        parts.append(f"\n---\n\n## Özet {letter} ({label})\n\n**Fırsat:** {s.pitch}\n")
        for section, title in [("loved", "Oyuncuların sevdiği"), ("complaints", "Şikâyetler"),
                               ("build", "Ne yapmalı"), ("caveats", "Dikkat")]:
            parts.append(f"\n**{title}**\n")
            parts += [f"- {p.text}" + (f" ({', '.join(p.games)})" if p.games else "") for p in getattr(s, section)]
    (OUT / "blind.md").write_text("\n".join(parts) + "\n", encoding="utf-8")
    (OUT / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    global LANG, OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=[config.LLM_MODEL])
    ap.add_argument("--runs", nargs="*", default=[], help="saved run ids (default: the latest tag runs)")
    ap.add_argument("--n-runs", type=int, default=3)
    ap.add_argument("--recheck", action="store_true", help="count again from raw.json, without the models")
    ap.add_argument("--lang", choices=sorted(summary.LANGUAGES), default=LANG, help="language the summaries are written in")
    args = ap.parse_args()
    if args.lang != LANG:
        LANG, OUT = args.lang, Path(f"reports/summary-eval-{args.lang}")
    run(args.models, args.runs, args.n_runs, args.recheck)


if __name__ == "__main__":
    main()
