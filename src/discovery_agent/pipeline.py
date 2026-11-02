"""The discovery pipeline: sources -> pains -> themes -> opportunities -> user stories.

The LLM does the judgement calls (what is a pain, what belongs together, what
is worth doing). Everything that must be exact is done in code: IDs, counts,
scores, quote verification and the traceability links between artefacts.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from . import prompts
from .providers import BaseProvider, ProviderError, T
from .schemas import (
    DiscoveryReport,
    Opportunity,
    OpportunityMapping,
    Pain,
    PainExtraction,
    Source,
    StoryBatch,
    Theme,
    ThemeClustering,
    UserStory,
)

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]

MAX_CHUNK_CHARS = 12_000
DEFAULT_LANGUAGE = "the same language as the transcripts"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def load_sources(paths: list[str | Path]) -> list[Source]:
    """Load .txt/.md files (or every such file inside a directory) as sources."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in {".txt", ".md"}))
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(f"Not found: {p}")
    if not files:
        raise FileNotFoundError("No .txt or .md files found.")
    return [Source(name=f.stem, text=f.read_text(encoding="utf-8")) for f in files]


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split long transcripts on paragraph boundaries so each call stays small."""
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
        while len(current) > max_chars:  # a single huge paragraph
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        chunks.append(current)
    return chunks


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[\"'`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True if every fragment of the quote (split on ellipses) appears in the text."""
    haystack = _normalize(text)
    fragments = [f.strip(" .,;:") for f in re.split(r"\.\.\.|…|\[\.\.\.\]", quote)]
    fragments = [_normalize(f) for f in fragments if len(f.strip()) > 3]
    return bool(fragments) and all(f in haystack for f in fragments)


