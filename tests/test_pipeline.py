from discovery_agent.pipeline import chunk_text, quote_in_text, run_discovery
from discovery_agent.schemas import Source

TEXT_A = "Interviewer: hi\nUser: I lose two hours a day confirming appointments by hand. It's awful."
TEXT_B = "User: Patients don't show up and I can't see how often it happens."


def pain(statement, quote, persona="Receptionist", severity=3):
    return {"statement": statement, "quote": quote, "persona": persona, "severity": severity}


def scripted():
    return {
        "extract:a:0": {
            "pains": [
                pain(
                    "Manual confirmations take hours.",
                    "I lose two hours a day confirming appointments by hand.",
                    severity=4,
                ),
                pain("Invented pain.", "This sentence is not in the transcript.", severity=2),
            ]
        },
        "extract:b:0": {
            "pains": [
                pain("No-shows happen.", "Patients don't show up", "Owner", 5),
                pain("No visibility into no-shows.", "I can't see how often it happens.", "Owner", 3),
            ]
        },
        "cluster": {
            "themes": [
                # P001 + P003 from different sources; P999 doesn't exist and must be dropped
                {"title": "No-shows", "description": "d", "pain_ids": ["P003", "P001", "P999"]},
                # P001 duplicated in a second theme: must stay only in the first one
                {"title": "Visibility", "description": "d", "pain_ids": ["P004", "P001"]},
            ]
        },
        "opportunities": {
            "opportunities": [
                {
                    "title": "Low score",
                    "how_might_we": "hmw",
                    "theme_ids": ["T2"],
                    "impact": 2,
                    "confidence": 2,
                    "effort": 4,
                    "rationale": "r",
                    "hypothesis": "h",
                },
                {
                    "title": "High score",
                    "how_might_we": "hmw",
                    "theme_ids": ["T1", "T42"],
                    "impact": 5,
                    "confidence": 4,
                    "effort": 2,
                    "rationale": "r",
                    "hypothesis": "h",
                },
                {
                    "title": "Only unknown themes",
                    "how_might_we": "hmw",
                    "theme_ids": ["T42"],
                    "impact": 5,
                    "confidence": 5,
                    "effort": 1,
                    "rationale": "r",
                    "hypothesis": "h",
                },
            ]
        },
        "stories:O1": {
            "stories": [
                {
                    "title": "Auto confirm",
                    "persona": "receptionist",
                    "want": "auto confirmations",
                    "so_that": "I save time",
                    "acceptance_criteria": [
                        {"given": "g", "when": "w", "then": "t"},
                        {"given": "g2", "when": "w2", "then": "t2"},
                    ],
                },
            ]
        },
    }


def run(fake_provider_cls, responses=None, **kwargs):
    provider = fake_provider_cls(responses or scripted())
    sources = [Source(name="a", text=TEXT_A), Source(name="b", text=TEXT_B)]
    return provider, run_discovery(sources, provider, top_n=1, **kwargs)


def test_ids_and_sources_are_assigned_in_code(fake_provider_cls):
    _, report = run(fake_provider_cls)
    assert [p.id for p in report.pains] == ["P001", "P002", "P003", "P004"]
    assert [p.source for p in report.pains] == ["a", "a", "b", "b"]


def test_quote_verification_flags_invented_quotes(fake_provider_cls):
    _, report = run(fake_provider_cls)
    verified = {p.id: p.quote_verified for p in report.pains}
    assert verified == {"P001": True, "P002": False, "P003": True, "P004": True}


def test_clustering_drops_unknown_ids_dedupes_and_keeps_leftovers(fake_provider_cls):
    _, report = run(fake_provider_cls)
    by_title = {t.title: t for t in report.themes}
    assert by_title["No-shows"].pain_ids == ["P003", "P001"]
    assert by_title["Visibility"].pain_ids == ["P004"]
    assert by_title["Other pains"].pain_ids == ["P002"]  # never assigned by the model
    assert sum(len(t.pain_ids) for t in report.themes) == len(report.pains)


def test_themes_are_ranked_by_evidence(fake_provider_cls):
    _, report = run(fake_provider_cls)
    first = report.themes[0]
    assert first.title == "No-shows" and first.id == "T1"
    assert first.source_count == 2 and first.mention_count == 2
    assert first.avg_severity == 4.5


def test_opportunities_scored_sorted_and_validated(fake_provider_cls):
    _, report = run(fake_provider_cls)
    assert [o.title for o in report.opportunities] == ["High score", "Low score"]
    top = report.opportunities[0]
    assert top.id == "O1" and top.score == 10.0
    assert top.theme_ids == ["T1"]  # unknown T42 removed


def test_stories_trace_back_to_pains(fake_provider_cls):
    provider, report = run(fake_provider_cls)
    assert len(report.stories) == 1
    story = report.stories[0]
    assert story.id == "US01" and story.opportunity_id == "O1"
    assert story.pain_ids == ["P003", "P001"]
    story_call = next(c for c in provider.calls if c["step"] == "stories:O1")
    assert "Patients don't show up" in story_call["prompt"]  # evidence was sent


def test_invalid_output_is_retried_with_feedback(fake_provider_cls):
    responses = scripted()
    responses["cluster"] = [{"themes": [{"title": "missing fields"}]}, responses["cluster"]]
    provider, report = run(fake_provider_cls, responses)
    cluster_calls = [c for c in provider.calls if c["step"] == "cluster"]
    assert len(cluster_calls) == 2
    assert "previous answer was invalid" in cluster_calls[1]["prompt"]
    assert report.themes


def test_language_rule_reaches_system_prompt(fake_provider_cls):
    provider, _ = run(fake_provider_cls, language="Brazilian Portuguese")
    assert all("Brazilian Portuguese" in c["system"] for c in provider.calls)


def test_chunk_text_splits_on_paragraphs():
    text = "\n\n".join(["x" * 40] * 10)
    chunks = chunk_text(text, max_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_quote_matching_tolerates_quotes_whitespace_and_ellipsis():
    source = "I said: “It’s   slow.” Then later, much later, it broke completely."
    assert quote_in_text("it's slow", source)
    assert quote_in_text("Then later... it broke completely", source)
    assert not quote_in_text("It is fast", source)
