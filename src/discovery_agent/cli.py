"""Command line interface.

Examples::

    discovery-agent demo
    discovery-agent run examples/interviews --context "Scheduling app for clinics"
    discovery-agent run notes.md --provider gemini --out report.md --json report.json
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .pipeline import DEFAULT_LANGUAGE, load_sources, run_discovery
from .providers import EXAMPLES_DIR, ProviderError, RecordingProvider, get_provider
from .report import to_markdown

DEMO_CONTEXT = (
    "ClinicFlow, a fictional SaaS for small private clinics (dental, physio, dermatology) "
    "to manage appointments. Users: receptionists, clinic owners and patients."
)


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so we don't need an extra dependency."""
    env = Path(path)
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _progress(message: str, fraction: float) -> None:
    print(f"[{fraction:4.0%}] {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discovery-agent",
        description="Turn interview transcripts and user feedback into pains, "
        "opportunities and user stories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Analyse your own transcripts (.txt/.md files or folders).")
    run.add_argument("paths", nargs="+", help="Files or folders with transcripts.")
    run.add_argument("--provider", default=os.getenv("DISCOVERY_PROVIDER", "claude"),
                     choices=["claude", "gemini", "ollama", "demo"])
    run.add_argument("--model", default=None, help="Override the provider's default model.")
    run.add_argument("--context", default="", help="One or two sentences about the product.")
    run.add_argument("--language", default=DEFAULT_LANGUAGE, help="Output language, e.g. 'English'.")
    run.add_argument("--top", type=int, default=3, help="Opportunities that get user stories.")
    run.add_argument("--stories", type=int, default=2, help="Stories per opportunity.")
    run.add_argument("--out", default="discovery_report.md", help="Markdown output path.")
    run.add_argument("--json", dest="json_out", default=None, help="Optional JSON output path.")
    run.add_argument("--record", default=None,
                     help="Save raw model responses to this file (used to build demo fixtures).")

    demo = sub.add_parser("demo", help="Run the bundled example without an API key.")
    demo.add_argument("--out", default="discovery_report.md")
    demo.add_argument("--json", dest="json_out", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    try:
        if args.command == "demo":
            provider = get_provider("demo")
            sources = load_sources([EXAMPLES_DIR / "interviews"])
            report = run_discovery(sources, provider, context=DEMO_CONTEXT, progress=_progress)
        else:
            provider = get_provider(args.provider, model=args.model)
            if args.record:
                provider = RecordingProvider(provider, args.record)
            sources = load_sources(args.paths)
            report = run_discovery(
                sources, provider, context=args.context, language=args.language,
                top_n=args.top, stories_per_opportunity=args.stories, progress=_progress,
            )
    except (ProviderError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    Path(args.out).write_text(to_markdown(report), encoding="utf-8")
    print(f"Report written to {args.out}", file=sys.stderr)
    if args.json_out:
        Path(args.json_out).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"JSON written to {args.json_out}", file=sys.stderr)
    print(
        f"{len(report.pains)} pains · {len(report.themes)} themes · "
        f"{len(report.opportunities)} opportunities · {len(report.stories)} stories",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
