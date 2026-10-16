#!/usr/bin/env python3
"""Inventory the `.github` folder of a repository.

Finds GitHub Actions workflows and local (composite / JS / Docker) actions,
parses them into structured data, resolves *local* dependencies between them
and pre-computes Mermaid dependency graphs. The output is meant to be read by
Claude, which then writes the human-facing documentation.

Usage:
    python scan_github.py --list                       # compact overview
    python scan_github.py --out /tmp/gha-inventory.json  # full inventory
    python scan_github.py --item .github/workflows/ci.yml   # one item as JSON

Requires PyYAML (pip install pyyaml). Read-only: never modifies the repo.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("PyYAML is required. Install it with: pip install pyyaml\n")
    sys.exit(2)

YAML_EXT = (".yml", ".yaml")
ACTION_FILES = ("action.yml", "action.yaml")
RUN_LIMIT = 1500  # chars of a `run:` script kept in the inventory
MAX_GRAPH_NODES = 40

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAJOR_RE = re.compile(r"^v?\d+$")
SEMVER_RE = re.compile(r"^v?\d+\.\d+(\.\d+)?([-+].*)?$")
CTX_PATTERNS = {
    "secrets": re.compile(r"\bsecrets\.([A-Za-z_][\w-]*)"),
    "vars": re.compile(r"\bvars\.([A-Za-z_][\w-]*)"),
    "inputs": re.compile(r"\binputs\.([A-Za-z_][\w-]*)"),
}
GH_DISPATCH_RE = re.compile(r"gh\s+workflow\s+run\s+[\"']?([^\s\"']+)")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_yaml(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}, None
    except Exception as exc:  # noqa: BLE001 - report any parse problem
        return None, f"{type(exc).__name__}: {exc}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def ctx_refs(text: str) -> dict:
    return {k: sorted(set(p.findall(text))) for k, p in CTX_PATTERNS.items()}


def pin_kind(version: str | None) -> str:
    if not version:
        return "none"
    if SHA_RE.match(version):
        return "sha"
    if MAJOR_RE.match(version):
        return "major-tag"  # floating tag such as v4
    if SEMVER_RE.match(version):
        return "tag"
    return "branch"


def normalize_on(on) -> dict:
    if on is None:
        return {}
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(e): {} for e in on}
    if isinstance(on, dict):
        return {str(k): (v if v is not None else {}) for k, v in on.items()}
    return {}


def classify_uses(ref, repo_root: Path, job_level: bool = False) -> dict:
    ref = str(ref).strip()
    info: dict = {"ref": ref}
    if ref.startswith("docker://"):
        info["kind"] = "docker"
        return info
    if ref.startswith("./") or ref.startswith("../"):
        rel = ref[2:] if ref.startswith("./") else ref
        target = repo_root / rel
        info["kind"] = "local-workflow" if job_level else "local-action"
        resolved = None
        if target.is_file():
            resolved = target
        elif target.is_dir():
            for name in ACTION_FILES:
                if (target / name).is_file():
                    resolved = target / name
                    break
        info["resolved"] = resolved is not None
        info["target"] = rel_posix(resolved, repo_root) if resolved else None
        return info
    path, _, version = ref.partition("@")
    info["name"] = path
    info["version"] = version or None
    info["pin"] = pin_kind(version)
    info["kind"] = "external-workflow" if "/.github/workflows/" in path else "external-action"
    return info


def parse_step(step, idx: int, repo_root: Path) -> dict:
    if not isinstance(step, dict):
        return {"index": idx, "raw": step}
    s: dict = {"index": idx}
    for out, inn in (
        ("id", "id"),
        ("name", "name"),
        ("if", "if"),
        ("shell", "shell"),
        ("working_directory", "working-directory"),
        ("continue_on_error", "continue-on-error"),
        ("timeout_minutes", "timeout-minutes"),
    ):
        if inn in step:
            s[out] = step[inn]
    if "uses" in step:
        s["uses"] = classify_uses(step["uses"], repo_root)
        if step.get("with"):
            s["with"] = step["with"]
    if "run" in step:
        run = str(step["run"])
        s["run"] = run if len(run) <= RUN_LIMIT else run[:RUN_LIMIT] + "\n# ... truncated"
        s["run_truncated"] = len(run) > RUN_LIMIT
    if step.get("env"):
        s["env"] = step["env"]
    return s


def parse_job(jid: str, job, repo_root: Path) -> dict:
    if not isinstance(job, dict):
        return {"id": jid, "raw": job}
    needs = job.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    j: dict = {"id": jid, "name": job.get("name"), "needs": needs}
    for out, inn in (
        ("runs_on", "runs-on"),
        ("if", "if"),
        ("environment", "environment"),
        ("permissions", "permissions"),
        ("concurrency", "concurrency"),
        ("timeout_minutes", "timeout-minutes"),
        ("continue_on_error", "continue-on-error"),
        ("strategy", "strategy"),
        ("container", "container"),
        ("outputs", "outputs"),
        ("env", "env"),
        ("defaults", "defaults"),
    ):
        if inn in job:
            j[out] = job[inn]
    if isinstance(job.get("services"), dict):
        j["services"] = {
            k: (v.get("image") if isinstance(v, dict) else v) for k, v in job["services"].items()
        }
    if "uses" in job:
        j["uses"] = classify_uses(job["uses"], repo_root, job_level=True)
        if "with" in job:
            j["with"] = job["with"]
        if "secrets" in job:
            j["secrets"] = job["secrets"]
    j["steps"] = [parse_step(s, i + 1, repo_root) for i, s in enumerate(job.get("steps") or [])]
    return j


def parse_workflow(path: Path, repo_root: Path) -> dict:
    rel = rel_posix(path, repo_root)
    item: dict = {"id": f"workflow:{rel}", "type": "workflow", "file": rel}
    item["context_refs"] = ctx_refs(read_text(path))
    data, err = load_yaml(path)
    if err or not isinstance(data, dict):
        item["name"] = path.stem
        item["error"] = err or "top level of the file is not a mapping"
        return item
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    triggers = normalize_on(data.get("on", data.get(True)))
    item.update(
        name=data.get("name") or path.stem,
        has_explicit_name=bool(data.get("name")),
        run_name=data.get("run-name"),
        triggers=triggers,
        permissions=data.get("permissions"),
        env=data.get("env"),
        concurrency=data.get("concurrency"),
        defaults=data.get("defaults"),
    )
    wc = triggers.get("workflow_call")
    if isinstance(wc, dict):
        item["call_interface"] = {
            "inputs": wc.get("inputs") or {},
            "secrets": wc.get("secrets") or {},
            "outputs": wc.get("outputs") or {},
        }
    wd = triggers.get("workflow_dispatch")
    if isinstance(wd, dict):
        item["dispatch_inputs"] = wd.get("inputs") or {}
    jobs = data.get("jobs") or {}
    item["jobs"] = [parse_job(str(k), v, repo_root) for k, v in jobs.items()] if isinstance(jobs, dict) else []
    return item


def parse_action(path: Path, repo_root: Path) -> dict:
    rel = rel_posix(path, repo_root)
    dir_rel = rel_posix(path.parent, repo_root)
    item: dict = {"id": f"action:{rel}", "type": "action", "file": rel, "dir": dir_rel}
    item["context_refs"] = ctx_refs(read_text(path))
    data, err = load_yaml(path)
    if err or not isinstance(data, dict):
        item["name"] = path.parent.name
        item["error"] = err or "top level of the file is not a mapping"
        return item
    runs = data.get("runs") or {}
    using = str(runs.get("using", "")).strip()
    if using == "composite":
        kind = "composite"
    elif using == "docker":
        kind = "docker"
    elif using.startswith("node"):
        kind = "javascript"
    else:
        kind = "unknown"
    item.update(
        name=data.get("name") or path.parent.name,
        description=data.get("description"),
        author=data.get("author"),
        inputs=data.get("inputs") or {},
        outputs=data.get("outputs") or {},
        branding=data.get("branding"),
        runs_using=using,
        action_kind=kind,
    )
    if kind == "composite":
        item["steps"] = [parse_step(s, i + 1, repo_root) for i, s in enumerate(runs.get("steps") or [])]
    elif kind == "docker":
        item["docker"] = {k: runs.get(k) for k in ("image", "args", "entrypoint", "env") if runs.get(k)}
    elif kind == "javascript":
        item["javascript"] = {k: runs.get(k) for k in ("main", "pre", "post") if runs.get(k)}
    return item


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
def find_repo_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / ".github").is_dir():
            return candidate
    return None


def action_slug(dir_rel: str) -> str:
    d = dir_rel
    if d.startswith(".github/actions/"):
        d = d[len(".github/actions/"):]
    elif d in ("", "."):
        return "root-action"
    return d.strip("/").replace("/", "--").lstrip(".")


def discover(repo_root: Path, gh_dir: Path):
    wf_dir = gh_dir / "workflows"
    workflows = sorted(p for p in wf_dir.glob("*") if p.is_file() and p.suffix in YAML_EXT) if wf_dir.is_dir() else []
    actions = sorted(p for p in gh_dir.rglob("*") if p.is_file() and p.name in ACTION_FILES)
    for name in ACTION_FILES:  # a root-level action (`uses: ./`)
        if (repo_root / name).is_file():
            actions.append(repo_root / name)
    claimed = set(workflows) | set(actions)
    others = sorted(
        rel_posix(p, repo_root) for p in gh_dir.rglob("*") if p.is_file() and p not in claimed
    )
    return workflows, actions, others


# --------------------------------------------------------------------------
# graph construction
# --------------------------------------------------------------------------
def iter_steps(item: dict):
    """Yield (location_label, step) for every step in a workflow or action."""
    if item["type"] == "workflow":
        for job in item.get("jobs", []):
            for step in job.get("steps", []):
                yield f"{job['id']}", step
    else:
        for step in item.get("steps", []):
            yield "steps", step


def build_edges(items: list[dict], warnings: list[str]):
    by_id = {i["id"]: i for i in items}
    wf_by_file = {Path(i["file"]).name: i for i in items if i["type"] == "workflow"}
    wf_by_name = {i["name"]: i for i in items if i["type"] == "workflow"}
    agg: dict = {}

    def add(frm, to, kind, via, heuristic=False):
        key = (frm, to, kind)
        e = agg.setdefault(key, {"from": frm, "to": to, "kind": kind, "via": [], "heuristic": heuristic})
        if via and via not in e["via"]:
            e["via"].append(via)

    for item in items:
        ext: dict = {}

        def note_local(uses, via):
            if not uses.get("resolved"):
                warnings.append(f"{item['file']}: local reference '{uses['ref']}' ({via}) does not resolve to a file")
                return None
            target = uses["target"]
            tid = ("workflow:" if uses["kind"] == "local-workflow" else "action:") + target
            if tid not in by_id:
                warnings.append(f"{item['file']}: '{uses['ref']}' points to {target}, which is outside the scanned .github folder")
                return None
            return tid

        def note_ext(uses, via):
            d = ext.setdefault(
                uses["name"],
                {"name": uses["name"], "kind": uses["kind"], "versions": [], "pins": [], "used_in": []},
            )
            if uses.get("version") and uses["version"] not in d["versions"]:
                d["versions"].append(uses["version"])
            if uses.get("pin") and uses["pin"] not in d["pins"]:
                d["pins"].append(uses["pin"])
            if via not in d["used_in"]:
                d["used_in"].append(via)

        # job-level reusable workflow calls
        for job in item.get("jobs", []):
            u = job.get("uses")
            if u:
                via = f"job {job['id']}"
                if u["kind"] == "local-workflow":
                    tid = note_local(u, via)
                    if tid:
                        add(item["id"], tid, "calls-workflow", job["id"])
                elif u["kind"].startswith("external"):
                    note_ext(u, via)
            for n in job.get("needs", []):
                if n not in {j["id"] for j in item["jobs"]}:
                    warnings.append(f"{item['file']}: job '{job['id']}' needs unknown job '{n}'")

        # step-level uses + gh workflow run heuristics
        for loc, step in iter_steps(item):
            u = step.get("uses")
            label = f"{loc}" if loc == "steps" else f"{loc}"
            if u:
                via = f"{loc}: {step.get('name') or step.get('id') or u['ref']}"
                if u["kind"] == "local-action":
                    tid = note_local(u, via)
                    if tid:
                        if loc == "steps":
                            label = str(step.get("id") or step.get("name") or f"step {step['index']}")
                        add(item["id"], tid, "uses-action", label)
                elif u["kind"].startswith("external"):
                    note_ext(u, via)
            run = step.get("run")
            if run:
                for m in GH_DISPATCH_RE.finditer(run):
                    ref = m.group(1)
                    target = wf_by_file.get(Path(ref).name) or wf_by_name.get(ref)
                    if target and target["id"] != item["id"]:
                        add(item["id"], target["id"], "dispatches", f"{loc} (gh workflow run)", heuristic=True)

        # workflow_run chaining
        wr = (item.get("triggers") or {}).get("workflow_run")
        if isinstance(wr, dict):
            for name in wr.get("workflows") or []:
                target = wf_by_name.get(name) or wf_by_file.get(name)
                if target:
                    types = ",".join(wr.get("types") or [])
                    add(item["id"], target["id"], "triggered-after", f"workflow_run{' ' + types if types else ''}")
                else:
                    warnings.append(f"{item['file']}: workflow_run references unknown workflow '{name}'")

        item["external_dependencies"] = sorted(ext.values(), key=lambda d: d["name"])

    edges = list(agg.values())
    for e in edges:
        if e["kind"] == "dispatches":
            tgt = by_id[e["to"]]
            if "workflow_dispatch" not in (tgt.get("triggers") or {}):
                warnings.append(
                    f"{by_id[e['from']]['file']}: appears to dispatch {tgt['file']} with `gh workflow run`, "
                    f"but that workflow has no `workflow_dispatch` trigger, so the call would be rejected"
                )
    out_edges: dict = {}
    in_edges: dict = {}
    for e in edges:
        out_edges.setdefault(e["from"], []).append(e)
        in_edges.setdefault(e["to"], []).append(e)
    for item in items:
        item["depends_on"] = sorted({e["to"] for e in out_edges.get(item["id"], [])})
        item["used_by"] = sorted({e["from"] for e in in_edges.get(item["id"], [])})
    return edges, out_edges, in_edges


# --------------------------------------------------------------------------
# Mermaid
# --------------------------------------------------------------------------
def mm(s) -> str:
    return str(s).replace('"', "'").replace("\n", " ").replace("|", "/")


def node_label(item: dict) -> str:
    if item["type"] == "workflow":
        base = Path(item["file"]).name
        return f"Workflow: {mm(item['name'])}<br/>{mm(base)}" if item["name"] != Path(item["file"]).stem else f"Workflow: {mm(base)}"
    d = item["dir"] if item["dir"] != "." else "(repo root)"
    return f"Action: {mm(item['name'])}<br/>{mm(d)}"


def edge_line(a: str, b: str, e: dict, by_id: dict) -> str:
    vias = e["via"]
    text = mm(", ".join(vias[:3]) + (f" +{len(vias) - 3}" if len(vias) > 3 else ""))
    if e["kind"] == "calls-workflow":
        return f'  {a} ==>|"job: {text}"| {b}'
    if e["kind"] == "uses-action":
        unit = "job" if by_id[e["from"]]["type"] == "workflow" else "step"
        return f'  {a} -->|"{unit}: {text}"| {b}'
    return f'  {a} -.->|"{text}"| {b}'


COMPOSITION = ("calls-workflow", "uses-action")


def closure(start: str, edges: dict, key: str, by_id: dict):
    """Transitive walk over composition edges only (reusable workflows / actions).

    Event chaining (workflow_run, gh workflow run) is deliberately not followed:
    it describes *when* something runs, not what it is made of, and following it
    drags unrelated pipelines into the graph.
    """
    seen = {start}
    q = deque([start])
    truncated = False
    while q:
        cur = q.popleft()
        for e in edges.get(cur, []):
            if e["kind"] not in COMPOSITION:
                continue
            nxt = e[key]
            if nxt in seen or nxt not in by_id:
                continue
            if len(seen) >= MAX_GRAPH_NODES:
                truncated = True
                continue
            seen.add(nxt)
            q.append(nxt)
    return seen, truncated


def build_dependency_graph(item: dict, by_id: dict, edges: list, out_edges: dict, in_edges: dict):
    down, t1 = closure(item["id"], out_edges, "to", by_id)
    up, t2 = closure(item["id"], in_edges, "from", by_id)
    event_nodes = set()
    for e in out_edges.get(item["id"], []) + in_edges.get(item["id"], []):
        if e["kind"] not in COMPOSITION:
            event_nodes.add(e["from"])
            event_nodes.add(e["to"])
    nodes = (down | up | event_nodes) & set(by_id)
    ext_names: dict = {}
    ext_src = down
    unique_ext = {d["name"] for n in down for d in by_id[n].get("external_dependencies", [])}
    if len(nodes) + len(unique_ext) > MAX_GRAPH_NODES:
        ext_src = {item["id"]}
    for n in ext_src:
        for d in by_id[n].get("external_dependencies", []):
            ext_names.setdefault(d["name"], {"versions": set(), "from": set()})
            ext_names[d["name"]]["versions"].update(d["versions"])
            ext_names[d["name"]]["from"].add(n)
    local_edges = [e for e in edges if e["from"] in nodes and e["to"] in nodes]
    if not local_edges and not ext_names:
        return None
    ids = {n: f"n{i}" for i, n in enumerate(sorted(nodes, key=lambda x: (x != item["id"], x)))}
    lines = ["flowchart LR"]
    for n, nid in ids.items():
        cls = "focus" if n == item["id"] else ("wf" if by_id[n]["type"] == "workflow" else "act")
        lines.append(f'  {nid}["{node_label(by_id[n])}"]:::{cls}')
    ext_ids = {}
    for i, (name, d) in enumerate(sorted(ext_names.items())):
        eid = f"x{i}"
        ext_ids[name] = eid
        vs = "/".join(sorted(v[:12] for v in d["versions"])) if d["versions"] else ""
        label = mm(name) + (f"<br/>@{mm(vs)}" if vs else "")
        lines.append(f'  {eid}(["{label}"]):::ext')
    for e in local_edges:
        lines.append(edge_line(ids[e["from"]], ids[e["to"]], e, by_id))
    for name, d in sorted(ext_names.items()):
        for src in sorted(d["from"]):
            lines.append(f"  {ids[src]} --> {ext_ids[name]}")
    lines += [
        "  classDef focus fill:#1f6feb,stroke:#0b3d91,color:#ffffff",
        "  classDef wf fill:#ddf4ff,stroke:#0969da,color:#0a3069",
        "  classDef act fill:#dafbe1,stroke:#1a7f37,color:#0f5323",
        "  classDef ext fill:#f6f8fa,stroke:#8c959f,color:#24292f,stroke-dasharray: 4 3",
    ]
    return {
        "mermaid": "\n".join(lines),
        "truncated": t1 or t2,
        "legend": "Arrows point from the caller to what it depends on. Thick = reusable workflow call, "
        "thin = local action, dotted = event chaining (workflow_run / gh workflow run), "
        "dashed box = external action.",
    }


def build_job_graph(item: dict):
    jobs = item.get("jobs") or []
    if len(jobs) < 2 and not any(j.get("needs") for j in jobs):
        return None
    ids = {j["id"]: f"j{i}" for i, j in enumerate(jobs)}
    trig = ", ".join(item.get("triggers", {}).keys()) or "trigger"
    lines = ["flowchart LR", f'  t(["on: {mm(trig)}"]):::trig']
    for j in jobs:
        label = mm(j["id"]) + (f"<br/>{mm(j['name'])}" if j.get("name") and j["name"] != j["id"] else "")
        shape = ("[[", "]]") if j.get("uses") else ("[", "]")
        lines.append(f'  {ids[j["id"]]}{shape[0]}"{label}"{shape[1]}')
    for j in jobs:
        needs = [n for n in j.get("needs", []) if n in ids]
        if not needs:
            lines.append(f"  t --> {ids[j['id']]}")
        for n in needs:
            lines.append(f"  {ids[n]} --> {ids[j['id']]}")
    lines.append("  classDef trig fill:#fff8c5,stroke:#9a6700,color:#4d2d00")
    return {
        "mermaid": "\n".join(lines),
        "legend": "Arrows follow `needs:` (run order). Double-bordered boxes call a reusable workflow.",
    }


def build_repo_graph(items: list[dict], edges: list[dict]):
    """One flowchart for the whole repo (used by the index README)."""
    by_id = {i["id"]: i for i in items if not i.get("error")}
    keep = set(by_id)
    note = None
    if len(keep) > MAX_GRAPH_NODES:
        uses = {}
        for e in edges:
            uses[e["to"]] = uses.get(e["to"], 0) + 1
        keep = {i for i, it in by_id.items() if it["type"] == "workflow" or uses.get(i, 0) >= 2}
        note = "Large repository: showing all workflows plus actions used by two or more items."
    edges = [e for e in edges if e["from"] in keep and e["to"] in keep]
    connected = {e["from"] for e in edges} | {e["to"] for e in edges}
    if not edges:
        return None
    ids = {n: f"n{i}" for i, n in enumerate(sorted(n for n in keep if n in connected or by_id[n]["type"] == "workflow"))}
    lines = ["flowchart LR"]
    for n, nid in ids.items():
        lines.append(f'  {nid}["{node_label(by_id[n])}"]:::{"wf" if by_id[n]["type"] == "workflow" else "act"}')
    for e in edges:
        lines.append(edge_line(ids[e["from"]], ids[e["to"]], e, by_id))
    lines += [
        "  classDef wf fill:#ddf4ff,stroke:#0969da,color:#0a3069",
        "  classDef act fill:#dafbe1,stroke:#1a7f37,color:#0f5323",
    ]
    legend = ("Arrows point from the caller to what it depends on. Thick = reusable workflow call, thin = local action, "
              "dotted = event chaining (workflow_run / gh workflow run). External actions are omitted.")
    return {"mermaid": "\n".join(lines), "legend": legend + (" " + note if note else "")}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="repository root (default: nearest parent of cwd containing .github)")
    ap.add_argument("--out", help="write the full JSON inventory to this file")
    ap.add_argument("--list", action="store_true", help="print a compact overview table")
    ap.add_argument("--item", help="print one item (match on file path or id) as JSON")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else find_repo_root(Path.cwd())
    if not root or not (root / ".github").is_dir():
        sys.stderr.write("No .github folder found. Run from inside the repository or pass --root.\n")
        return 1
    gh_dir = root / ".github"

    workflows, actions, others = discover(repo_root=root, gh_dir=gh_dir)
    items = [parse_workflow(p, root) for p in workflows] + [parse_action(p, root) for p in actions]
    warnings: list[str] = []
    for it in items:
        if it.get("error"):
            warnings.append(f"{it['file']}: could not be parsed ({it['error']})")
        it["doc_file"] = (
            f"workflows/{Path(it['file']).stem}.md" if it["type"] == "workflow" else f"actions/{action_slug(it['dir'])}.md"
        )
    slug_seen: dict = {}
    for it in items:  # guard against slug collisions (e.g. ci.yml and ci.yaml)
        if it["doc_file"] in slug_seen:
            it["doc_file"] = it["doc_file"][:-3] + f"-{Path(it['file']).suffix.lstrip('.')}.md"
        slug_seen[it["doc_file"]] = True

    edges, out_edges, in_edges = build_edges(items, warnings)
    by_id = {i["id"]: i for i in items}
    for it in items:
        if it.get("error"):
            continue
        g = build_dependency_graph(it, by_id, edges, out_edges, in_edges)
        if g:
            it["dependency_graph"] = g
        if it["type"] == "workflow":
            jg = build_job_graph(it)
            if jg:
                it["job_graph"] = jg

    all_ext = {d["name"]: d for it in items for d in it.get("external_dependencies", [])}
    unpinned = sorted(
        {d["name"] for it in items for d in it.get("external_dependencies", []) if d["kind"] == "external-action" and "sha" not in d["pins"]}
    )
    inventory = {
        "repo_root": str(root),
        "github_dir": ".github",
        "summary": {
            "workflows": sum(1 for i in items if i["type"] == "workflow"),
            "actions": sum(1 for i in items if i["type"] == "action"),
            "local_edges": len(edges),
            "external_actions": len(all_ext),
            "external_not_sha_pinned": unpinned,
        },
        "repo_graph": build_repo_graph(items, edges),
        "items": items,
        "edges": edges,
        "other_files": others,
        "warnings": warnings,
    }

    if args.item:
        needle = args.item.strip()
        match = [i for i in items if i["file"] == needle or i["id"] == needle or i["id"].endswith(needle)]
        if not match:
            sys.stderr.write(f"No item matching '{needle}'. Use --list to see available items.\n")
            return 1
        json.dump(match[0], sys.stdout, indent=2, default=str)
        print()
        return 0

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(inventory, indent=2, default=str), encoding="utf-8")
        sys.stderr.write(f"Inventory written to {args.out}\n")

    if args.list or not args.out:
        s = inventory["summary"]
        print(f"Repo: {root}")
        print(f"Workflows: {s['workflows']}  Actions: {s['actions']}  Local edges: {s['local_edges']}  External actions: {s['external_actions']}")
        print()
        for it in items:
            trig = ",".join((it.get("triggers") or {}).keys()) if it["type"] == "workflow" else it.get("action_kind", "")
            print(f"{it['type']:<9} {it['file']:<55} {it['name'][:30]:<30} {trig}  -> {it['doc_file']}")
        if others:
            print(f"\nOther files in .github: {len(others)}")
        for w in warnings:
            print(f"WARNING: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
