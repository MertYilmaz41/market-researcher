# Measurements and experiments

The record behind the decisions in `CLAUDE.md`: what was measured, how, and what was tried and dropped. Numbers are from Nov 2026 unless said otherwise. Re-measure before relying on them after a change.

## Complaint miner accuracy

`uv run python -m market_researcher.mining.evaluate` scores the miner against hand-labeled real reviews.

**Label sets**
- `tests/fixtures/labeled_reviews.jsonl` (153 reviews from 9 games): the set to tune on.
- `labeled_reviews_holdout.jsonl` (47 reviews from 6 other games): never tuned on; shows whether a change generalizes.
- `labeled_reviews_holdout2.jsonl` (6 more games, labeled by the user through `scripts/label_server.py`): a second never-tuned set. Only 75 of its 156 reviews are answered (the rest stay in `labeled_reviews_holdout2.unlabeled.jsonl`); rows marked `unsure` are skipped by `evaluate.load`.
- `claude_labeled_reviews.jsonl` (1,077 reviews, 50 games, `"labeler": "claude"`): training and tuning only, never for measuring. A blind check of 40 of them by the user (`claude_check2.user.jsonl`) agreed on 86% of complaint labels (micro-F1; gate 80%); Claude never missed one of the user's labels but added ~10 extra.

**Complaint precision/recall**
- First tuning: tuning 90%/86%, held-out 83%/62%, holdout2 78%/63% (held-out was 86%/53% before tuning; 12 "content" labels in the first two sets were corrected after a blind check by the user).
- Then tuned on the Claude-labeled set (40 of its 50 games; the other 10 as a check): tuning 90%/86%, held-out 85%/62%, holdout2 77%/65%, both held-out sets pooled 80%/64% (was 80%/63%); the 10 check games 81%/54% (was 81%/50%). Most new patterns raised recall on the Claude games but barely moved the human sets, so the human labelers phrase misses differently. Patterns that cost held-out precision were dropped by counting hits only (texts not read): "false advertising", "nothing new", "they promised". Idea praise now also matches praise of the whole game ("the game is fun", "I loved this game"), as LABELING.md asks: holdout2 recall 31% -> 50%. `scope_unrealistic` was left alone: the Claude set has no example of it.
- `abandoned`, tuned on the Claude set's misses only: server shutdowns ("terminate a game", "sunset it", "will be shut down"), removed multiplayer ("remove multiplayer", "multiplayer ... gone"), "lack of developers response", "without ever finishing". Claude set abandoned 78%/48% -> 81%/57%; tuning and both held-out sets unchanged. Then the user set a rule (LABELING.md rule 2): bait and switch and not delivering the promised genre ("not an MMO") are abandoned; "false advertising" only when it says what is missing. The 17 reviews in the human sets with such phrases were relabeled blind by the user; only `abandoned` was applied (6 added: tuning 3, held-out 2, holdout2 1). Patterns added: "bait and switch", "not an MMO", "not what was advertised/promised", "advertised as", "misleading store page/trailer"; the bare phrase "false advertising" is left out, since keywords can't tell its two meanings apart. Claude set abandoned -> 81%/60%; the human sets have no hits for them (no precision cost).
- **Current:** tuning 90%/85%, held-out 85%/60%, holdout2 77%/65%, held-out pooled 80%/63%.

**The user's own labels drift** outside `abandoned`: in that blind relabeling, 9 of 16 sure reviews got a different set of the other categories than the first time (controls, content, performance and ui_ux added or dropped; bugs stable). These are the weak categories, so part of their low scores is label noise, not the miner. Old labels were kept.

**Per game** (`evaluate --games`): what the app shows, from labels vs from the miner, with the same playtime weighting as `mine()`. Keywords on the 12 held-out games (7-16 reviews each): biggest complaint right in 10/12, top-3 overlap ~68%, shares ~0.78x the labeled ones (recall, roughly uniform). The tuning set: 8/9, 94%, 0.97x.

**Fixability barely varies:** 7 of 8 categories are `fixable` (only `scope_unrealistic` isn't), so fixability is ~100% for almost every game (20 games in saved runs: median 100%, min 91%) and its 25% score weight hardly separated games. The user decided to keep the categories as they are (`content` and `abandoned` stay fixable, since both are in the developer's hands), and later to take fixability out of the score.

## Price and cheater patterns

`price` and `cheaters` were added in Nov 2026. The label sets before then don't mark them (LABELING.md rule 4 left price out); from then on both are labeled (`"schema": 2`), and `evaluate` scores `UNLABELED` categories only on schema 2 rows. So far only the Claude-labeled set has them: relabeled by Claude for both, candidates picked by a broad money/cheat regex, so reviews outside it got neither; 128 price, 33 cheaters. Keywords there before tuning: price 88%/18%, cheaters 96%/73%; most missed price complaints were about DLC, paywalls, subscriptions and real-money purchases.