def _call(provider: BaseProvider, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
    """Call the provider, retrying once with the validation error as feedback."""
    try:
        return provider.generate(step=step, system=system, prompt=prompt, schema=schema)
    except (ValidationError, ValueError) as exc:
        if provider.name == "demo":
            raise
        log.warning("Step %s returned invalid output, retrying: %s", step, exc)
        retry_prompt = (
            f"{prompt}\n\nYour previous answer was invalid:\n{exc}\n"
            "Return a corrected answer that matches the schema exactly."
        )
        return provider.generate(step=step, system=system, prompt=retry_prompt, schema=schema)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


def extract_pains(
    provider: BaseProvider,
    sources: list[Source],
    context: str = "",
    language: str = DEFAULT_LANGUAGE,
    progress: ProgressFn | None = None,
) -> list[Pain]:
    system = prompts.with_language(prompts.EXTRACT_SYSTEM, language)
    pains: list[Pain] = []
    for i, source in enumerate(sources):
        if progress:
            progress(f"Extracting pains from {source.name}", i / max(len(sources), 1))
        for j, chunk in enumerate(chunk_text(source.text)):
            result = _call(
                provider,
                step=f"extract:{source.name}:{j}",
                system=system,
                prompt=prompts.extract_prompt(source.name, chunk, context),
                schema=PainExtraction,
            )
            for raw in result.pains:
                pains.append(
                    Pain(
                        **raw.model_dump(),
                        id=f"P{len(pains) + 1:03d}",
                        source=source.name,
                        quote_verified=quote_in_text(raw.quote, source.text),
                    )
                )
    unverified = [p.id for p in pains if not p.quote_verified]
    if unverified:
        log.warning("Quotes not found verbatim in the source: %s", ", ".join(unverified))
    return pains


def cluster_pains(
    provider: BaseProvider, pains: list[Pain], context: str = "", language: str = DEFAULT_LANGUAGE
) -> list[Theme]:
    if not pains:
        return []
    lines = "\n".join(f"{p.id} | {p.persona} | {p.severity} | {p.statement}" for p in pains)
    result = _call(
        provider,
        step="cluster",
        system=prompts.with_language(prompts.CLUSTER_SYSTEM, language),
        prompt=prompts.cluster_prompt(lines, context),
        schema=ThemeClustering,
    )

    by_id = {p.id: p for p in pains}
    assigned: set[str] = set()
    themes: list[Theme] = []
    for draft in result.themes:
        # keep only known IDs, and each pain in a single theme
        ids = [pid for pid in dict.fromkeys(draft.pain_ids) if pid in by_id and pid not in assigned]
        if not ids:
            continue
        assigned.update(ids)
        themes.append(Theme(**{**draft.model_dump(), "pain_ids": ids}, id=""))

    leftover = [p.id for p in pains if p.id not in assigned]
    if leftover:
        themes.append(
            Theme(
                id="",
                title="Other pains",
                description="Pains the clustering step did not assign to any theme.",
                pain_ids=leftover,
            )
        )

    for theme in themes:
        members = [by_id[pid] for pid in theme.pain_ids]
        theme.mention_count = len(members)
        theme.source_count = len({p.source for p in members})
        theme.avg_severity = round(sum(p.severity for p in members) / len(members), 1)

    themes.sort(key=lambda t: (t.source_count, t.mention_count, t.avg_severity), reverse=True)
    for i, theme in enumerate(themes, 1):
        theme.id = f"T{i}"
    return themes


def _theme_block(theme: Theme, pains_by_id: dict[str, Pain], max_quotes: int = 3) -> str:
    members = [pains_by_id[pid] for pid in theme.pain_ids]
    strongest = sorted(members, key=lambda p: p.severity, reverse=True)[:max_quotes]
    quotes = "\n".join(f'  - "{p.quote}" ({p.persona}, {p.source})' for p in strongest)
    personas = ", ".join(sorted({p.persona for p in members}))
    return (
        f"{theme.id}: {theme.title}\n"
        f"  {theme.description}\n"
        f"  Mentions: {theme.mention_count} | Sources: {theme.source_count} | "
        f"Avg severity: {theme.avg_severity} | Personas: {personas}\n"
        f"  Sample quotes:\n{quotes}"
    )


def map_opportunities(
    provider: BaseProvider,
    themes: list[Theme],
    pains: list[Pain],
    context: str = "",
    language: str = DEFAULT_LANGUAGE,
) -> list[Opportunity]:
    if not themes:
        return []
    pains_by_id = {p.id: p for p in pains}
    block = "\n\n".join(_theme_block(t, pains_by_id) for t in themes)
    result = _call(
        provider,
        step="opportunities",
        system=prompts.with_language(prompts.OPPORTUNITY_SYSTEM, language),
        prompt=prompts.opportunity_prompt(block, context),
        schema=OpportunityMapping,
    )
    valid_theme_ids = {t.id for t in themes}
    opportunities: list[Opportunity] = []
    for draft in result.opportunities:
        theme_ids = [tid for tid in dict.fromkeys(draft.theme_ids) if tid in valid_theme_ids]
        if not theme_ids:
            continue
        score = round(draft.impact * draft.confidence / draft.effort, 1)
        opportunities.append(
            Opportunity(**{**draft.model_dump(), "theme_ids": theme_ids}, id="", score=score)
        )
    opportunities.sort(key=lambda o: o.score, reverse=True)
    for i, opp in enumerate(opportunities, 1):
        opp.id = f"O{i}"
    return opportunities


def write_stories(
    provider: BaseProvider,
    opportunities: list[Opportunity],
    themes: list[Theme],
    pains: list[Pain],
    context: str = "",
    language: str = DEFAULT_LANGUAGE,
    top_n: int = 3,
    stories_per_opportunity: int = 2,
    progress: ProgressFn | None = None,
) -> list[UserStory]:
    system = prompts.with_language(prompts.STORY_SYSTEM, language)
    themes_by_id = {t.id: t for t in themes}
    pains_by_id = {p.id: p for p in pains}
    stories: list[UserStory] = []
    selected = opportunities[:top_n]
    for i, opp in enumerate(selected):
        if progress:
            progress(f"Writing stories for {opp.id}", i / max(len(selected), 1))
        pain_ids = [pid for tid in opp.theme_ids for pid in themes_by_id[tid].pain_ids]
        evidence = "\n".join(
            f"- [{pid}] {pains_by_id[pid].persona}: {pains_by_id[pid].statement} "
            f'Quote: "{pains_by_id[pid].quote}"'
            for pid in pain_ids
        )
        opp_block = (
            f"{opp.id}: {opp.title}\nHow might we: {opp.how_might_we}\n"
            f"Hypothesis: {opp.hypothesis}\nRationale: {opp.rationale}"
        )
        result = _call(
            provider,
            step=f"stories:{opp.id}",
            system=system,
            prompt=prompts.story_prompt(opp_block, evidence, context, stories_per_opportunity),
            schema=StoryBatch,
        )
        for draft in result.stories:
            stories.append(
                UserStory(
                    **draft.model_dump(),
                    id=f"US{len(stories) + 1:02d}",
                    opportunity_id=opp.id,
                    pain_ids=pain_ids,
                )
            )
    return stories


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run_discovery(
    sources: list[Source],
    provider: BaseProvider,
    *,
    context: str = "",
    language: str = DEFAULT_LANGUAGE,
    top_n: int = 3,
    stories_per_opportunity: int = 2,
    progress: ProgressFn | None = None,
) -> DiscoveryReport:
    """Run the full pipeline and return a report with full traceability."""
    if not sources:
        raise ValueError("Provide at least one source.")

    def stage(label: str, start: float, span: float) -> ProgressFn | None:
        if not progress:
            return None
        return lambda msg, frac: progress(msg, start + span * frac)

    pains = extract_pains(provider, sources, context, language, stage("extract", 0.0, 0.45))
    if not pains:
        raise ProviderError("No pains were found in the sources.")

    if progress:
        progress("Clustering pains into themes", 0.5)
    themes = cluster_pains(provider, pains, context, language)

    if progress:
        progress("Mapping opportunities", 0.65)
    opportunities = map_opportunities(provider, themes, pains, context, language)

    stories = write_stories(
        provider,
        opportunities,
        themes,
        pains,
        context,
        language,
        top_n,
        stories_per_opportunity,
        stage("stories", 0.75, 0.25),
    )
    if progress:
        progress("Done", 1.0)

    return DiscoveryReport(
        product_context=context,
        sources=[s.name for s in sources],
        pains=pains,
        themes=themes,
        opportunities=opportunities,
        stories=stories,
        provider=provider.label,
    )
