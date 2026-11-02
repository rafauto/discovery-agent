"""Render a DiscoveryReport as Markdown (GitHub-friendly, with a Mermaid tree)."""

from __future__ import annotations

from .schemas import DiscoveryReport


def _esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _mermaid_label(text: str, limit: int = 90) -> str:
    text = text.replace('"', "'")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def opportunity_tree(report: DiscoveryReport) -> str:
    """Mermaid flowchart: themes -> opportunities -> stories."""
    lines = ["```mermaid", "flowchart LR"]
    used_themes = {tid for o in report.opportunities for tid in o.theme_ids}
    for t in report.themes:
        if t.id in used_themes:
            lines.append(f'  {t.id}["{t.id} · {_mermaid_label(t.title)}<br/>{t.mention_count} mentions"]')
    for o in report.opportunities:
        lines.append(f'  {o.id}(["{o.id} · {_mermaid_label(o.title)}<br/>score {o.score}"])')
        for tid in o.theme_ids:
            lines.append(f"  {tid} --> {o.id}")
    for s in report.stories:
        lines.append(f'  {s.id}["{s.id} · {_mermaid_label(s.title, 70)}"]')
        lines.append(f"  {s.opportunity_id} --> {s.id}")
    lines.append("```")
    return "\n".join(lines)


def to_markdown(report: DiscoveryReport) -> str:
    out: list[str] = []
    verified = sum(p.quote_verified for p in report.pains)

    out.append("# Discovery report\n")
    if report.product_context:
        out.append(f"**Product context:** {report.product_context}\n")
    out.append(
        f"Generated {report.generated_at} with `{report.provider}` from "
        f"{len(report.sources)} sources: {', '.join(report.sources)}.\n"
    )
    out.append(
        f"| Pains | Themes | Opportunities | User stories | Quotes verified |\n"
        f"|---|---|---|---|---|\n"
        f"| {len(report.pains)} | {len(report.themes)} | {len(report.opportunities)} | "
        f"{len(report.stories)} | {verified}/{len(report.pains)} |\n"
    )

    # Opportunities -------------------------------------------------------- #
    out.append("## Opportunities (ranked)\n")
    out.append("Score = impact × confidence ÷ effort (1–5 each).\n")
    out.append("| ID | Opportunity | Themes | Impact | Confidence | Effort | Score |")
    out.append("|---|---|---|---|---|---|---|")
    for o in report.opportunities:
        out.append(
            f"| {o.id} | {_esc(o.title)} | {', '.join(o.theme_ids)} | {o.impact} | "
            f"{o.confidence} | {o.effort} | **{o.score}** |"
        )
    out.append("")
    for o in report.opportunities:
        out.append(f"### {o.id} · {o.title}\n")
        out.append(f"- **How might we:** {o.how_might_we}")
        out.append(f"- **Hypothesis:** {o.hypothesis}")
        out.append(f"- **Rationale:** {o.rationale}\n")

    out.append("### Opportunity tree\n")
    out.append(opportunity_tree(report) + "\n")

    # Stories -------------------------------------------------------------- #
    out.append("## User stories\n")
    for s in report.stories:
        out.append(f"### {s.id} · {s.title}\n")
        out.append(f"> **As a** {s.persona}, **I want** {s.want}, **so that** {s.so_that}.\n")
        out.append(f"Opportunity: {s.opportunity_id} · Evidence: {', '.join(s.pain_ids)}\n")
        out.append("**Acceptance criteria**\n")
        out.append("```gherkin")
        for i, ac in enumerate(s.acceptance_criteria, 1):
            out.append(f"Scenario {i}")
            out.append(f"  Given {ac.given}")
            out.append(f"  When {ac.when}")
            out.append(f"  Then {ac.then}")
        out.append("```")
        if s.notes:
            out.append(f"\n_Notes to validate:_ {s.notes}")
        out.append("")

    # Themes and evidence ------------------------------------------------- #
    out.append("## Themes and evidence\n")
    for t in report.themes:
        out.append(f"### {t.id} · {t.title}\n")
        out.append(
            f"{t.description}\n\n{t.mention_count} mentions · {t.source_count} sources · "
            f"avg severity {t.avg_severity}\n"
        )
        out.append("| Pain | Persona | Sev. | Statement | Quote | Source |")
        out.append("|---|---|---|---|---|---|")
        for pid in t.pain_ids:
            p = report.pain(pid)
            if not p:
                continue
            check = "" if p.quote_verified else " ⚠️"
            out.append(
                f"| {p.id} | {_esc(p.persona)} | {p.severity} | {_esc(p.statement)} | "
                f"“{_esc(p.quote)}”{check} | {p.source} |"
            )
        out.append("")

    if verified < len(report.pains):
        out.append("⚠️ = quote not found verbatim in the source; review before sharing.\n")
    return "\n".join(out)
