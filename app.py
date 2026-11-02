"""Streamlit UI for the Discovery Agent.

Run locally:  streamlit run app.py
Demo mode works without any API key.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from discovery_agent.cli import DEMO_CONTEXT, load_dotenv  # noqa: E402
from discovery_agent.pipeline import DEFAULT_LANGUAGE, load_sources, run_discovery  # noqa: E402
from discovery_agent.providers import EXAMPLES_DIR, ProviderError, get_provider  # noqa: E402
from discovery_agent.report import to_markdown  # noqa: E402
from discovery_agent.schemas import DiscoveryReport, Source  # noqa: E402

load_dotenv()
st.set_page_config(page_title="Discovery Agent", page_icon="🔎", layout="wide")

PROVIDERS = {
    "Demo (no key needed)": "demo",
    "Claude (Anthropic)": "claude",
    "Gemini (free tier available)": "gemini",
    "Ollama (local models)": "ollama",
}
KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Settings")
    provider_label = st.selectbox("Model provider", list(PROVIDERS))
    provider_name = PROVIDERS[provider_label]

    api_key, model = None, None
    if provider_name in KEY_ENV:
        api_key = st.text_input(
            "API key",
            type="password",
            value=os.getenv(KEY_ENV[provider_name], ""),
            help="Used only for this session. It is never stored.",
        )
    if provider_name != "demo":
        model = st.text_input("Model (optional)", placeholder="provider default") or None

    st.divider()
    language = st.text_input("Output language", value="", placeholder=DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
    top_n = st.slider("Opportunities that get user stories", 1, 6, 3)
    stories_per = st.slider("Stories per opportunity", 1, 4, 2)

    st.divider()
    st.caption(
        "Demo mode replays responses recorded with Claude for the bundled, fictional interviews. "
        "Choose a real provider to analyse your own material."
    )

# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #

st.title("🔎 Discovery Agent")
st.markdown(
    "Paste interview transcripts or user feedback. The agent **extracts pains with verbatim quotes**, "
    "**clusters them into themes**, **maps opportunities** and **writes user stories with acceptance "
    "criteria**, keeping every story traceable to the customer evidence behind it."
)

sources: list[Source] = []
if provider_name == "demo":
    context = DEMO_CONTEXT
    sources = load_sources([EXAMPLES_DIR / "interviews"])
    st.info(f"**Demo dataset:** {len(sources)} fictional sources for *ClinicFlow*, a clinic scheduling app.")
    with st.expander("See the example interviews"):
        for s in sources:
            st.markdown(f"**{s.name}**")
            st.text(s.text)
else:
    context = st.text_input(
        "Product context (optional)",
        placeholder="e.g. Mobile app for small gyms to manage memberships. Users: owners, staff, members.",
    )
    tab_paste, tab_upload = st.tabs(["Paste text", "Upload files"])
    with tab_paste:
        pasted = st.text_area(
            "Transcripts or feedback",
            height=260,
            placeholder="Paste one or more transcripts. Separate them with a line containing only ---",
        )
        if pasted.strip():
            parts = [p.strip() for p in pasted.split("\n---\n") if p.strip()]
            sources += [Source(name=f"pasted_{i + 1}", text=p) for i, p in enumerate(parts)]
    with tab_upload:
        files = st.file_uploader("Text or Markdown files", type=["txt", "md"], accept_multiple_files=True)
        for f in files or []:
            sources.append(Source(name=Path(f.name).stem, text=f.read().decode("utf-8", errors="replace")))

run = st.button("Run discovery", type="primary", disabled=not sources)

if run:
    try:
        provider = get_provider(provider_name, model=model, api_key=api_key)
        bar = st.progress(0.0, text="Starting…")
        report = run_discovery(
            sources, provider, context=context, language=language, top_n=top_n,
            stories_per_opportunity=stories_per,
            progress=lambda msg, frac: bar.progress(min(frac, 1.0), text=msg),
        )
        bar.empty()
        st.session_state["report"] = report
    except ProviderError as exc:
        st.error(str(exc))
    except Exception as exc:  # show API errors to the user instead of a stack trace
        st.error(f"Something went wrong: {exc}")

# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #

report: DiscoveryReport | None = st.session_state.get("report")
if report:
    verified = sum(p.quote_verified for p in report.pains)
    cols = st.columns(5)
    cols[0].metric("Pains", len(report.pains))
    cols[1].metric("Themes", len(report.themes))
    cols[2].metric("Opportunities", len(report.opportunities))
    cols[3].metric("User stories", len(report.stories))
    cols[4].metric("Quotes verified", f"{verified}/{len(report.pains)}")

    t_opp, t_stories, t_themes, t_export = st.tabs(
        ["Opportunities", "User stories", "Themes & evidence", "Export"]
    )

    with t_opp:
        st.caption("Score = impact × confidence ÷ effort (1–5 each).")
        st.dataframe(
            [
                {"ID": o.id, "Opportunity": o.title, "Themes": ", ".join(o.theme_ids), "Impact": o.impact,
                 "Confidence": o.confidence, "Effort": o.effort, "Score": o.score}
                for o in report.opportunities
            ],
            hide_index=True, use_container_width=True,
        )
        for o in report.opportunities:
            with st.expander(f"{o.id} · {o.title}  —  score {o.score}"):
                st.markdown(f"**How might we:** {o.how_might_we}")
                st.markdown(f"**Hypothesis:** {o.hypothesis}")
                st.markdown(f"**Rationale:** {o.rationale}")

    with t_stories:
        for s in report.stories:
            st.subheader(f"{s.id} · {s.title}")
            st.markdown(f"> **As a** {s.persona}, **I want** {s.want}, **so that** {s.so_that}.")
            gherkin = "\n".join(
                f"Scenario {i}\n  Given {ac.given}\n  When {ac.when}\n  Then {ac.then}"
                for i, ac in enumerate(s.acceptance_criteria, 1)
            )
            st.code(gherkin, language="gherkin")
            if s.notes:
                st.caption(f"Notes to validate: {s.notes}")
            with st.expander(f"Evidence behind {s.id} ({len(s.pain_ids)} pains)"):
                for pid in s.pain_ids:
                    p = report.pain(pid)
                    if p:
                        st.markdown(f"- **{p.persona}** ({p.source}): “{p.quote}”")

    with t_themes:
        for t in report.themes:
            st.subheader(f"{t.id} · {t.title}")
            st.caption(
                f"{t.mention_count} mentions · {t.source_count} sources · avg severity {t.avg_severity}"
            )
            st.write(t.description)
            st.dataframe(
                [
                    {"Pain": p.id, "Persona": p.persona, "Severity": p.severity, "Statement": p.statement,
                     "Quote": p.quote, "Verified": "✅" if p.quote_verified else "⚠️", "Source": p.source}
                    for pid in t.pain_ids if (p := report.pain(pid))
                ],
                hide_index=True, use_container_width=True,
            )

    with t_export:
        st.download_button("Download Markdown report", to_markdown(report), "discovery_report.md")
        st.download_button(
            "Download JSON", report.model_dump_json(indent=2), "discovery_report.json", "application/json"
        )
        st.caption(f"Generated {report.generated_at} with {report.provider}.")
