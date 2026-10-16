#!/usr/bin/env python3
"""Validate generated GitHub Actions documentation against the scanner inventory.

Checks (deterministic, no network unless --mermaid is used):
  * every workflow / action in the inventory has its doc file
  * each doc has the required sections for its type
  * every ```mermaid block is closed, starts with a known diagram type and a
    sequenceDiagram has participants and at least one message
  * sections that may be skipped say "Not applicable:" explicitly
  * relative links resolve; the index README links every doc
  * docs that no longer match an inventory item are reported as stale

Optional --mermaid: parse every block with the real Mermaid parser (needs node
and npm; installs mermaid + jsdom once into ~/.cache/github-actions-docs-mermaid).

Usage:
    python validate_docs.py --inventory /tmp/gha-inventory.json --docs docs/github-automation [--mermaid]
Exit code 0 = clean, 1 = problems found.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED = {
    "workflow": ["Overview", "Triggers", "Dependencies", "Configuration", "Jobs", "Sequence diagram", "Examples"],
    "action": ["Overview", "Usage", "Inputs", "Outputs", "Dependencies", "Examples", "Sequence diagram"],
}
DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram", "erDiagram", "gantt", "journey", "timeline")
FENCE_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
ARROW_RE = re.compile(r"(->>|-->>|->|-->|-x|--x|-\)|--\))")


def headings(text: str) -> dict[str, str]:
    """Map heading title -> section body (up to the next heading of same or higher level)."""
    out = {}
    matches = list(HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        end = len(text)
        for n in matches[i + 1:]:
            if len(n.group(1)) <= level:
                end = n.start()
                break
        out[m.group(2).strip()] = text[m.end():end]
    return out


def check_mermaid_block(code: str) -> list[str]:
    problems = []
    lines = [l for l in code.splitlines() if l.strip() and not l.strip().startswith("%%")]
    if not lines:
        return ["empty mermaid block"]
    first = lines[0].strip()
    if not first.startswith(DIAGRAM_TYPES):
        problems.append(f"unknown diagram type on first line: '{first[:40]}'")
    if first.startswith("sequenceDiagram"):
        body = "\n".join(lines[1:])
        if not re.search(r"^\s*(participant|actor)\s", body, re.M):
            problems.append("sequenceDiagram declares no participants (declare them explicitly with aliases)")
        if not ARROW_RE.search(body):
            problems.append("sequenceDiagram has no messages")
        opens = len(re.findall(r"^\s*(alt|opt|loop|par|critical|break|rect)\b", body, re.M))
        ends = len(re.findall(r"^\s*end\s*$", body, re.M))
        if opens != ends:
            problems.append(f"unbalanced blocks: {opens} opening (alt/opt/loop/par/...) vs {ends} 'end'")
    return problems


def run_real_parser(blocks: list[dict]) -> list[str]:
    if not shutil.which("node") or not shutil.which("npm"):
        return ["--mermaid requested but node/npm not found; skipped real parser check (not a failure of the docs)"]
    cache = Path.home() / ".cache" / "github-actions-docs-mermaid"
    cache.mkdir(parents=True, exist_ok=True)
    if not (cache / "node_modules" / "mermaid").exists():
        print("Installing mermaid + jsdom into", cache, "(one-time)...", file=sys.stderr)
        (cache / "package.json").write_text('{"name":"gha-docs-mermaid","private":true,"type":"module"}')
        r = subprocess.run(["npm", "install", "--no-audit", "--no-fund", "mermaid@10", "jsdom"], cwd=cache, capture_output=True, text=True)
        if r.returncode != 0:
            return ["could not install mermaid parser (" + r.stderr.strip()[:200] + "); skipped real parser check"]
    shutil.copy(Path(__file__).with_name("check_mermaid.mjs"), cache / "check_mermaid.mjs")
    (cache / "blocks.json").write_text(json.dumps(blocks))
    r = subprocess.run(["node", "check_mermaid.mjs", "blocks.json"], cwd=cache, capture_output=True, text=True)
    return [l[5:].strip() for l in r.stdout.splitlines() if l.startswith("FAIL")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--docs", required=True, help="documentation output directory (contains README.md)")
    ap.add_argument("--mermaid", action="store_true", help="also parse diagrams with the real Mermaid parser")
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    docs = Path(args.docs)
    problems: list[str] = []
    all_blocks: list[dict] = []

    if not docs.is_dir():
        print(f"Docs directory not found: {docs}")
        return 1

    expected = set()
    for item in inv["items"]:
        rel = item["doc_file"]
        expected.add(rel)
        path = docs / rel
        tag = f"{rel}"
        if not path.is_file():
            problems.append(f"{tag}: missing (for {item['file']})")
            continue
        text = path.read_text(encoding="utf-8")
        secs = headings(text)
        for req in REQUIRED[item["type"]]:
            if not any(h == req or h.startswith(req) for h in secs):
                problems.append(f"{tag}: missing section '## {req}'")
        # skippable diagrams must be explicit
        for name in ("Sequence diagram",):
            body = next((b for h, b in secs.items() if h.startswith(name)), None)
            if body is not None and "```mermaid" not in body and "Not applicable:" not in body:
                problems.append(f"{tag}: '{name}' has neither a mermaid diagram nor a 'Not applicable: <reason>' line")
        dep = next((b for h, b in secs.items() if h.startswith("Dependency graph")), None)
        if dep is None:
            dep_parent = next((b for h, b in secs.items() if h.startswith("Dependencies")), "")
            dep = dep_parent
        if "```mermaid" not in dep and "Not applicable:" not in dep:
            problems.append(f"{tag}: Dependencies section needs a dependency graph or 'Not applicable: <reason>'")
        if "<!-- manual:start -->" in text and "<!-- manual:end -->" not in text:
            problems.append(f"{tag}: manual:start marker without manual:end")
        if text.count("```") % 2:
            problems.append(f"{tag}: unbalanced ``` code fences")
        for i, m in enumerate(FENCE_RE.finditer(text), 1):
            for p in check_mermaid_block(m.group(1)):
                problems.append(f"{tag}: mermaid block #{i}: {p}")
            all_blocks.append({"label": f"{tag}#{i}", "code": m.group(1)})
        for link in LINK_RE.findall(text):
            if re.match(r"^[a-z]+:", link) or link.startswith("#"):
                continue
            if not (path.parent / link).resolve().exists():
                problems.append(f"{tag}: broken relative link '{link}'")
        if item.get("error"):
            if "parse" not in text.lower() and "error" not in text.lower():
                problems.append(f"{tag}: source file failed to parse ({item['error'][:60]}) but the doc does not mention it")

    readme = docs / "README.md"
    if not readme.is_file():
        problems.append("README.md: missing index")
    else:
        rt = readme.read_text(encoding="utf-8")
        for rel in sorted(expected):
            if rel not in rt:
                problems.append(f"README.md: does not link to {rel}")
        for link in LINK_RE.findall(rt):
            if not re.match(r"^[a-z]+:", link) and not link.startswith("#") and not (docs / link).resolve().exists():
                problems.append(f"README.md: broken relative link '{link}'")
        for i, m in enumerate(FENCE_RE.finditer(rt), 1):
            for p in check_mermaid_block(m.group(1)):
                problems.append(f"README.md: mermaid block #{i}: {p}")
            all_blocks.append({"label": f"README.md#{i}", "code": m.group(1)})

    for sub in ("workflows", "actions"):
        d = docs / sub
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                if f"{sub}/{f.name}" not in expected:
                    problems.append(f"{sub}/{f.name}: stale - no matching workflow/action in the inventory")

    if args.mermaid and all_blocks:
        for msg in run_real_parser(all_blocks):
            problems.append(f"mermaid parser: {msg}")

    n = len(inv["items"])
    if problems:
        print(f"{len(problems)} problem(s) found across {n} item(s):")
        for p in problems:
            print(" -", p)
        return 1
    print(f"OK: {n} item(s) documented, {len(all_blocks)} mermaid block(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
