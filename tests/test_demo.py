"""End-to-end run of the bundled example through demo mode (no API key needed)."""

import json

from discovery_agent.cli import DEMO_CONTEXT, main
from discovery_agent.pipeline import load_sources, run_discovery
from discovery_agent.providers import EXAMPLES_DIR, DemoProvider
from discovery_agent.report import to_markdown


def demo_report():
    sources = load_sources([EXAMPLES_DIR / "interviews"])
    return run_discovery(sources, DemoProvider(), context=DEMO_CONTEXT)


def test_demo_report_is_complete_and_traceable():
    report = demo_report()
    assert len(report.sources) == 6
    assert report.pains and report.themes and report.opportunities and report.stories
    # every quote in the demo is a real, verbatim quote
    assert all(p.quote_verified for p in report.pains)
    # every pain is in exactly one theme
    ids = [pid for t in report.themes for pid in t.pain_ids]
    assert sorted(ids) == sorted(p.id for p in report.pains)
    # every story points to an existing opportunity and existing pains
    for story in report.stories:
        assert report.opportunity(story.opportunity_id)
        assert story.pain_ids and all(report.pain(pid) for pid in story.pain_ids)
        assert len(story.acceptance_criteria) >= 2


def test_markdown_contains_all_sections():
    md = to_markdown(demo_report())
    for heading in ["## Opportunities (ranked)", "## User stories", "## Themes and evidence", "```mermaid", "```gherkin"]:
        assert heading in md


def test_cli_demo_writes_files(tmp_path, capsys):
    out, js = tmp_path / "r.md", tmp_path / "r.json"
    assert main(["demo", "--out", str(out), "--json", str(js)]) == 0
    assert out.read_text().startswith("# Discovery report")
    assert json.loads(js.read_text())["stories"]


def test_cli_reports_missing_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    code = main(["run", str(EXAMPLES_DIR / "interviews"), "--provider", "claude"])
    assert code == 1
    assert "Error" in capsys.readouterr().err
