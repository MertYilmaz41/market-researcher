"""Streamlit UI. Launch with `sr ui` (runs `streamlit run` on this file)."""

import datetime as dt

import pandas as pd
import streamlit as st

from steam_researcher import boxmethod, config
from steam_researcher.http import HttpClient
from steam_researcher.models import Analysis
from steam_researcher.pipeline import analyze_game, run_tag
from steam_researcher.report import money, rank, render, slug

SEVERITY_ICON = {"high": ":red[**high**]", "warn": ":orange[warn]", "info": ":blue[info]"}


def ranking_frame(analyses: list[Analysis]) -> pd.DataFrame:
    rows = []
    for a in rank(analyses):
        g, o = a.game, a.opportunity
        top = a.mining.categories[0] if a.mining and a.mining.categories else None
        rows.append({
            "Game": g.name,
            "Score": round(o.score),
            "Reviews": g.reviews,
            "% Pos": round(g.rating),
            "% Pos (adj.)": round(o.effective_rating),
            "Price": g.base_price,
            "Est. gross (x45)": boxmethod.estimate(g.reviews, g.base_price).gross_mid,
            "Top complaint": f"{top.label} ({top.share:.0%})" if top else "-",
            "Risks": ", ".join(f.code for f in a.flags if f.severity != "info") or "-",
            "AppID": g.appid,
        })
    return pd.DataFrame(rows)


