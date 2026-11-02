# Contributing

Thanks for your interest in Discovery Agent! Issues, ideas and pull requests are welcome.

## Reporting a problem or suggesting an idea

Open an [issue](https://github.com/rafauto/discovery-agent/issues) and include:

- what you tried (command or steps in the web UI)
- what you expected and what happened instead
- the provider you used (`claude`, `gemini`, `ollama` or `demo`)

**Never paste real interview transcripts, personal data or API keys in issues.** Use fictional or anonymised examples.

## Setting up for development

```bash
git clone https://github.com/rafauto/discovery-agent.git
cd discovery-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,gemini,dev]"
pytest -q
```

## Making a change

1. Create a branch from `main`: `git checkout -b feat/short-description`
2. Keep the change focused and add or update tests in `tests/`.
3. Run `pytest -q` and `python evals/run_eval.py` before opening the pull request.
4. If you change the example interviews or the pipeline step keys, regenerate
   `examples/demo_fixtures.json` (use `--record`) and the files in `examples/output/`.
5. Open a pull request describing **what** changed and **why**.

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use for |
|---|---|
| `feat:` | a new feature |
| `fix:` | a bug fix |
| `docs:` | documentation only |
| `test:` | adding or fixing tests |
| `refactor:` | code changes that don't change behaviour |
| `chore:` | tooling, dependencies, CI |

Example: `feat: export user stories to CSV`

## Guiding principles

- **Evidence first:** every pain must keep a verbatim quote from the source.
- **The LLM judges, the code counts:** IDs, counts, scores and traceability stay in `pipeline.py`, not in prompts.
- **Provider-agnostic:** new features must work with every provider through `generate(step, system, prompt, schema)`.
- Everything user-facing is in English, and all examples are fictional.
