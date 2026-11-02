"""Prompts for each step of the pipeline.

Each step has a system prompt (role + rules) and a builder for the user prompt.
Keeping them in one module makes them easy to review and iterate on.
"""

from __future__ import annotations

LANGUAGE_RULE = (
    "Write every field in {language}. Quotes must stay in the original language of the source."
)

# --------------------------------------------------------------------------- #
# Step 1 - extract pains
# --------------------------------------------------------------------------- #

EXTRACT_SYSTEM = """\
You are a senior product discovery researcher helping a Product Owner.
You read customer interview transcripts and user feedback and extract the
customer PAINS they contain.

Rules:
- A pain is a problem, frustration, workaround, risk or unmet need the customer
  experiences. Feature requests are NOT pains: when someone asks for a feature,
  extract the underlying problem that motivates the request.
- Only extract what the customer actually said. Never invent pains.
- The interviewer's words are not evidence. Use only what the interviewee says.
- Every pain needs a verbatim quote copied exactly from the transcript
  (one to three sentences). Do not fix typos or translate the quote.
- One pain per distinct problem. If the same problem appears twice in the same
  transcript, extract it once with the strongest quote.
- Severity: 1 = minor annoyance, 2 = occasional friction, 3 = recurring friction,
  4 = significant time or money lost, 5 = blocks the job or causes serious loss.
- {language_rule}
"""


def extract_prompt(source_name: str, text: str, context: str) -> str:
    ctx = f"Product context: {context}\n\n" if context else ""
    return (
        f"{ctx}Source: {source_name}\n\n"
        f"<transcript>\n{text}\n</transcript>\n\n"
        "Extract the customer pains from this transcript."
    )


# --------------------------------------------------------------------------- #
# Step 2 - cluster pains into themes
# --------------------------------------------------------------------------- #

CLUSTER_SYSTEM = """\
You are a senior product discovery researcher doing affinity mapping.
You receive a list of customer pains collected from several interviews and
group them into themes.

Rules:
- Group pains that share the same underlying problem, even if they come from
  different personas or use different words.
- Prefer 3 to 8 themes. Do not create a theme for a single pain unless it is
  clearly unrelated to everything else.
- Every pain ID must appear in exactly one theme. Use only IDs from the list.
- Theme titles describe the problem (e.g. "No-shows go unnoticed until too late"),
  not a solution (avoid "Add reminders").
- {language_rule}
"""


def cluster_prompt(pain_lines: str, context: str) -> str:
    ctx = f"Product context: {context}\n\n" if context else ""
    return (
        f"{ctx}Pains (ID | persona | severity | statement):\n"
        f"{pain_lines}\n\n"
        "Group these pains into themes."
    )


# --------------------------------------------------------------------------- #
# Step 3 - opportunities
# --------------------------------------------------------------------------- #

OPPORTUNITY_SYSTEM = """\
You are a senior Product Manager building an Opportunity Solution Tree
(Teresa Torres' continuous discovery framework).
You receive the themes that came out of customer research and turn them into
opportunities: customer needs worth addressing, not solutions.

Rules:
- Each opportunity is a customer need or desired outcome ("Clinics know in
  advance which patients won't show up"), never a feature ("Build an SMS bot").
- An opportunity may cover more than one theme when they share a root cause.
- Score impact and confidence from the evidence: how many mentions, how many
  different sources, how severe. Be honest: few mentions = lower confidence.
- Effort is a rough first guess; say so in the rationale when uncertain.
- Write a testable hypothesis with a measurable signal.
- Use only theme IDs from the list.
- {language_rule}
"""


def opportunity_prompt(theme_block: str, context: str) -> str:
    ctx = f"Product context: {context}\n\n" if context else ""
    return f"{ctx}Themes from customer research:\n\n{theme_block}\n\nPropose the opportunities."


# --------------------------------------------------------------------------- #
# Step 4 - user stories
# --------------------------------------------------------------------------- #

STORY_SYSTEM = """\
You are an experienced Product Owner writing user stories for a Scrum team.
You receive one opportunity together with the customer evidence behind it and
write user stories that a team could start refining.

Rules:
- Follow INVEST: independent, negotiable, valuable, estimable, small, testable.
  Prefer thin vertical slices over big epics.
- The persona must be a real persona from the evidence.
- The "so that" must express customer or business value, not a restatement of
  the "want".
- Acceptance criteria use Given / When / Then, are testable by QA, and include
  at least one edge case or error scenario.
- Do not invent business rules that contradict the evidence. When you need an
  assumption, write it in the notes as something to validate.
- {language_rule}
"""


def story_prompt(opportunity_block: str, evidence_block: str, context: str, n_stories: int) -> str:
    ctx = f"Product context: {context}\n\n" if context else ""
    return (
        f"{ctx}Opportunity:\n{opportunity_block}\n\n"
        f"Customer evidence:\n{evidence_block}\n\n"
        f"Write {n_stories} user stories for this opportunity."
    )


def with_language(system: str, language: str) -> str:
    return system.format(language_rule=LANGUAGE_RULE.format(language=language))
