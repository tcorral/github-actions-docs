# github-actions-docs

A [Claude Code](https://claude.com/product/claude-code) skill that reads the `.github` folder of a repository and generates
Markdown documentation for every GitHub Actions **workflow** and **local action**, complete with Mermaid dependency
graphs and sequence diagrams.

Point it at a repository and ask *"document our GitHub Actions"*. You get one document per workflow or action, plus an
index that shows how everything fits together.

## What you get

```
docs/github-automation/
├── README.md                  index, repo-wide dependency map, cross-cutting notes
├── workflows/
│   ├── ci.md                  one document per workflow file
│   └── release.md
└── actions/
    └── setup-project.md       one document per local action
```

Every document covers:

| Section | Content |
|---------|---------|
| **Overview** | What it does and why it exists, in plain language rather than a restatement of the YAML |
| **Triggers** / **Usage** | Events with their filters, cron schedules in words, concurrency; for actions, who calls them and how |
| **Dependencies** | Local workflows and actions (linked to their own docs) and external actions with version and pinning (SHA, tag, floating major tag or branch) |
| **Dependency graph** | Mermaid flowchart showing what it calls and what calls it |
| **Configuration** | Inputs, outputs, secrets, variables, environment, permissions, runners, matrix |
| **Jobs** | Table of jobs with `needs`, conditions and purpose, plus a Mermaid job graph |
| **Sequence diagram** | Mermaid sequence diagram of a run from trigger to completion (or an explicit `Not applicable: <reason>`) |
| **Examples** | Real call sites from your repository first, then illustrative snippets, such as `gh workflow run` and `gh secret set` |
| **Notes and caveats** | Broken references, unpinned actions, secrets used but not declared, and other findings |

### Example output

Dependency graph generated for a composite action (arrows point from caller to dependency):

```mermaid
flowchart LR
  n0["Action: Setup project<br/>.github/actions/setup-project"]:::focus
  n1["Action: Cache dependencies<br/>.github/actions/cache-deps"]:::act
  n2["Workflow: CI<br/>ci.yml"]:::wf
  n3["Workflow: Release<br/>release.yml"]:::wf
  x0(["actions/cache<br/>@v4"]):::ext
  x1(["actions/setup-node<br/>@v4"]):::ext
  n2 -->|"job: test"| n0
  n3 -->|"job: build"| n0
  n0 -->|"step: deps"| n1
  n1 --> x0
  n0 --> x1
  classDef focus fill:#1f6feb,stroke:#0b3d91,color:#ffffff
  classDef wf fill:#ddf4ff,stroke:#0969da,color:#0a3069
  classDef act fill:#dafbe1,stroke:#1a7f37,color:#0f5323
  classDef ext fill:#f6f8fa,stroke:#8c959f,color:#24292f,stroke-dasharray: 4 3
```

Sequence diagram for a pull-request CI workflow:

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant GH as GitHub
    participant Lint as Lint (reusable)
    participant Test as test job (matrix)
    participant Setup as setup-project
    participant Notify as notify job

    Dev->>GH: push to main or open/update PR
    GH->>Lint: call _lint.yml (python 3.12, secrets inherited)
    Lint-->>GH: lint result
    GH->>Test: start after lint succeeds
    loop each OS x Node version (4 runs)
        Test->>Setup: node-version from matrix
        Setup-->>Test: Node installed, deps cached and installed
        Test->>Test: npm test with coverage
    end
    opt a job failed and ref is main
        GH->>Notify: post failure to Slack
    end
```

## Requirements

- [Claude Code](https://claude.com/product/claude-code)
- Python 3 and [PyYAML](https://pypi.org/project/pyyaml/) (`pip install pyyaml`)
- *Optional:* Node.js and npm, used by the validator to check diagrams with the real Mermaid parser. It installs `mermaid` and `jsdom` once into `~/.cache/github-actions-docs-mermaid`.

## Installation

Clone this repository into your Claude Code skills folder.

**Personal skill, available in every project:**

```bash
git clone https://github.com/tcorral/github-actions-docs ~/.claude/skills/github-actions-docs
```

**Project skill, shared with your team through the repository you want to document:**

```bash
git clone https://github.com/tcorral/github-actions-docs .claude/skills/github-actions-docs
```

If you received a `github-actions-docs.skill` package instead, unzip it into one of the same locations.

## Usage

Open Claude Code **inside the repository that contains the `.github` folder** and ask in your own words:

> Document our GitHub Actions workflows and actions.

> Generate docs for `.github` with dependency graphs and sequence diagrams.

> Explain what our CI pipelines do and how they depend on each other.

Output goes to `docs/github-automation/` unless you name another folder (*"…write the docs to `docs/ci/`"*).

The skill only **reads** `.github/`. It never modifies your workflows or actions.

### Regenerating

Run it again at any time. Documents are regenerated from the current source rather than appended to. Anything you
write between these markers is preserved verbatim:

```markdown
<!-- manual:start -->
Your own notes, runbooks, links…
<!-- manual:end -->
```

## How it works

The work is split between deterministic scripts and Claude:

1. **Scan** (`scripts/scan_github.py`): parses every workflow and local action, resolves local `uses:` references,
   detects `workflow_run` chaining and `gh workflow run` calls, and pre-computes Mermaid flowcharts. Output is a
   JSON inventory. The same input always gives the same structure.
2. **Understand and write** (Claude): reads the inventory *and* the source YAML, comments and scripts that steps call, then
   writes the prose, configuration examples and sequence diagrams using the templates in `references/`.
3. **Validate** (`scripts/validate_docs.py`): checks that every workflow and action has a document with the
   required sections, that links resolve, that the index links everything and that Mermaid blocks are well-formed.
   With `--mermaid` it also parses them with the real Mermaid parser.

### Using the scripts directly

```bash
# Overview of everything found, with warnings
python3 scripts/scan_github.py --list

# Full JSON inventory
python3 scripts/scan_github.py --out /tmp/gha-inventory.json

# One workflow or action as JSON
python3 scripts/scan_github.py --item .github/workflows/ci.yml

# Validate generated docs (add --mermaid for the real parser)
python3 scripts/validate_docs.py --inventory /tmp/gha-inventory.json --docs docs/github-automation --mermaid
```

Run these from inside the repository, or pass `--root /path/to/repo` to the scanner.

### What the scanner warns about

- Local `uses: ./…` references that do not resolve to a file
- `needs:` pointing at a job that does not exist
- `gh workflow run x.yml` where `x.yml` has no `workflow_dispatch` trigger
- `workflow_run` pointing at an unknown workflow
- YAML files that fail to parse (the document is still created and says so)
- External actions that are not pinned to a commit SHA (summarised in the index)

## Repository layout

```
github-actions-docs/
├── SKILL.md                   instructions Claude follows (entry point of the skill)
├── README.md                  this file
├── scripts/
│   ├── scan_github.py         inventory + dependency graphs
│   ├── validate_docs.py       completeness and diagram checks
│   └── check_mermaid.mjs      Mermaid parser used by --mermaid
└── references/
    ├── doc-templates.md       document structure and writing principles
    └── mermaid-guide.md       diagram conventions, safe syntax, sequence-diagram patterns
```

## Scope and limitations

- **Local analysis only.** External actions (`owner/repo@ref`) are listed with version and pinning status. They are not fetched or analysed.
- **`gh workflow run` detection is heuristic.** Such edges are drawn dotted, and the docs say "appears to dispatch".
- **Dynamic references** (`uses: ${{ … }}`), generated workflows and `repository_dispatch` chains cannot be resolved statically.
- **Things that live outside the repository**, such as environment protection rules, secret values and organisation-level policies, are not visible. The docs mark them as unknown instead of guessing.
- **Behaviour of repo scripts and JavaScript or Docker action sources** is only documented when the files are available to read.
- `.github` files other than workflows and actions (`CODEOWNERS`, `dependabot.yml`, issue templates…) are listed in the index but not documented.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `PyYAML is required` | `pip install pyyaml` |
| `No .github folder found` | Run Claude Code from inside the repository, or use `--root` with the scripts |
| `--mermaid` is skipped | Install Node.js and npm, or ignore: the structural checks still run |
| A workflow's doc says it could not be parsed | Fix the YAML error shown in the scanner warning, then regenerate |
| Skill does not trigger | Check that `SKILL.md` is at `~/.claude/skills/github-actions-docs/SKILL.md` (or the project-level equivalent), then restart Claude Code |

## Contributing

Issues and pull requests are welcome. When changing the scanner, test it on a repository that exercises reusable
workflows, nested composite actions, `workflow_run` chains and at least one broken reference, then confirm that
`validate_docs.py --mermaid` passes on the generated docs.

## License

See [LICENSE](LICENSE).