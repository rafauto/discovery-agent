"""Tiny evaluation for the discovery agent.

Measures, on the bundled example interviews:

* theme recall      - share of expected problem areas found in the themes
* quote precision   - share of pains whose quote exists verbatim in the source
* story quality     - stories with >= 2 acceptance criteria and traceable evidence

Usage:
    python evals/run_eval.py                      # demo mode (no key)
    python evals/run_eval.py --provider claude    # real run
    python evals/run_eval.py --provider gemini
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from discovery_agent.cli import DEMO_CONTEXT, load_dotenv  # noqa: E402
from discovery_agent.pipeline import load_sources, run_discovery  # noqa: E402
from discovery_agent.providers import get_provider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="demo")
    parser.add_argument("--model", default=None)
    parser.add_argument("--min-recall", type=float, default=0.8)
    args = parser.parse_args()

    load_dotenv(str(ROOT / ".env"))
    expected = json.loads((ROOT / "evals" / "expected_themes.json").read_text())["expected"]
    sources = load_sources([ROOT / "examples" / "interviews"])
    report = run_discovery(sources, get_provider(args.provider, args.model), context=DEMO_CONTEXT)

    themes_text = [
        " ".join([t.title, t.description] + [report.pain(pid).statement for pid in t.pain_ids]).lower()
        for t in report.themes
    ]
    found = []
    for item in expected:
        hit = any(any(k.lower() in txt for k in item["keywords"]) for txt in themes_text)
        found.append(hit)
        print(f"  {'✓' if hit else '✗'} {item['area']}")

    recall = sum(found) / len(found)
    precision = sum(p.quote_verified for p in report.pains) / max(len(report.pains), 1)
    good_stories = sum(len(s.acceptance_criteria) >= 2 and bool(s.pain_ids) for s in report.stories)

    print(f"\nProvider:         {report.provider}")
    print(f"Theme recall:     {recall:.0%} ({sum(found)}/{len(found)})")
    print(f"Quote precision:  {precision:.0%} ({len(report.pains)} pains)")
    print(f"Well-formed stories: {good_stories}/{len(report.stories)}")
    return 0 if recall >= args.min_recall and precision >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
