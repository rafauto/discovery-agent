# Discovery Agent — notes for Claude

Python agent that turns interview transcripts into pains → themes → opportunities → user stories.

- Code lives in `src/discovery_agent/` (schemas, prompts, providers, pipeline, report, cli). UI in `app.py` (Streamlit).
- Rule of thumb: the LLM makes judgement calls; IDs, counts, scores and traceability are computed in `pipeline.py`.
- Every provider implements `generate(step, system, prompt, schema)`. Step keys (`extract:<source>:<chunk>`, `cluster`, `opportunities`, `stories:<opp id>`) are also the keys of `examples/demo_fixtures.json`.
- Run tests: `pytest -q` (no network, providers mocked). Eval: `python evals/run_eval.py`.
- If you change the example interviews or the step keys, regenerate the demo fixtures and `examples/output/`.
- Everything user-facing is in English. Keep examples fictional.
