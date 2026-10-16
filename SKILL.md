---
name: github-actions-docs
description: Generate complete Markdown documentation for a repository's `.github` folder - one document per GitHub Actions workflow and per local action (composite, JavaScript or Docker), plus an index README. Each doc explains what it does, its triggers, local and external dependencies, configuration (inputs, secrets, variables, permissions), configuration examples, a Mermaid dependency graph and a Mermaid sequence diagram. Use this skill whenever the user wants to document, describe, map, explain, audit or diagram GitHub Actions, workflows, reusable workflows, composite actions, CI/CD pipelines or anything under `.github/workflows` or `.github/actions`, even if they don't say "documentation" or "skill" (e.g. "what do our pipelines do?", "draw the workflow dependencies", "write docs for our CI", "generate a README for .github").
---

# GitHub Actions documentation generator

Turns the `.github` folder of the current repository into a browsable documentation set:

```
<doc-dir>/                      default: docs/github-automation/
├── README.md                   index + repo-wide dependency map + cross-cutting notes
├── workflows/<name>.md         one per workflow file
└── actions/<name>.md           one per local action (action.yml / action.yaml)
```

The work is split on purpose. A script does what must be exact (parse every YAML file, resolve local
`uses:` references, build the graph, pre-draw Mermaid flowcharts). You do what needs understanding (what a
workflow is *for*, how a run unfolds, what a reader needs to configure it). Don't re-derive structure by hand
when the inventory has it, and don't paraphrase the YAML when you can explain the intent.

`<skill-dir>` below means the directory containing this SKILL.md. Run from inside the target repository.
The skill only reads `.github/` – it never edits workflows or actions.

## Workflow

### 1. Scan

```bash
python3 <skill-dir>/scripts/scan_github.py --list --out /tmp/gha-inventory.json
```

Needs PyYAML (`pip install pyyaml` if the script says it is missing). `--list` prints every workflow/action with
its triggers and target doc path, plus warnings (broken local references, unparsable files, unknown `needs`).
No `.github` found → tell the user and stop. Nothing to document → say so; don't produce empty docs.

Choose the output directory: use the one the user named, otherwise `docs/github-automation/`. If it already
contains docs, you are *updating* them (see "Regeneration" below). Mention the directory you chose in your
final message; don't interrupt the user to ask unless the choice is genuinely ambiguous.

The inventory JSON is large. Don't dump it into context. Per item, fetch just what you need:

```bash
python3 <skill-dir>/scripts/scan_github.py --item .github/workflows/ci.yml
```

The shape of an item: `type`, `file`, `name`, `triggers`, `jobs[]` (with `needs`, `steps[]`, `uses`),
`call_interface` / `dispatch_inputs`, action `inputs`/`outputs`/`steps`, `external_dependencies[]`,
`depends_on`, `used_by`, `context_refs` (secrets/vars/inputs names), `dependency_graph`, `job_graph`,
`doc_file`.

### 2. Understand each item

For every workflow and action: read the item's inventory entry **and** the source YAML (comments carry intent
the parser drops), plus any repo scripts it invokes (`./scripts/deploy.sh`, `make ci`, …) when they exist – a
step that says `run: ./scripts/deploy.sh` is only understood by reading the script. For callers, look at
`used_by` items to see how inputs are really passed; those become your examples.

Process dependencies before dependents when it helps (a reusable workflow or composite action before the
things that call it) so descriptions stay consistent. In large repos (> ~15 items) work in batches and write
each doc as soon as it's understood rather than reading everything first.

### 3. Write the docs

Read `references/doc-templates.md` for the exact section structure, writing principles and the mapping from
inventory fields to sections. Then for each item write `<doc-dir>/<doc_file>`.

Every document must cover these things (they are the point of the skill):

1. **What it does** – purpose and outcome, in plain language.
2. **Dependencies** – local (linked to their docs) and external (version + pinning).
3. **How it is triggered** – events with filters and cron in words; for actions, who calls them and how.
4. **How it is configured** – inputs, secrets, variables, env, permissions, runners.
5. **Configuration examples** – real ones from the repo first, labelled with source.
6. **Dependency graph** – start from the inventory's `dependency_graph`. For a local action with no incoming callers (`used_by`) and no outgoing dependencies (`depends_on` or `external_dependencies`), keep the `## Dependency graph` section but a Mermaid flowchart is optional. Instead, write an explicit `Not applicable: this action has no dependencies or callers.` line. This exception applies only when both sides are empty; an unused action can still have outgoing dependencies and must show them. All other items must include the graph.
7. **Sequence diagram** – written by you; see `references/mermaid-guide.md`. Skip only with an explicit
   `Not applicable: <reason>` line (rules for skipping are in the guide). Prefer including it for multi-job
   workflows, anything calling other workflows/actions, and composite actions with ≥ 3 steps.

Facts you can't verify from the repo (what a secret holds, what an environment's approval rules are, what an
external service does) are stated as unknown or hedged, never guessed. Secrets: names only, never values.

### 4. Write the index

`<doc-dir>/README.md` per the index template: repo-wide dependency flowchart (`repo_graph` in the inventory), tables
linking every workflow and action with a one-line summary, and cross-cutting notes (actions not pinned to a
SHA, secrets/variables used across the repo, unused local actions, scanner warnings, other `.github` files).

### 5. Validate and fix

```bash
python3 <skill-dir>/scripts/validate_docs.py --inventory /tmp/gha-inventory.json --docs <doc-dir> --mermaid
```

It checks: every item has a doc, required sections exist, skippable diagrams say `Not applicable:`, Mermaid blocks
are well-formed (and parse with the real Mermaid parser when node/npm are available), links resolve, the index
links every doc, no stale docs. Fix everything it reports and re-run until it prints `OK`. If `--mermaid` can't
run (no node/npm/network) the structural checks still apply; mention that diagrams were not parser-checked.

### 6. Report

Finish with a short summary: how many workflows/actions documented and where, the notable findings (broken
references, unpinned or branch-pinned external actions, secrets used but undeclared, unused actions) and anything
you were unable to determine. Don't repeat the docs' contents.

## Regeneration

If docs already exist, regenerate them from the current source – don't append. Keep human-written content:
anything between `<!-- manual:start -->` and `<!-- manual:end -->` is copied verbatim into the new version of the
same doc. Delete docs for workflows/actions that no longer exist only after telling the user which ones.

## Scope and edge cases

- **Local analysis only.** External actions (`owner/repo@ref`) are listed with version and pinning but not
  fetched or described beyond what their name and usage make evident.
- **Local reusable workflows** (`uses: ./.github/workflows/x.yml`) get their own doc; callers link to it and
  document the inputs/secrets they pass.
- **Actions outside `.github/actions`** are found anywhere under `.github/`; a repo-root `action.yml` is
  included too.
- **Unparsable YAML**: the scanner records an `error`. Still create the doc, state that the file could not be
  parsed and why, and document what's visible from reading the raw file.
- **Broken or out-of-tree local references** appear in `warnings`; mention them in the affected doc's
  "Notes and caveats" and in the index.
- **Event chaining** via `workflow_run` is exact; `gh workflow run` detection is a heuristic (the edge has
  `heuristic: true`) – say "appears to dispatch" for those.
- **Dynamic references** (`uses: ${{ ... }}`, generated workflows, `repository_dispatch`) can't be resolved;
  note them where you see them.
- Documentation language follows the user's language; keep YAML keys, event names and code in English.
