# Documentation templates

Use these structures exactly: the validator (`scripts/validate_docs.py`) looks for the `##` section names, and
a consistent shape makes the docs scannable across dozens of files. Anything in `<angle brackets>` is for you to
fill in; delete helper comments. Every doc lives at `<doc-dir>/<doc_file>` (the `doc_file` field of the inventory).

Contents: [Writing principles](#writing-principles) · [Workflow template](#workflow-template) ·
[Action template](#action-template) · [Index README template](#index-readme-template) ·
[Where each section's data comes from](#where-each-sections-data-comes-from)

## Writing principles

- **Explain intent, not syntax.** "Runs the test matrix on every PR and blocks merge on failure" beats "Has a job
  named test that runs on a matrix". Get intent from the job/step names, comments, the scripts in `run:` blocks and
  the scripts they call (read them when they are in the repo).
- **Never invent.** If something can't be determined from the repo (what a secret contains, what an external
  service does), say so: "Not determinable from the repository". A wrong doc is worse than a short one.
- **Secrets: names only.** Document that `DEPLOY_KEY` is needed and what for, never a value.
- **Link generously**, relatively: to other generated docs (use their `doc_file`), to the source file, and to the
  Marketplace page for external actions as plain text `owner/repo` (do not fabricate URLs beyond
  `https://github.com/<owner>/<repo>`).
- **Real examples first.** Prefer an example lifted from how the repo actually calls the workflow/action, labelled
  with its source. Add a minimal synthetic example only when no real caller exists, and label it "Example (illustrative)".
- Keep tables for enumerable facts (inputs, triggers, secrets); use prose for behaviour.
- Preserve human edits: if the doc file already exists and contains `<!-- manual:start -->` … `<!-- manual:end -->`,
  copy that block verbatim into the regenerated file.

## Workflow template

````markdown
# <Workflow name>

> **Source:** [`<file>`](<relative path from the doc to the repo file>) · **Type:** Workflow
> **Triggers:** <comma-separated events, e.g. push, pull_request, schedule> · **Called by:** <links or "nothing – top-level workflow">

## Overview

<2–5 sentences: what it does, why it exists, what it produces/changes (artifacts, releases, deployments, comments,
status checks). Mention if it is a reusable workflow meant to be called by others.>

## Triggers

| Event | When it fires | Filters / details |
|-------|---------------|-------------------|
| `push` | <plain-language> | branches: `main`; tags: `v*.*.*` |

<Add: schedule cron in words ("daily at 02:00 UTC"), workflow_dispatch inputs → see Configuration, workflow_run
upstream workflow(s) as links, concurrency behaviour (cancel-in-progress or queue).>

## Dependencies

### Local dependencies
| Kind | Name | Used by | Purpose |
|------|------|---------|---------|
| Composite action | [Setup project](../actions/setup-project.md) | job `test` | <why> |
| Reusable workflow | [Lint](_lint.md) | job `lint` | <why> |
| Triggered after | [Release](release.md) | `workflow_run` | <why> |

<If none: "None – this workflow only uses external actions and inline scripts.">

### External actions
| Action | Version | Pinning | Used in |
|--------|---------|---------|---------|
| `actions/checkout` | `v4` | major tag | all jobs |

<Pinning values: sha / tag / major-tag / branch. Add a note when something is pinned to a branch
(`@master`, `@main`) – that is a supply-chain risk worth flagging in one sentence.>

### Dependency graph

<Paste `dependency_graph.mermaid` from the inventory in a ```mermaid fence, refined if needed, followed by its
`legend` as an italic line. If the item has no local or external dependencies and nobody uses it, write
`Not applicable: <reason>` instead.>

## Configuration

### Inputs
<workflow_dispatch / workflow_call inputs: table of Name | Type | Required | Default | Description.
"None" if there are none.>

### Secrets and variables
| Name | Kind | Used for | Where |
|------|------|----------|-------|
| `CODECOV_TOKEN` | secret | uploading coverage | job `test` |

<Include `vars.*`. Mention `GITHUB_TOKEN` permissions here as well, from the workflow/job `permissions:` blocks
(explain what the granted scopes allow, and if no `permissions:` is set, that repo defaults apply).>

### Environment variables, runners and other settings
<`env:` blocks, `runs-on` labels, `environment:` (and that it may require approvals), timeouts, matrix dimensions,
services/containers. Table or short list.>

### Outputs
<workflow_call outputs, or "None".>

## Jobs

<If `job_graph` exists, paste it in a ```mermaid fence with its legend.>

| Job | Runs on | Needs | Condition | What it does |
|-----|---------|-------|-----------|--------------|
| `test` | ubuntu-latest, windows-latest (matrix) | `lint` | – | <purpose, key steps> |

<Optionally a short subsection per complex job (3+ meaningful steps, non-obvious conditions, scripts with logic).>

## Sequence diagram

<A ```mermaid sequenceDiagram showing the run from trigger to completion – see references/mermaid-guide.md.
If it adds nothing (a single job with a couple of trivial steps), write: `Not applicable: <one-line reason>`.>

## Examples

<Configuration examples: how to trigger it manually (`gh workflow run …` with inputs), how to call it from another
workflow (for workflow_call), how to set the required secrets/variables (`gh secret set NAME`), and a real
snippet from a caller. Label each: "From `<file>`" or "(illustrative)".>

## Notes and caveats

<Only non-obvious things: ordering constraints, known gotchas visible in the code, missing/broken references
reported by the scanner, unpinned or branch-pinned actions, secrets referenced but not declared, permissions that
look broader than needed. Omit the section content ("None noted.") rather than padding.>

<!-- manual:start -->
<!-- manual:end -->
````

## Action template

````markdown
# <Action name>

> **Source:** [`<file>`](<relative path>) · **Type:** <Composite | JavaScript | Docker> action
> **Used by:** <links to workflows/actions, or "not referenced by any local workflow">

## Overview

<2–5 sentences: what it does and why it is factored out. Include the `description` from action.yml only if it
adds something.>

## Usage

<How it is triggered: actions have no events – they run when a workflow step says `uses: ./<dir>`. Show the
minimal invocation, and list the real call sites as a table: Caller | Job/step | Inputs passed.>

```yaml
- uses: ./.github/actions/<dir>
  with:
    <input>: <value>
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|

<"None" when the action takes no inputs.>

## Outputs

| Name | Description | Value comes from |
|------|-------------|------------------|

<"None" when the action has no outputs.>

## Dependencies

### Local dependencies
<Other local actions (links). "None" if none.>

### External actions and tools
<Table as in the workflow template for composite steps. For JavaScript actions: entrypoint (`main`/`pre`/`post`)
and node version. For Docker actions: image/Dockerfile and entrypoint. Mention tools the shell steps assume
(npm, jq, gh, docker…).>

### Dependency graph

<As in the workflow template. `Not applicable: <reason>` when it has no dependencies and no callers.>

## Configuration

<Things that influence behaviour beyond inputs: required environment variables, runner OS assumptions (e.g.
`shell: bash`), required permissions, caches and their keys, secrets it expects the caller to pass as inputs.>

## Sequence diagram

<Composite actions with ≥3 steps or any interaction with other actions/services: a sequenceDiagram with the
caller job, the action, its steps/nested actions and external systems. JS/Docker actions: describe the
interaction if the source is available, otherwise `Not applicable: <reason>`.>

## Examples

<Real call sites first (copied from the repo, labelled), then an illustrative example showing optional inputs.>

## Notes and caveats

<As in the workflow template.>

<!-- manual:start -->
<!-- manual:end -->
````

## Index README template

````markdown
# GitHub automation documentation

_Generated from `.github/` on <date>. <N> workflows · <M> actions. Regenerate with the `github-actions-docs` skill._

## How it fits together

<Paste `repo_graph.mermaid` from the inventory in a ```mermaid fence, followed by its `legend` (it already thins
itself out above 40 nodes). If `repo_graph` is null (no item depends on another), write `Not applicable: no local
dependencies between workflows and actions`.>

## Workflows

| Workflow | Triggers | Summary |
|----------|----------|---------|
| [CI](workflows/ci.md) | push, pull_request | <one line> |

## Actions

| Action | Type | Used by | Summary |
|--------|------|---------|---------|
| [Setup project](actions/setup-project.md) | composite | CI, Release | <one line> |

## Cross-cutting notes

- **External actions not pinned to a commit SHA:** <list from `summary.external_not_sha_pinned`, or "none">
- **Secrets and variables used across the repo:** <deduplicated names with the items using them>
- **Unused local actions:** <actions with empty `used_by`>
- **Problems found while scanning:** <inventory `warnings`, or "none">
- **Other files in `.github/` (not documented here):** <`other_files`, e.g. CODEOWNERS, dependabot.yml>
````

## Where each section's data comes from

| Doc section | Inventory fields (see `scan_github.py`) | Plus reading |
|-------------|------------------------------------------|--------------|
| Triggers | `triggers`, `concurrency` | cron → words; branch filters |
| Local dependencies | `depends_on`, `used_by`, `edges[].kind/via` | – |
| External actions | `external_dependencies[].versions/pins/used_in` | – |
| Dependency graph | `dependency_graph.mermaid/legend` | refine labels if useful |
| Inputs / Outputs | `call_interface`, `dispatch_inputs`, action `inputs`/`outputs` | – |
| Secrets & variables | `context_refs.secrets/vars`, `call_interface.secrets`, job `secrets` | find which job uses each |
| Jobs | `jobs[]` (`needs`, `runs_on`, `if`, `strategy`, `environment`, `steps`) | `job_graph` |
| Sequence diagram | `jobs[].steps[]`, `edges` | scripts invoked by `run:` steps |
| Examples | callers' `with:` / `secrets:` in `jobs[].with`, `steps[].with` | – |
