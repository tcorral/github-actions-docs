# Promptfoo end-to-end evaluation

These tests run the **actual** `github-actions-docs` Claude Code skill on the fixture taken from the supplied example repository. The source `.github` workflows/actions and the generated documentation are retained under `fixtures/example/`; each execution starts with the source inputs, not the reference output. The generated docs are not used as an exact-text golden snapshot: the assertions check coverage, key source facts, dependencies, Markdown links, required headings and diagrams.

## Run

Requirements: Node.js 20+, `claude` CLI authenticated with access to a model, Python 3 with `pyyaml`, and Promptfoo. These tests invoke Claude Code in a **temporary directory** with `--dangerously-skip-permissions`; run only with trusted fixtures in an isolated environment, not with untrusted pull requests or secrets. The API/model call may incur cost.

```bash
python3 -m pip install pyyaml
npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache
npx promptfoo@latest view
```

Run from the root of this skill repository. The provider loads this checkout of the skill by symlinking it into `.claude/skills/` of the test repository. Set `SKILL_EVAL_TIMEOUT_MS` for the per-case CLI timeout (default 600000). `SKILL_EVAL_KEEP_WORKDIR=1` retains working copies for debugging. Three cases cover default output, alternate output directory and preserving existing `manual:start`/`manual:end` sections during regeneration. Failing assertions include the exact missing property.

Promptfoo stores its own run metadata/results locally. No credentials, tokens or real Slack webhooks are included in the fixture. The original generated docs are retained as examples, not provided to the running agent, to avoid leaking reference answers into the test input.

## Evaluation scope

- **End-to-end model behavior:** Claude reads the skill and fixture and writes docs; assertions inspect the written Markdown rather than its final chat response.
- **Deterministic contract:** checks all five workflows, four local actions, index coverage, Mermaid blocks, important triggers, dependency links, matrix and configuration names, known dangling action reference and manual-section preservation.
- **Not measured:** prose quality, actual deployment behavior, whether Mermaid parses in a browser, or semantic factual completeness beyond asserted facts. Run `scripts/validate_docs.py --mermaid` separately for more exhaustive structural/parser validation.