Each pattern was kept only if 80%+ of its hits in all fixture files were real complaints of that kind, judged by Claude reading them:
- First pass, kept: "not worth the money/price" 9/9, "overpriced" 2/2, pay to win/p2w 11/11, mtx 3/3, microtransactions ~11/13, predatory 4/5, cheaters 16/19, hackers 12/14. Dropped: "full price" 3/12, "anti-cheat" 1/9 (mostly complaints about intrusive kernel anti-cheat), "hacking" 4/8, "cash shop" 2/4, "lootbox" 1/2, "too expensive" 1/2, "rip-off" 1/2.
- Second pass, kept: paywall 11/11, "locked behind" DLC/premium 3/3, real money 12/12, "pay real money/more/to play" 13/13, subscription 5/5, battle pass 3/3, paid/cosmetic DLC 5/5, monetization 3/3, premium currency/vehicles 6/6, gacha 1/1, money-hungry/grubbing 4/4, "get/buy/grab it on (a) sale/discount" 6/7. Dropped: greedy 9/16, "on sale" alone 16/26, full price 9/13, crates 3/6, money grab 0/4 (like cash grab), per month 3/11, cash shop 2/5.

Claude set price 88%/18% -> 97%/51% (tuned on, so optimistic; the human sets have no price labels). The 8 old categories scored exactly as before on all four sets ("overpriced" moved here from `content`). Recall on human labels is unmeasured.

## LLMs and classifiers for complaint detection (not adopted)

The code (`classify`, `verify`, `fill`, `--miner`, `--model`, `scripts/embed_classifier.py`) was removed later in Nov 2026; git history has it.
- First test, held-out reviews: gemma3:12b 67%/88% precision/recall, qwen3:30b-a3b 49%/84%, keywords 86%/62%. A blind relabeling by the user sided with the labels, not the LLM, on most disputed "too little content" cases.
- Both human held-out sets together (holdout + the 73 sure reviews of holdout2), on a 16 GB RTX 4060 Ti: keywords 81%/63%; qwen3:14b 65%/74%; phi4:14b 67%/74%; mistral-small3.2:24b 66%/74% (~25 min/game, 88% in VRAM); gpt-oss:20b 69%/68%; gemma3:12b 57%/72%; qwen3:30b-a3b 58%/65%; qwen3.5:9b 64%/70%; gemma4:12b 74%/82% (~2 s/review). None reaches 85% precision; all over-flag (gemma4 too: 18 "content" for 5 labeled in holdout2). gpt-oss gets `think: "low"` (it can't turn thinking off).
- Embeddings + one logistic regression per category (trained on the Claude set + tuning set, threshold per category from 5-fold CV), same 120 held-out reviews: bge-m3 79%/46% and nomic-embed-text 81%/49% at an 85% precision target; lower targets trade precision for recall (bge-m3 at 65%: 60%/66%). Keywords OR classifier raised recall to 70-81% but cut precision to 54-74%. The classifier held 85% in cross-validation but not on the held-out games, so numpy/scikit-learn were not added.
- Keywords checked by an LLM (`verify`: the model may only drop keyword hits, with a quote that must be in the review), after the Claude-set tuning: keywords 80%/64%; gemma3:12b 88%/61%, qwen3:14b 87%/62%, ~2 s per review (~6-8 min per game). Precision +7-8 points, recall -2-3, and a 15-game run would take 1.5-2 h.
- Keywords plus an LLM only where keywords find nothing (`fill`; ~1/3 of reviews, ~3 min per game): gemma3:12b and qwen3:14b both 69%/75% vs keywords 80%/64%. Per game: biggest complaint right 11/12 (gemma) and 10/12 (qwen) vs 10/12, top-3 overlap ~75-77% vs ~68%, shares ~1.08x instead of ~0.78x. Mostly false `content` and `abandoned`.
- With gemma4:12b: `verify` 93%/54% (biggest complaint 10/12, shares ~0.58x), `fill` 72%/72% (10/12, top-3 ~77%, shares ~1.0x), keywords 80%/63% (10/12, ~68%, ~0.76x). The categories gemma4 adds correctly in `fill`, counted on the tuning and Claude sets: bugs 84% right, abandoned 64%, every other category under 50% (content 40% of 118). Allowing only bugs and abandoned: Claude set 78%/62% -> 77%/71%; held-out 80.4%/62.8% -> 78.4%/66.4%, biggest complaint still 10/12, top-3 ~70%, shares ~0.82x. A gain within the noise of 12 games, for ~1 min per game and a need for Ollama.
- Conclusion: more human labels (more held-out games) would help more than another model.

## Summary model choice

`summary_eval.py`: each model writes the summary of the same saved runs with the app's prompt; the script counts format errors, game names `parse()` removes, and unsupported claims (a complaint, or a fix of one, pinned on a game whose evidence, the 4 complaints per game the model reads, lacks it at 5%+; the complaint is read from the point's words via `CATEGORY_WORDS`). "Loved" and caveats are barely checked. `realism` is read only as a lack of it ("unrealistic"), since "realistic physics" is usually praise.
- Turkish, 3 runs (Rugby, Motorbike, Cyberpunk + Incremental): gemma4:12b 43 s/summary, 59 supported / 0 unsupported, 1 format slip (2 caveats instead of 3+); gemma3:12b 115 s, 57/5, 2 made-up names; qwen3.5:9b 77 s, 62/11. The user's blind read also picked gemma4's.
- English (`--lang en`): gemma4 32 s, 64/3 (the 3 at a 4% share, just under the bar); qwen3.5 43 s, 52/1; gemma3 64 s, 62/8. So qwen3.5's weakness is Turkish.
- Game summary (Rugby 25): gemma4 more concrete than gemma3 (27 s vs 40 s).
- Earlier: gemma3:12b was steady and grounded but partly generic; qwen3:30b-a3b was sharper but once returned empty sections and made factual slips. The prompt was written while looking at gemma3's answers, so earlier comparisons favored it.
- With thinking on, qwen3.5:9b took 225 s for a summary instead of ~80.

