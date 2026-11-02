"""Data models for the discovery pipeline.

Two kinds of models live here:

* ``*Draft`` / ``*Extraction`` models are what the LLM is asked to return.
  They contain no IDs and no computed fields, so the model can't get them wrong.
* Domain models (``Pain``, ``Theme``, ``Opportunity``, ``UserStory``) add the
  IDs, counts and traceability links that the pipeline computes in code.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Step 1 - pain extraction
# --------------------------------------------------------------------------- #


class ExtractedPain(BaseModel):
    statement: str = Field(
        description="The pain in one sentence, from the user's point of view. "
        "Describe the problem, not a solution."
    )
    quote: str = Field(
        description="Verbatim excerpt from the transcript that evidences the pain. "
        "Copy it exactly, without paraphrasing."
    )
    persona: str = Field(description="Who has this pain, e.g. 'Receptionist', 'Clinic owner'.")
    severity: int = Field(
        ge=1,
        le=5,
        description="1 = minor annoyance, 3 = recurring friction, 5 = blocks the job or costs money.",
    )


class PainExtraction(BaseModel):
    pains: list[ExtractedPain]


class Pain(ExtractedPain):
    id: str
    source: str
    quote_verified: bool = Field(
        default=False,
        description="True if the quote was found verbatim in the source text.",
    )


# --------------------------------------------------------------------------- #
# Step 2 - clustering
# --------------------------------------------------------------------------- #


class ThemeDraft(BaseModel):
    title: str = Field(description="Short name for the theme (max ~6 words).")
    description: str = Field(description="One or two sentences describing the underlying problem.")
    pain_ids: list[str] = Field(description="IDs of the pains that belong to this theme.")


class ThemeClustering(BaseModel):
    themes: list[ThemeDraft]


class Theme(ThemeDraft):
    id: str
    mention_count: int = 0
    source_count: int = 0
    avg_severity: float = 0.0


# --------------------------------------------------------------------------- #
# Step 3 - opportunities
# --------------------------------------------------------------------------- #


class OpportunityDraft(BaseModel):
    title: str = Field(description="The opportunity, phrased as a customer need or desired outcome.")
    how_might_we: str = Field(description="A 'How might we ...?' question that frames the opportunity.")
    theme_ids: list[str] = Field(description="IDs of the themes this opportunity addresses.")
    impact: int = Field(ge=1, le=5, description="Expected impact on users and business (1-5).")
    confidence: int = Field(ge=1, le=5, description="How strongly the evidence supports it (1-5).")
    effort: int = Field(ge=1, le=5, description="Rough effort to address it (1 = small, 5 = very large).")
    rationale: str = Field(description="Why this matters, citing the evidence (frequency, severity, personas).")
    hypothesis: str = Field(
        description="A testable hypothesis: 'We believe that <change> for <persona> will result in "
        "<outcome>. We will know when <signal>.'"
    )


class OpportunityMapping(BaseModel):
    opportunities: list[OpportunityDraft]


class Opportunity(OpportunityDraft):
    id: str
    score: float = Field(default=0.0, description="impact x confidence / effort")


# --------------------------------------------------------------------------- #
# Step 4 - user stories
# --------------------------------------------------------------------------- #


class AcceptanceCriterion(BaseModel):
    given: str
    when: str
    then: str


class StoryDraft(BaseModel):
    title: str = Field(description="Short title for the story.")
    persona: str = Field(description="The 'As a ...' part, without the words 'As a'.")
    want: str = Field(description="The 'I want ...' part, without the words 'I want'.")
    so_that: str = Field(description="The 'so that ...' part, without the words 'so that'.")
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        description="2 to 5 testable criteria in Given/When/Then form, including at least one edge case."
    )
    notes: str = Field(
        default="",
        description="Assumptions, open questions or dependencies the team should validate.",
    )


class StoryBatch(BaseModel):
    stories: list[StoryDraft]


class UserStory(StoryDraft):
    id: str
    opportunity_id: str
    pain_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Inputs and final report
# --------------------------------------------------------------------------- #


class Source(BaseModel):
    """One interview transcript or batch of feedback."""

    name: str
    text: str


class DiscoveryReport(BaseModel):
    product_context: str = ""
    sources: list[str]
    pains: list[Pain]
    themes: list[Theme]
    opportunities: list[Opportunity]
    stories: list[UserStory]
    provider: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )

    def pain(self, pain_id: str) -> Pain | None:
        return next((p for p in self.pains if p.id == pain_id), None)

    def theme(self, theme_id: str) -> Theme | None:
        return next((t for t in self.themes if t.id == theme_id), None)

    def opportunity(self, opp_id: str) -> Opportunity | None:
        return next((o for o in self.opportunities if o.id == opp_id), None)