def show_game(a: Analysis) -> None:
    g, o = a.game, a.opportunity
    st.subheader(g.name)
    st.caption(
        f"[Steam store]({g.store_url}) · AppID {g.appid}"
        + (f" · Released {a.details.release_date}" if a.details else "")
        + (f" · {g.developer}" if g.developer else "")
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Opportunity", f"{o.score:.0f}/100")
    c2.metric("Reviews", f"{g.reviews:,}")
    adj = None if round(o.effective_rating) == round(g.rating) else f"{o.effective_rating:.0f}% adj."
    c3.metric("% positive", f"{g.rating:.0f}%", adj, delta_color="off")
    if g.base_price:
        est = boxmethod.estimate(g.reviews, g.base_price)
        c4.metric("Est. gross (x45)", money(est.gross_mid), f"{money(est.gross_low)} - {money(est.gross_high)}",
                  delta_color="off")
    else:
        c4.metric("Price", "Free")

    st.progress(o.demand, text=f"Demand {o.demand:.0%}")
    st.progress(o.dissatisfaction, text=f"Dissatisfaction {o.dissatisfaction:.0%} (at {o.effective_rating:.0f}% positive)")
    st.progress(o.fixability, text=f"Fixability {o.fixability:.0%}")
    if o.penalty:
        st.caption(f"Risk penalty: -{o.penalty:.0f} ({', '.join(o.penalized)})")
    if g.tags:
        st.caption("Tags: " + ", ".join(list(g.tags)[:12]))

    tab_complaints, tab_fantasy, tab_risks, tab_history = st.tabs(
        ["What went wrong", "Core fantasy", "Risk checks", "Review history"]
    )

    with tab_complaints:
        m = a.mining
        if a.review_error:
            st.warning(f"Review texts unavailable: {a.review_error}")
        elif not m or not m.n_negative:
            st.info("No English negative reviews to mine.")
        else:
            st.markdown(
                f"**{m.n_negative} negative reviews analyzed.** {m.idea_praise_share:.0%} still praise the idea "
                f"or its potential; {m.fixability:.0%} of complaint mentions are fixable."
            )
            st.dataframe(
                pd.DataFrame([
                    {"Complaint": c.label, "% of negative": round(100 * c.share),
                     "Design pillar (do this instead)": c.pillar + ("" if c.fixable else " (not fixable)")}
                    for c in m.categories
                ]),
                hide_index=True, width="stretch",
                column_config={"% of negative": st.column_config.ProgressColumn(format="%d%%", max_value=100)},
            )
            for c in m.categories:
                with st.expander(f"{c.label}: {c.count} reviews"):
                    for q in c.quotes:
                        st.markdown(f"> {q}")

    with tab_fantasy:
        m = a.mining
        if m and m.core_phrases:
            st.markdown(f"Common phrases in **{m.n_positive}** positive reviews:")
            st.bar_chart(pd.DataFrame(m.core_phrases, columns=["Phrase", "Reviews"]).set_index("Phrase"),
                         horizontal=True)
        if m and m.liked:
            st.markdown("**Players liked:** " + ", ".join(p for p, _ in m.liked))
        if not (m and (m.core_phrases or m.liked)):
            st.info("No positive-review phrases found.")

    with tab_risks:
        if not a.flags:
            st.success("No risk flags.")
        for f in a.flags:
            st.markdown(f"{SEVERITY_ICON[f.severity]} `{f.code}`: {f.message}")

    with tab_history:
        if not a.has_histogram:
            st.info("No review histogram available.")
        else:
            hist = pd.DataFrame(
                [{"Month": dt.datetime.fromtimestamp(p.date, dt.UTC).strftime("%Y-%m"),
                  "Positive": p.up, "Negative": p.down} for p in a.histogram]
            ).set_index("Month")
            st.bar_chart(hist, color=["#d9534f", "#4a90d9"])
            st.caption("Monthly reviews. Spikes after launch can mean a streamer effect or a review bomb.")


def tag_page() -> None:
    with st.sidebar:
        st.header("Filters")
        tag = st.text_input("Steam tag", "Job Simulator", help="e.g. Job Simulator, Colony Sim, Management, Life Sim")
        min_reviews = st.number_input("Minimum reviews", 10, 100_000, config.MIN_REVIEWS, step=50)
        lo, hi = st.slider("% positive", 0, 100, (int(config.MIN_RATING), int(config.MAX_RATING)))
        max_games = st.slider("Games to analyze", 1, 40, 15,
                              help="Highest review count first. First runs take ~3s per game; cached afterwards.")
        reviews = st.slider("Reviews mined per game", 50, 500, 200, step=50)
        run = st.button("Find opportunities", type="primary", width="stretch")

    if run:
        bar = st.progress(0.0, text=f"Fetching games tagged {tag!r}...")

        def step(message: str, done: int, total: int) -> None:
            bar.progress(min(1.0, done / total) if total else 0.0, text=message)

        result = run_tag(HttpClient(), tag, int(min_reviews), lo, hi, max_games, reviews, step)
        bar.empty()
        st.session_state["result"] = (tag, int(min_reviews), lo, hi, result)

    if "result" not in st.session_state:
        st.info("Pick a tag and filters in the sidebar, then press **Find opportunities**.")
        return
    tag, min_reviews, lo, hi, result = st.session_state["result"]
    if result is None:
        st.error(f"No games found for tag {tag!r}. Check the spelling.")
        return
    if not result.analyses:
        st.warning(f"{len(result.candidates)} of {result.n_tag_games} games pass the filters; nothing to analyze.")
        return

    st.subheader(f"{tag}: opportunity ranking")
    st.caption(
        f"{len(result.candidates)} of {result.n_tag_games} games have >= {min_reviews} reviews and "
        f"{lo}-{hi}% positive; analyzed the {len(result.analyses)} with most reviews."
        + (f" Excluded non-games: {', '.join(result.not_games)}." if result.not_games else "")
    )
    frame = ranking_frame(result.analyses)
    event = st.dataframe(
        frame, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={
            "Score": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=100),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Est. gross (x45)": st.column_config.NumberColumn(format="$%d"),
            "% Pos": st.column_config.NumberColumn(format="%d%%"),
            "% Pos (adj.)": st.column_config.NumberColumn(format="%d%%"),
            "AppID": st.column_config.NumberColumn(format="%d"),
        },
    )
    md = render(tag=tag, analyses=result.analyses, n_candidates=len(result.candidates),
                n_tag_games=result.n_tag_games, min_reviews=min_reviews, lo=lo, hi=hi,
                not_games=result.not_games, unlisted=result.unlisted)
    st.download_button("Download Markdown report", md, file_name=f"{slug(tag)}.md", mime="text/markdown")

    ranked = rank(result.analyses)
    rows = event.selection.rows if event and event.selection else []
    st.divider()
    if rows:
        show_game(ranked[rows[0]])
    else:
        st.caption("Select a row to see complaints, core fantasy, risks and review history. Showing #1:")
        show_game(ranked[0])


def game_page() -> None:
    with st.sidebar:
        st.header("Single game")
        appid = st.number_input("Steam AppID", 1, 10_000_000, 1330660, step=1)
        reviews = st.slider("Reviews mined", 50, 500, 300, step=50)
        run = st.button("Analyze", type="primary", width="stretch")
    if run:
        with st.spinner("Fetching SteamSpy, Steam store data and reviews..."):
            st.session_state["game"] = analyze_game(HttpClient(), int(appid), reviews)
            st.session_state["game_appid"] = int(appid)
    if "game" not in st.session_state:
        st.info("Enter an AppID in the sidebar (from the ranking or a Steam store URL).")
        return
    if st.session_state["game"] is None:
        st.error(f"SteamSpy has no data for AppID {st.session_state['game_appid']}.")
        return
    show_game(st.session_state["game"])


def main() -> None:
    st.set_page_config(page_title="Steam Researcher", page_icon=":mag:", layout="wide")
    st.title("Steam Researcher")
    st.caption("Proven Demand + Poor Execution = High Opportunity (CodeMonkey's Underserved Audience method)")
    page = st.sidebar.radio("Mode", ["Tag research", "Single game"], horizontal=True)
    tag_page() if page == "Tag research" else game_page()


main()