## Backtest results

Method and rules are in `CLAUDE.md`; the report is `reports/backtest.md`.
- **Full run (Nov 7 2026; 32k histograms, 676 usable rows, 180 tags): the unmet share does not predict hits.** Gap vs hit rate rho -0.04 (-0.17 to +0.09), -0.06 with market size held fixed; top fifth's hit rate 10.7% vs bottom 11.6%. Not one of the criteria, but clear: gap vs sold rate +0.19 (+0.05 to +0.31), sold rate rising by fifth 14% -> 21%; market size vs hit rate +0.28. A high unmet share means players keep buying, not that a new game gets rated well.
- **Recent check** (2023-01 and 2024-01, 12-month windows, fixed before it was run, never tuned on): gap vs hit rate -0.12 (-0.27 to +0.02), gap vs sold rate +0.13 (-0.03 to +0.27).
- **Other market measures** (`CANDIDATES`, written down Nov 7 2026 before they were measured). Check rho / recent rho:
  - earlier entrants' hit rate (games released 48-24 months before T): +0.47 (+0.42 with size fixed), fifths 14.6% vs 7.3%; recent +0.30. Adopted (strongest).
  - well-served games: +0.36 (+0.15 size fixed), 11.7% vs 7.8%; recent +0.22. Adopted.
  - games with demand (market size): +0.33, 11.0% vs 6.2%; recent +0.17. Adopted, but its pooled result (+0.28) had been seen before.
  - underserved games: +0.25 but -0.04 with size fixed (a size proxy). Rejected. Releases in the 24 months before T: +0.07. Rejected.
  - So new games do well where earlier games did well, and in big markets with many well-liked games: the opposite of the method's "unhappy audience" idea.

## Box Method check

`uv run python -m market_researcher.boxcheck` (report: `reports/box-check.md`).
- **29 disclosed figures, 23 scored:** median 44x, middle half 32x-80x, 10th-90th 13x-125x; 70% inside x30-x100; x45 within 1.5x of the real figure for 57%, within 2x for 61%.
- Most rows are hits announcing milestones (Valheim, PEAK, Brotato...), few are small games, and none was released before 2019, so rule C (per era) equals B and the era effect from the literature is untested here. Seen after the fact: the three smallest games of the first batch (51-234 reviews) sold only 14-30x, the biggest hits up to 121-178x.
- **Small-games test:** small-game postmortems with unit figures are rare and most have under 20 reviews: 6 found, 3 scored (Prickle 9x, The Fall of Lazarus 32x, TAURONOS 128x; median 32x, large games 53x). Too few to tell, and the three disagree.
- **Earlier, with the first 6 games:** 16x, 30x, 38x, 54x, 100x, 165x; x45 was off by 1.2-3.7x for a single game.
- **Literature:** GameDiscoverCo and Gamalytic (2023) give ~93 sales per review in 2013 and ~32 in 2023. Steam's review prompt from 2019 halved the ratio. Heavy discounting raises it (40-57). Their figures are mostly Gamalytic's own estimates, so they are no independent check.
- **Gross is not income:** gross = units x undiscounted price. Escape Simulator took ~$10 a unit against a $14.99 list price, before Steam's cut, refunds and taxes.

## Steam endpoint timings

- Steam's review API is sometimes very slow: 20-90+ s per page.
- GetAppReviews said 1,588 reviews for Apex Legends, against 1.18 million in its histogram and 453,416 English ones on the store page (why the histogram wins when the summary is under half its total).
- The HTTP cache reached 733 MB before `mr cache prune` existed.
