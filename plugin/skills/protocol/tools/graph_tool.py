#!/usr/bin/env python3
"""graph_tool.py — protocol-as-code for the graph plugin (D26).

Runs the mechanical parts of the graph-context protocol so that Claude executes them instead of
re-deriving them from prose. Read-only: validate, check, handover-tables (incl. --verify), lint-prose, lint-handover,
hydrate --dry-run, backlog. Writing: hydrate (current_node), fold, split, set-status, add-edge, set-current, add-node, add-doc, add-code,
set-next, set-issue, close.

Usage (run from the project root that holds dependency_graph.json):
  graph_tool.py validate                      R1 + schema (schema needs `jsonschema`; degrades with a warning)
  graph_tool.py hydrate <node_id>             hop 0-2 subgraph, components, files, re-examine, capabilities,
                                              staleness (timestamp + content), blast radius; sets current_node
  graph_tool.py check                         growth / fold candidates, staleness (both layers)
  graph_tool.py handover-tables               Markdown for handover §2 (components+subgraph), §6 lines, §7 table
  graph_tool.py fold <victim> <survivor>      apply a fold, then validate
  graph_tool.py split <node> <child>=<id,id,...> [...]   create function children, move attachments, validate
  graph_tool.py set-status <node> <PLANNED|IN_PROGRESS|BLOCKED|DONE|none>   change wip_status, validate
  graph_tool.py backlog [--owner user|claude] [--next-only] [--component C] [--all]
                                              graph-wide Backlog view (D33): open issues (filtered; default = config.backlog_filter),
                                              PLANNED / IN_PROGRESS / BLOCKED / next nodes; excluded issues counted per component
  graph_tool.py set-next <node> [--off]       set or clear the `next` flag, validate
  graph_tool.py set-issue <issue> [--owner user|claude] [--trigger TEXT]   set owner / trigger of an issue, validate
  graph_tool.py close <issue> <resolved|transferred> --by <decision-id|commit|text>
                                              close an issue; when --by names a decision node, also add <decision>.resolves -> <issue>
  graph_tool.py add-edge <src> <kind> <dst>   add one edge (part_of|depends_on|affects|resolves|supersedes), validate
  graph_tool.py set-current <node|null>       set current_node, validate
  graph_tool.py add-node <id> <type> "<name>" [--part-of P] [--doc PATH ...] [--code PATH ...] [--source-ref ID]
                     [--status S] [--next] [--owner user|claude] [--trigger TEXT]   (issue nodes get issue_status open)
                                              create a node (the last hand-edit of the JSON), validate
  graph_tool.py handover-tables --verify <handover.md>
                                              check that the pasted §2/§6/§7 blocks in a handover equal current output (R9)
  graph_tool.py lint-prose                    version strings and D-ranges in SKILL.md / README / delegates vs plugin.json and the register
  graph_tool.py lint-handover <handover.md> [--prev <previous.md>]
                                              free-text cross-checks: §5 names current_node, §4 resolved ids absent from table,
                                              with --prev: every U-id of the previous §4 is still a row or named resolved/transferred,
                                              §1 mentions commits since the footer HEAD, no empty free-text cell on flagged rows,
                                              exactly one footer, Generated stamp present
  graph_tool.py add-doc <node> <path>  /  add-code <node> <path>   append to docs / code_targets, validate
  graph_tool.py hydrate --dry-run <node>      same output, no current_node write
Options: --graph PATH (default dependency_graph.json). --lang ja|en may be given before or after the sub-command;
default = config.interaction_language. Tables stay English; proposal sentences follow --lang.
Every write is appended to <dir of handover_path>/graph_tool.log; every run ends with a footer line
`<!-- graph_tool <cmd> @<git head> graph md5 <before>[ -> <after> (WRITTEN)] -->`.
Exit code: 0 ok, 1 = validation errors or bad usage.
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys
from collections import Counter, defaultdict

EDGES = ("part_of", "depends_on", "affects", "resolves", "supersedes")
WIP = ("PLANNED", "IN_PROGRESS", "BLOCKED", "DONE")
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.normpath(os.path.join(HERE, "..", "schema", "graph_schema.json"))
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

MSG = {
    "growth": {"en": "Proposal: split `{n}` — {c} attached decisions/issues (threshold {t}).",
               "ja": "提案: `{n}` の分割 — 付属する decision/issue が {c} 件（しきい値 {t}）。"},
    "fold": {"en": "Proposal: fold `{v}` into `{s}` ({why}).",
             "ja": "提案: `{v}` を `{s}` に畳み込む（{why}）。"},
    "none": {"en": "No proposals.", "ja": "提案はありません。"},
    "stale": {"en": "Stale: {n} — {what}.", "ja": "更新忘れ: {n} — {what}。"},
}

# ---------------------------------------------------------------- io
def load(path):
    with open(path) as f:
        return json.load(f)

def save(path, g):
    with open(path, "w") as f:
        json.dump(g, f, indent=2, ensure_ascii=False)
        f.write("\n")

class WriteRefused(Exception):
    """Raised by guarded_save: the graph would be invalid, nothing was written (U31, plan integrity-store P2)."""

def guarded_save(path, g):
    """Validate first, save only when valid (R1 + schema + entity hashes + view drift)."""
    problems, _ = validate(g, drift=False)
    if problems:
        raise WriteRefused(problems)
    save(path, g)
    for v in g.get("config", {}).get("views", []):  # P3: views are regenerated on every accepted write, never by hand
        want = render_view(g, v["kind"])
        if not os.path.exists(v["path"]) or open(v["path"], encoding="utf-8").read() != want:
            os.makedirs(os.path.dirname(v["path"]) or ".", exist_ok=True); open(v["path"], "w", encoding="utf-8").write(want)

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()[:12]

def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "-"
    except Exception:
        return "-"

def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None

def newer(a, b):
    """True when timestamp a is strictly newer than b (both ISO strings, seconds precision, tz-aware or naive)."""
    da, db = parse_ts(a), parse_ts(b)
    if not da or not db:
        return False
    if da.tzinfo is None: da = da.astimezone()
    if db.tzinfo is None: db = db.astimezone()
    return da > db

def log_path(g):
    hp = g.get("config", {}).get("handover_path", ".context/WIP_HANDOVER.md")
    return os.path.join(os.path.dirname(hp) or ".", "graph_tool.log")

def log_op(g, line, graph_path="dependency_graph.json", before=None):
    lp = log_path(g)
    os.makedirs(os.path.dirname(lp) or ".", exist_ok=True)
    after = md5(graph_path) if os.path.exists(graph_path) else "-"
    with open(lp, "a") as f:
        f.write(f"{now_iso()} @{git_head()} md5 {before or '?'} -> {after} {line}\n")

# ---------------------------------------------------------------- graph helpers
def adjacency(ns):
    adj = {k: [] for k in ns}
    for k, n in ns.items():
        for e in EDGES:
            for t in n.get(e, []):
                if t in adj:
                    adj[k].append((t, e)); adj[t].append((k, "rev-" + e))
    return adj

def in_edges(ns):
    ins = {k: [] for k in ns}
    for k, n in ns.items():
        for e in EDGES:
            for t in n.get(e, []):
                if t in ins:
                    ins[t].append((k, e))
    return ins

def hops(ns, origin, depth=2):
    adj = adjacency(ns)
    hop = {origin: (0, "—")}
    frontier = [origin]
    for h in range(1, depth + 1):
        nxt = []
        for k in frontier:
            for t, e in adj[k]:
                if t not in hop:
                    hop[t] = (h, f"{k} {e}"); nxt.append(t)
        frontier = nxt
    return hop

def attached(ns, f):
    return sorted(k for k, n in ns.items() if n["type"] in ("decision", "issue") and n.get("part_of") == [f])

def component_roots(ns):
    return [c for n in ns.values() if n["type"] == "component" for c in n["code_targets"]]

def parent_chain(ns, k):
    chain, seen = [], set()
    while ns[k].get("part_of"):
        k = ns[k]["part_of"][0]
        if k in seen or k not in ns:
            return chain, True
        seen.add(k); chain.append(k)
    return chain, False

# ---------------------------------------------------------------- timestamps
def git_last(path):
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cI", "--", path], capture_output=True, text=True)
        return r.stdout.strip() or None
    except Exception:
        return None

def mtime_iso(path):
    if not os.path.exists(path):
        return None
    if os.path.isdir(path):
        best = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    best = max(best, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
        if not best:
            return None
        return datetime.datetime.fromtimestamp(best).astimezone().isoformat(timespec="seconds")
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")

def newest(paths):
    best = (None, "-")
    for p in paths:
        if not os.path.exists(p):
            continue
        g = git_last(p)
        v = (g, "git") if g else (mtime_iso(p), "mtime")
        if v[0] and (best[0] is None or newer(v[0], best[0])):
            best = v
    return best

# ---------------------------------------------------------------- validate (R1)
def validate(g, want_schema=True, drift=True):
    problems, warnings = [], []
    for key in ("current_node", "nodes", "config"):
        if key not in g:
            problems.append(f"root missing `{key}`")
    ns = g.get("nodes", {})
    regs = g.get("config", {}).get("registries", [])
    roots = component_roots(ns)
    if want_schema:
        try:
            import jsonschema  # noqa
            from jsonschema import Draft202012Validator as V, FormatChecker
            schema = load(SCHEMA_PATH)
            for e in V(schema, format_checker=FormatChecker()).iter_errors(g):
                problems.append("schema: " + "/".join(str(p) for p in e.path) + ": " + e.message[:120])
        except ImportError:
            warnings.append("jsonschema not installed — schema layer skipped, R1 checks only")
        except FileNotFoundError:
            warnings.append(f"schema file not found at {SCHEMA_PATH} — schema layer skipped")
    cur = g.get("current_node")
    if cur is not None and cur not in ns:
        problems.append(f"current_node `{cur}` not in nodes")
    for k, n in ns.items():
        if n.get("id") != k:
            problems.append(f"key `{k}` != id `{n.get('id')}`")
        if not ID_RE.match(k):
            problems.append(f"bad id `{k}`")
        for e in EDGES:
            for t in n.get(e, []):
                if t not in ns:
                    problems.append(f"dangling {k}.{e} -> {t}")
                elif t == k:
                    problems.append(f"self-edge {k}.{e}")
        for t in n.get("resolves", []):
            if t in ns and ns[t]["type"] != "issue":
                problems.append(f"{k}.resolves -> {t} is not an issue")
            elif t in ns and ns[t].get("issue_status", "open") != "resolved":
                problems.append(f"{k}.resolves -> {t} but {t}.issue_status is {ns[t].get('issue_status', 'unset')} (must be resolved)")
        for t in n.get("supersedes", []):
            if t in ns and ns[t]["type"] != "decision":
                problems.append(f"{k}.supersedes -> {t} is not a decision")
        if n["type"] == "component" and n.get("part_of"):
            problems.append(f"component `{k}` has part_of")
        if len(n.get("part_of", [])) > 1:
            problems.append(f"{k}.part_of has {len(n['part_of'])} entries")
        _, cyc = parent_chain(ns, k)
        if cyc:
            problems.append(f"part_of cycle through `{k}`")
        if "source_ref" in n and regs:
            if not any(r["type"] == n["type"] and re.match(r["id_pattern"], n["source_ref"]) for r in regs):
                problems.append(f"{k}.source_ref `{n['source_ref']}` matches no registry of type {n['type']}")
        for p in n.get("docs", []) + n.get("code_targets", []):
            if not os.path.exists(p):
                problems.append(f"{k}: path missing `{p}`")
        if n["type"] != "component" and roots:
            for c in n.get("code_targets", []):
                if not any(c.startswith(r) for r in roots):
                    problems.append(f"{k}: code_target `{c}` outside component roots")
        if n["type"] in ("decision", "issue") and not n.get("part_of") and not n.get("affects"):
            warnings.append(f"{k}: {n['type']} attached to nothing (R5)")
        if n.get("file"):
            f = n["file"]
            if not os.path.exists(f):
                problems.append(f"{k}: entity file missing `{f}`")
            else:
                if n.get("sha256") and sha256_of(f) != n["sha256"]:
                    problems.append(f"{k}: entity file `{f}` changed outside graph_tool (sha256 mismatch) — P2; restore it or record the change with `append`")
                missing = [h for h in HEADINGS.get(n["type"], []) + ["Log"] if h not in entity_sections(f)]
                if missing: problems.append(f"{k}: entity file `{f}` lacks sections {missing}")
    problems += view_drift(g) if (want_schema and drift) else []
    return problems, warnings

# ---------------------------------------------------------------- content staleness (D24)
def registry_scan(g):
    """Return per-registry: ids found in file. Pattern anchors are stripped and applied to tokens."""
    out = []
    for r in g["config"].get("registries", []):
        f = r["file"]
        if not os.path.exists(f):
            out.append((r, None)); continue
        core = r["id_pattern"].lstrip("^").rstrip("$")
        text = open(f, encoding="utf-8", errors="replace").read()
        ids = set(m.group(0) for m in re.finditer(r"(?<![\w-])(?:" + core + r")(?![\w-])", text))
        out.append((r, ids))
    return out

def content_checks(g):
    ns = g["nodes"]; findings = []
    roots = component_roots(ns)
    scans = registry_scan(g)
    for r, ids in scans:
        tag = f"{r['type']} registry `{r['file']}`"
        if ids is None:
            findings.append(("error", tag, "registry file missing")); continue
        shipped = any(r["file"].startswith(x) for x in roots)
        own = {n["source_ref"] for n in ns.values() if n["type"] == r["type"] and "source_ref" in n and re.match(r["id_pattern"], n["source_ref"])}
        folded = {f for n in ns.values() for f in n.get("folded", []) if re.match(r["id_pattern"], f)}
        findings.append(("info", tag + (" (shipped)" if shipped else ""), f"scanned: {len(ids)} ids in file, {len(own)} nodes with matching source_ref, {len(own & ids)} matched, {len(folded & ids)} folded ids present"))
        for i in sorted(own - ids):
            findings.append(("error", tag + (" (shipped)" if shipped else ""), f"orphan source_ref `{i}` not in file"))
        for i in sorted(folded - ids):
            findings.append(("error", tag, f"folded id `{i}` not in file"))
        unindexed = sorted(ids - own - folded)
        if unindexed:
            findings.append(("info", tag, f"{len(unindexed)} ids in file without node and not folded: {', '.join(unindexed[:12])}{' …' if len(unindexed) > 12 else ''}"))
    # parent-code layer (timestamp based): docs-only structural nodes vs the code of their non-component parent and affects targets
    for k, n in ns.items():
        if n["type"] in ("decision", "issue") or n.get("code_targets") or not n.get("docs"):
            continue
        rel = [p for p in n.get("part_of", []) if p in ns and ns[p]["type"] != "component"] + [a for a in n.get("affects", []) if a in ns]
        if not rel:
            continue
        best = (None, "-", None)
        for r_ in rel:
            c = newest(ns[r_].get("code_targets", []))
            if c[0] and (best[0] is None or newer(c[0], best[0])):
                best = (c[0], c[1], r_)
        d = newest(n["docs"])
        if best[0] and d[0] and newer(best[0], d[0]):
            findings.append(("warn", k, f"docs-only node behind related code: `{best[2]}` code {best[0]} ({best[1]}) > docs {d[0]} ({d[1]}) [parent-code layer, timestamp based; component parents excluded]"))
    return findings

def timestamp_checks(ns, keys):
    rows = []
    for k in keys:
        n = ns[k]
        c = newest(n.get("code_targets", [])); d = newest(n.get("docs", []))
        if not n.get("code_targets"):
            finding = "(no code_targets)"
        elif c[0] and d[0] and newer(c[0], d[0]):
            finding = "CODE NEWER THAN DOCS"
        else:
            finding = "—"
        rows.append((k, f"{c[0] or '-'} ({c[1]})", f"{d[0] or '-'} ({d[1]})", finding))
    return rows

# ---------------------------------------------------------------- proposals
def growth_candidates(g):
    ns = g["nodes"]; th = g["config"].get("growth_threshold", 5)
    return [(f, len(attached(ns, f)), th) for f, n in ns.items() if n["type"] in ("feature", "function") and len(attached(ns, f)) >= th]

def fold_candidates(g):
    ns = g["nodes"]; ins = in_edges(ns); out = []
    for k, n in ns.items():
        if n.get("wip_status") in ("IN_PROGRESS", "BLOCKED") or not ins[k]:
            continue
        if n["type"] == "decision" and all(e == "supersedes" for _, e in ins[k]):
            out.append((k, ins[k][0][0], "superseded, no other live in-edges"))
        if n["type"] == "issue" and all(e == "resolves" for _, e in ins[k]):
            out.append((k, ins[k][0][0], "resolved, no other live in-edges"))
    return out

# ---------------------------------------------------------------- entities (plan integrity-store P1–P5)
ENTITY_TYPES = ("decision", "issue", "plan", "rule")
ENTITY_DIR = "docs/entities"
HEADINGS = {  # required sections per entity type, in order; "Log" is always last and append-only
    "decision": ["Statement", "Public summary", "User's words", "Reason", "Date"],
    "issue": ["Text", "Source"],
    "plan": ["Goal", "Approval"],
    "rule": ["Statement", "Source"],
}
ENTITY_MARK = "<!-- entity {id} · {type} · written by graph_tool; do not edit by hand — use `graph_tool.py append` -->"

def sha256_of(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def entity_sections(path):
    """Parse an entity file into {heading: text}."""
    out, cur = {}, None
    for line in open(path, encoding="utf-8").read().splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m: cur = m.group(1); out[cur] = []; continue
        if cur is not None: out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}

def render_entity(nid, ntype, title, sections, when):
    lines = [ENTITY_MARK.format(id=nid, type=ntype), f"# {nid} — {title}", ""]
    for h in HEADINGS[ntype]:
        lines += [f"## {h}", sections[h].strip(), ""]
    for h, t in sections.items():
        if h not in HEADINGS[ntype] and h != "Log":
            lines += [f"## {h}", t.strip(), ""]
    lines += ["## Log", f"- {when} created by graph_tool", ""]
    return "\n".join(lines)

def entity_text(ns, k):
    n = ns[k]
    if n.get("file") and os.path.exists(n["file"]):
        sec = entity_sections(n["file"])
        return " ".join(v for h, v in sec.items() if h != "Log")
    return ""

def tokens(t):
    t = t.lower()
    words = set(w for w in re.findall(r"[a-z0-9_]{3,}", t))
    cjk = re.sub(r"[^\u3040-\u30ff\u4e00-\u9fff]", "", t)
    return words | {cjk[i:i + 2] for i in range(len(cjk) - 1)}

def candidates(ns, ntype, text, k=5):
    """P4: every live entity of the same type + the top-k by token overlap (Jaccard)."""
    q = tokens(text); same = []
    for nid, n in sorted(ns.items()):
        if n["type"] != ntype:
            continue
        t = tokens(nid + " " + n["name"] + " " + entity_text(ns, nid))
        score = len(q & t) / len(q | t) if q | t else 0.0
        same.append((score, nid, n["name"]))
    top = sorted(same, reverse=True)[:k]
    return same, top

# ---------------------------------------------------------------- views (P3: documents people read are generated)
VIEW_KINDS = ("decisions", "public-decisions", "issues", "current", "plans")
VIEW_MARK = "<!-- generated by graph_tool render ({kind}) from dependency_graph.json + docs/entities — do not edit -->"

def first_line(t):
    t = (t or "").strip()
    return t.splitlines()[0] if t else "—"

def folded_into(ns, k):
    for j, m in ns.items():
        if k in m.get("supersedes", []) and ns[k].get("wip_status") == "folded":
            return j
    return None

def decision_status(ns, k):
    n = ns[k]; st = n.get("wip_status")
    if st == "PLANNED": return "decided, not yet implemented"
    if st == "IN_PROGRESS": return "in progress"
    if st == "BLOCKED": return "blocked"
    return "active"

def render_view(g, kind):
    ns = g["nodes"]; out = [VIEW_MARK.format(kind=kind), ""]
    sec = lambda k: entity_sections(ns[k]["file"]) if ns[k].get("file") and os.path.exists(ns[k]["file"]) else {}
    rel = lambda k: "; ".join(x for x in (("supersedes " + ", ".join(ns[k]["supersedes"])) if ns[k].get("supersedes") else "",
                                          ("resolves " + ", ".join(ns[k]["resolves"])) if ns[k].get("resolves") else "") if x) or "—"
    ref = lambda k: ns[k].get("source_ref", k)
    decs = sorted((k for k, n in ns.items() if n["type"] == "decision"), key=lambda k: (re.sub(r"\d", "", ref(k)), int(re.sub(r"\D", "", ref(k)) or 0)))
    if kind == "decisions":
        out += ["# Decision register (generated)", "", "| id | decision | supersedes / resolves | status | entity |", "|---|---|---|---|---|"]
        for k in decs:
            out.append(f"| {ref(k)} | {first_line(sec(k).get('Statement')) if sec(k) else ns[k]['name']} | {rel(k)} | {decision_status(ns, k)} | {ns[k].get('file', '(no entity file yet)')} |")
    elif kind == "public-decisions":
        out += ["# Public decision register (generated from each decision's Public summary)", "", "| id | Decision | Supersedes / resolves | Status |", "|----|----------|-----------------------|--------|"]
        for k in decs:
            s_ = sec(k)
            if not s_: continue  # not migrated yet: nothing public to show
            out.append(f"| {ref(k)} | {first_line(s_.get('Public summary'))} | {rel(k)} | {decision_status(ns, k)} |")
    elif kind == "issues":
        out += ["# Issue register (generated)", "", "| id | issue | status | owner | trigger | closed_by | attached to |", "|---|---|---|---|---|---|---|"]
        iss = sorted((k for k, n in ns.items() if n["type"] == "issue"), key=lambda k: int(re.sub(r"\D", "", ref(k)) or 0))
        for k in iss:
            n = ns[k]; txt = first_line(sec(k).get("Text")) if sec(k) else n["name"]
            out.append(f"| {ref(k)} | {txt} | {n.get('issue_status', '—')} | {n.get('owner', '—')} | {n.get('trigger', '—')} | {n.get('closed_by', '—')} | {(n.get('part_of') or ['—'])[0]} |")
    elif kind == "current":
        out += ["# Current specification (generated: active decisions per node)", ""]
        by = defaultdict(list)
        for k in decs:
            if ns[k].get("wip_status") != "folded": by[(ns[k].get("part_of") or ["(unattached)"])[0]].append(k)
        for parent in sorted(by):
            out += [f"## {parent}", ""]
            for k in by[parent]:
                out.append(f"- **{ref(k)}** ({decision_status(ns, k)}): {first_line(sec(k).get('Statement')) if sec(k) else ns[k]['name']}")
            out.append("")
    elif kind == "plans":
        out += ["# Plans (generated: goal, steps, decisions)", ""]
        for k in sorted(x for x, n in ns.items() if n["type"] == "plan"):
            s_ = sec(k); out += [f"## {k} — {ns[k]['name']} ({ns[k].get('wip_status', '—')})", "", f"Goal: {first_line(s_.get('Goal'))}", f"Approval: {first_line(s_.get('Approval'))}", ""]
            kids = sorted(j for j, m in ns.items() if m.get("part_of") == [k])
            for j in kids:
                m = ns[j]; mark = " (next)" if m.get("next") else ""
                out.append(f"- {m['type']} `{j}`: {m['name']} — {m.get('wip_status') or m.get('issue_status') or '—'}{mark}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"

def view_drift(g):
    probs = []
    for v in g.get("config", {}).get("views", []):
        want = render_view(g, v["kind"])
        if not os.path.exists(v["path"]):
            probs.append(f"view `{v['path']}` ({v['kind']}) missing — run `render`")
        elif open(v["path"], encoding="utf-8").read() != want:
            probs.append(f"view `{v['path']}` ({v['kind']}) differs from a fresh render — edited by hand or stale; run `render`")
    return probs

# ---------------------------------------------------------------- backlog (D33)
def component_of(ns, k):
    if ns[k]["type"] == "component":
        return k
    chain, _ = parent_chain(ns, k)
    top = chain[-1] if chain else None
    if top and ns[top]["type"] == "component":
        return top
    for a in ns[k].get("affects", []):  # issue attached by `affects` only
        if a in ns and a != k:
            return component_of(ns, a) if ns[a].get("part_of") or ns[a]["type"] == "component" else a
    return "(none)"

def short(t, n=90):
    t = t.replace("|", "\\|")
    return t if len(t) <= n else t[:n - 1] + "…"

def backlog(g, owner=None, next_only=False, component=None, all_=False):
    """Return (rows, excluded, filter) — rows: (kind, id, name, component, state, owner, trigger/parent, next); excluded: Counter component -> n."""
    ns = g["nodes"]; flt = {} if all_ else dict(g["config"].get("backlog_filter", {}))
    if owner: flt["owner"] = owner
    if next_only: flt["next_only"] = True
    if component: flt["component"] = component
    rows, excluded = [], Counter()
    for k, n in sorted(ns.items()):
        comp = component_of(ns, k)
        if n["type"] == "issue":
            if n.get("issue_status", "open") != "open":
                continue
            keep = (not flt.get("owner") or n.get("owner") == flt["owner"]) and (not flt.get("next_only") or n.get("next")) \
                   and (not flt.get("component") or comp == flt["component"])
            if n.get("next") and not flt.get("component"):
                keep = True  # a `next` item is never hidden by the owner filter
            if not keep:
                excluded[comp] += 1; continue
            rows.append(("issue", k, short(n["name"]), comp, "open", n.get("owner", "—"), n.get("trigger", "—"), "next" if n.get("next") else ""))
        elif n.get("wip_status") in ("PLANNED", "IN_PROGRESS", "BLOCKED") or n.get("next"):
            if flt.get("component") and comp != flt["component"]:
                excluded[comp] += 1; continue
            rows.append((n["type"], k, short(n["name"]), comp, n.get("wip_status", "—"), "—", "part_of " + (n.get("part_of") or ["—"])[0], "next" if n.get("next") else ""))
    order = {"next": 0, "": 1}
    rows.sort(key=lambda r: (order[r[7]], r[0] != "issue", r[3], r[1]))
    return rows, excluded, flt

def backlog_md(g, **kw):
    rows, excluded, flt = backlog(g, **kw)
    out = [table(["kind", "id", "name", "component", "state", "owner", "trigger / parent", "next"], rows)]
    fdesc = ", ".join(f"{k}={v}" for k, v in sorted(flt.items())) or "none (all open issues)"
    out.append(f"Filter: {fdesc}. " + ("Excluded by the filter: " + ", ".join(f"{c}: {n}" for c, n in sorted(excluded.items())) + f" (total {sum(excluded.values())}) — run `backlog --all` to list them."
                                         if excluded else "Excluded by the filter: none."))
    if not any(r[7] == "next" for r in rows) and not excluded:
        out.append("WARNING: no item carries `next` (D33) — set one with `set-next <node>`.")
    return "\n".join(out)

# ---------------------------------------------------------------- markdown helpers
def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out) if rows else "\n".join(out[:2]) + "\n| - none - |" + " |" * (len(headers) - 1)

def components_table(ns):
    rows = []
    for k, n in sorted(ns.items()):
        if n["type"] == "component":
            rows.append((k, n["name"], ", ".join(f"`{c}`" for c in n["code_targets"]) or "—",
                         ", ".join(f"`{d}`" for d in n["docs"]) or "—", n.get("wip_status", "—")))
    return table(["id", "name", "roots", "overview doc", "wip"], rows)

SUBGRAPH_LEGEND = "Legend: one row per node; hop = shortest distance over all edge kinds in both directions (`rev-` = traversed against the arrow); `path from origin` = the first path found (BFS, ids sorted), other paths may exist; `(index)` = feature/function that has feature/function children."

def subgraph_table(ns, hop, why_col=False):
    rows = []
    for k, (h, path) in sorted(hop.items(), key=lambda x: (x[1][0], x[0])):
        is_index = ns[k]["type"] in ("feature", "function") and any(m.get("part_of") == [k] and m["type"] in ("feature", "function") for m in ns.values())
        r = [h, k, ns[k]["type"] + (" (index)" if is_index else ""), ns[k].get("wip_status", "—"), path]
        if why_col:
            r.append("")
        rows.append(r)
    hdr = ["hop", "id", "type", "wip_status", "path from origin"] + (["why it matters"] if why_col else [])
    return table(hdr, rows)

# ---------------------------------------------------------------- commands
def cmd_validate(g, args):
    problems, warnings = validate(g)
    print("## validate")
    print(table(["severity", "finding"], [("error", p) for p in problems] + [("warn", w) for w in warnings]))
    ns = g["nodes"]
    print(f"\nnodes: {len(ns)} = " + ", ".join(f"{t} {c}" for t, c in sorted(Counter(n['type'] for n in ns.values()).items())))
    print("RESULT:", "FAIL" if problems else "OK")
    return 1 if problems else 0

def cmd_hydrate(g, args):
    ns = g["nodes"]; origin = args.node
    if origin not in ns:
        close = [k for k in ns if origin.lower() in k or k in origin.lower()]
        print(f"ERROR: node `{origin}` not found. Closest ids: {', '.join(sorted(close)) or 'none'}"); return 1
    hop = hops(ns, origin)
    print(f"## Impact Assessment Checklist — {origin}\n")
    print("### Components (always shown — R7)"); print(components_table(ns)); print()
    print("### Backlog (graph-wide, always shown — D33)"); print(backlog_md(g)); print()
    print("### Subgraph"); print(subgraph_table(ns, hop)); print(SUBGRAPH_LEGEND); print()
    rows = []
    for k in sorted(hop, key=lambda x: (hop[x][0], x)):
        for kind in ("docs", "code_targets"):
            for p in ns[k].get(kind, []):
                st = "MISSING" if not os.path.exists(p) else ("exists (dir: read every file under it)" if os.path.isdir(p) else "exists")
                rows.append((k, kind, f"`{p}`", st))
        if "source_ref" in ns[k]:
            regs = [r for r in g["config"].get("registries", []) if r["type"] == ns[k]["type"] and re.match(r["id_pattern"], ns[k]["source_ref"])]
            for r in regs:
                rows.append((k, "registry entry", f"`{ns[k]['source_ref']}` in `{r['file']}`", "exists" if os.path.exists(r["file"]) else "MISSING"))
    print("### Files loaded (read every `exists` row in full before ticking the first box)"); print(table(["node", "kind", "path", "status"], rows)); print()
    print("### Constraints inherited from decisions")
    dec = [k for k in hop if ns[k]["type"] == "decision"]
    for k in sorted(dec, key=lambda x: (hop[x][0], x)):
        n = ns[k]; print(f"- hop {hop[k][0]} `{k}` ({n.get('source_ref', '—')}): {n['name']}" + (f" — folded: {', '.join(n['folded'])}" if n.get("folded") else ""))
    if not dec: print("- none")
    print()
    print("### Decisions to re-examine (hop 0–1 decisions: affects ∪ resolves ∪ supersedes ∪ superseded-by ∪ same-parent decisions)")
    adj = adjacency(ns); rows = []
    for k in sorted(hop, key=lambda x: (hop[x][0], x)):
        if hop[k][0] <= 1 and ns[k]["type"] == "decision":
            n = ns[k]
            rel = set(n.get("affects", [])) | set(n.get("resolves", [])) | set(n.get("supersedes", [])) | {s for s, e in adj[k] if e == "rev-supersedes"}
            parent = n.get("part_of", [None])[0]
            sib = sorted(j for j, m in ns.items() if m["type"] == "decision" and m.get("part_of") == [parent] and j != k)
            rows.append((k, n.get("source_ref", "—"), ", ".join(sorted(rel)) or "—", f"{len(sib)} siblings under `{parent}`"))
    print(table(["decision", "registry id", "affects/resolves/supersedes", "same-parent"], rows)); print()
    print("### Existing capabilities (R8 — name/path overlap across all components)")
    words = {w for w in re.split(r"[^a-z0-9]+", (origin + " " + ns[origin]["name"]).lower()) if len(w) > 3}
    rows = []
    for k, n in ns.items():
        if k in hop or n["type"] in ("decision", "issue"):
            continue
        nw = {w for w in re.split(r"[^a-z0-9]+", (k + " " + n["name"]).lower()) if len(w) > 3}
        shared_path = any(any(c.startswith(d) or d.startswith(c) for d in ns[origin].get("code_targets", [])) for c in n.get("code_targets", []))
        if words & nw or shared_path:
            chain, _ = parent_chain(ns, k)
            rows.append((k, chain[-1] if chain else k, n["name"], "name" if words & nw else "path"))
    print(table(["id", "component", "provides", "overlap"], rows)); print()
    print("### Stale docs (F10 timestamp layer + D24 content layer)")
    print(table(["node", "code last changed", "docs last changed", "finding"], timestamp_checks(ns, [k for k in sorted(hop, key=lambda x: (hop[x][0], x)) if ns[k]["type"] not in ("decision", "issue")])))
    cf = content_checks(g)
    print(table(["severity", "scope", "finding"], cf)); print()
    print("### Blast radius")
    own = defaultdict(list)
    for k, n in ns.items():
        for p in n.get("code_targets", []): own[p].append(k)
    shared = {p: ks for p, ks in own.items() if len(ks) > 1 and any(x in hop for x in ks)}
    print("- Shared code_targets: " + ("; ".join(f"`{p}` ← {', '.join(ks)}" for p, ks in shared.items()) if shared else "none"))
    print("- IN_PROGRESS / BLOCKED in subgraph: " + (", ".join(k for k in hop if ns[k].get("wip_status") in ("IN_PROGRESS", "BLOCKED")) or "none"))
    print()
    print("### Pre-modification checks")
    for line in ("All hop-1 and hop-2 files read (or each MISSING row acknowledged)", "Existing capabilities reviewed; no duplicate implementation planned",
                 "Decisions to re-examine acknowledged", "Stale docs acknowledged (will be updated in this change or logged as unresolved)",
                 "No conflicting IN_PROGRESS work on shared code_targets", f"current_node set to `{origin}`"):
        print(f"- [ ] {line}")
    if getattr(args, "dry_run", False):
        print("\n(dry-run: current_node not written)")
    else:
        old = g.get("current_node"); b4 = md5(args.graph); g["current_node"] = origin; guarded_save(args.graph, g); log_op(g, f"hydrate {origin} (current_node {old} -> {origin})", args.graph, b4)
        print(f"\n(current_node written: `{origin}`)")
    return 0

def proposals(g, lang):
    lines = []
    for f, c, t in growth_candidates(g):
        lines.append(MSG["growth"][lang].format(n=f, c=c, t=t))
    for v, s, why in fold_candidates(g):
        lines.append(MSG["fold"][lang].format(v=v, s=s, why=why))
    return lines or [MSG["none"][lang]]

def cmd_check(g, args):
    ns = g["nodes"]
    print("## check\n")
    print("### Growth (attached = decision/issue nodes whose `part_of` is this node; `affects` does not count). Criterion (a) threshold is computed here; criteria (b) partial-scope decision and (c) design doc with ≥2 separate top-level sections are judged by hand.")
    th = g["config"].get("growth_threshold", 5)
    print(table(["node", "type", "attached", "threshold", "proposal"], [(f, n["type"], len(attached(ns, f)), th, "SPLIT" if len(attached(ns, f)) >= th else "—") for f, n in sorted(ns.items()) if n["type"] in ("feature", "function")]))
    print("\n### Fold candidates"); print(table(["victim", "survivor", "why"], fold_candidates(g)))
    print("\n### Staleness — timestamp layer"); print(table(["node", "code last changed", "docs last changed", "finding"], timestamp_checks(ns, [k for k, n in sorted(ns.items()) if n["type"] not in ("decision", "issue")])))
    print("\n### Staleness — content layer (D24)"); print(table(["severity", "scope", "finding"], content_checks(g)))
    print("\n### Proposals (" + args.lang + ")")
    for l in proposals(g, args.lang): print("- " + l)
    return 0

def handover_blocks(g):
    """Return the generated blocks as dict name -> list of lines (used by handover-tables and --verify)."""
    ns = g["nodes"]; cur = g.get("current_node"); B = {}
    B["components"] = components_table(ns).splitlines()
    if cur and cur in ns:
        B["subgraph"] = subgraph_table(ns, hops(ns, cur), why_col=True).splitlines()
    else:
        B["subgraph"] = ["- current_node is null; nothing to hydrate"]
    gc = growth_candidates(g); fc = fold_candidates(g)
    B["s6"] = ["Node counts: " + ", ".join(f"{t} {c}" for t, c in sorted(Counter(n['type'] for n in ns.values()).items())) + f"; total {len(ns)}",
               "Growth check: " + ("; ".join(f"`{f}` {c}/{t}" for f, c, t in gc) if gc else "no node at or above threshold") + f" (threshold {g['config'].get('growth_threshold', 5)})",
               "Fold check (current state): " + ("; ".join(f"`{v}`→`{s}`" for v, s, _ in fc) if fc else "no candidates")]
    B["s7"] = table(["node", "code last changed", "docs last changed", "finding", "action"], [r + ("",) for r in timestamp_checks(ns, [k for k, n in sorted(ns.items()) if n["type"] not in ("decision", "issue")])]).splitlines()
    return B

def cmd_handover_tables(g, args):
    if getattr(args, "verify", None):
        return verify_handover(g, args)
    ns = g["nodes"]; cur = g.get("current_node"); B = handover_blocks(g)
    print(f"<!-- generated by graph_tool.py handover-tables at {now_iso()} (D25) — do not retype -->")
    print(f"Generated: {now_iso()} by graph_tool @{git_head()} · Graph: `{args.graph}` md5 {md5(args.graph)}  ← copy this line as the handover header's `Generated:` line")
    print("### Components (R7)"); print("\n".join(B["components"]))
    print(f"### Subgraph (re-hydrate with `/graph:hydrate {cur}`)" if cur else "### Subgraph"); print("\n".join(B["subgraph"])); print(SUBGRAPH_LEGEND)
    print("\n<!-- §6 lines -->"); print("\n".join(B["s6"]))
    lp = log_path(g)
    if os.path.exists(lp):
        lines = open(lp).read().strip().splitlines()
        print("Operations log (session history, from `" + lp + "`):")
        for l in lines[-20:]: print("- " + l)
    else:
        print("Operations log: none recorded (no fold/split/set via graph_tool yet)")
    print("\n<!-- §7 table -->"); print("\n".join(B["s7"]))
    cf = content_checks(g)
    if cf:
        print("Content layer (D24):"); print(table(["severity", "scope", "finding"], cf))
    return 0

def _rows(lines, drop_last_col=False):
    """Markdown table rows -> set of tuples of cells (header/separator excluded). Optionally drop the free-text last column."""
    out = set()
    for l in lines:
        if not l.startswith("|") or set(l.replace("|", "").strip()) <= set("-: "):
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if drop_last_col and len(cells) > 1:
            cells = cells[:-1]
        out.add(tuple(cells))
    return out

def verify_handover(g, args):
    """U14: compare the pasted generated blocks of a handover file with current tool output."""
    path = args.verify
    if not os.path.exists(path):
        print(f"ERROR: {path} not found"); return 1
    text = open(path, encoding="utf-8").read(); lines = text.splitlines()
    B = handover_blocks(g); problems = []
    def section(start_pat, end_pats):
        idx = [i for i, l in enumerate(lines) if re.match(start_pat, l)]
        if not idx: return None
        i = idx[0] + 1; out = []
        while i < len(lines) and not any(re.match(e, lines[i]) for e in end_pats):
            out.append(lines[i]); i += 1
        return out
    comp = section(r"^### Components", [r"^### ", r"^## "])
    sub = section(r"^### Subgraph", [r"^Files read outside", r"^## ", r"^### "])
    s6 = section(r"^## 6\. Decision Drift", [r"^## 7"])
    s7 = section(r"^## 7\. Staleness", [r"^## ", r"^<!-- graph_tool"])
    # components: exact rows (header dropped)
    if comp is None: problems.append("§2 Components table not found")
    else:
        want = _rows(B["components"]) - _rows(B["components"][:1]); got = _rows(comp) - _rows(B["components"][:1])
        if want != got: problems.append(f"§2 Components rows differ: missing {sorted(want - got)}, extra {sorted(got - want)}")
    # subgraph: compare all columns except the free-text last one
    if sub is None: problems.append("§2 Subgraph table not found")
    else:
        hdr = _rows(B["subgraph"][:1], True)
        want = _rows(B["subgraph"], True) - hdr; got = _rows(sub, True) - hdr
        if want != got: problems.append(f"§2 Subgraph rows differ (free-text column ignored): missing {sorted(want - got)[:6]}, extra {sorted(got - want)[:6]}")
    # §6 lines: the three generated lines must appear verbatim
    if s6 is None: problems.append("§6 not found")
    else:
        for l in B["s6"]:
            if l not in [x.strip() for x in s6]: problems.append(f"§6 line missing or stale: `{l}`")
    # §7: node/code/docs/finding columns must match (action column ignored)
    if s7 is None: problems.append("§7 table not found")
    else:
        hdr = _rows(B["s7"][:1], True)
        want = _rows(B["s7"], True) - hdr
        got = {r for r in _rows(s7, True) - hdr if len(r) == 4}  # ignore the 3-column D24 content table that may follow
        if want != got: problems.append(f"§7 rows differ (action column ignored): missing {sorted(want - got)[:4]}, extra {sorted(got - want)[:4]}")
    # footer md5 + HEAD
    footers = re.findall(r"<!-- graph_tool [a-z-]+ @([0-9a-f]+|-) graph md5 ([0-9a-f]{12})(?: -> ([0-9a-f]{12}))?", text)
    cur_md5 = md5(args.graph); head = git_head(); warnings = []
    if not footers: problems.append("no graph_tool footer with graph md5 found in handover")
    else:
        if len(footers) > 1: problems.append(f"{len(footers)} graph_tool footers found; keep exactly the last one")
        fhead, m1, m2 = footers[-1]; last = m2 or m1
        if last != cur_md5: problems.append(f"handover footer md5 {last} != current graph md5 {cur_md5} (handover generated from an older graph state)")
        head_moved = fhead not in ("-", head)
        s7p = [p for p in problems if p.startswith("§7")]
        if s7p and last == cur_md5:
            # §7 rows are timestamps; when the graph (md5) is unchanged a §7-only difference is drift after generation, not a paste error
            why = f"HEAD moved {fhead} -> {head}" if head_moved else "HEAD unchanged; a docs/code path was edited (mtime moved) after generation"
            for p in s7p: problems.remove(p); warnings.append(p + f" — diagnosis: {why}; graph md5 unchanged → not a paste error; regenerate §7 as the very last step")
    if not re.search(r"^Generated: .*graph_tool", text, re.M): warnings.append("header `Generated:` line does not carry a graph_tool stamp (hand-typed time?)")
    print("## handover-tables --verify " + path)
    rows = [("MISMATCH", p) for p in problems] + [("WARN", w) for w in warnings]
    print(table(["result", "detail"], rows or [("OK", "§2 Components, §2 Subgraph, §6 lines, §7 table, footer md5 and HEAD all match current graph")]))
    print("RESULT:", "FAIL" if problems else ("OK (with warnings)" if warnings else "OK"))
    return 1 if problems else 0

def cmd_lint_prose(g, args):
    """U15: version strings and D-ranges in skill prose vs plugin.json and the decision register."""
    skill_dir = os.path.normpath(os.path.join(HERE, ".."))
    plugin_root = os.path.normpath(os.path.join(skill_dir, "..", ".."))
    problems, checked = [], []
    try:
        pj = load(os.path.join(plugin_root, ".claude-plugin", "plugin.json")); ver = pj.get("version", "?")
    except Exception as e:
        print(f"ERROR: plugin.json not readable from {plugin_root}: {e}"); return 1
    reg = os.path.join(skill_dir, "references", "40-decision-register.md")
    max_d = 0
    if os.path.exists(reg):
        ids = re.findall(r"^\| D(\d+) \|", open(reg).read(), re.M); max_d = max(int(x) for x in ids) if ids else 0
    files = [os.path.join(skill_dir, "SKILL.md"), os.path.join(skill_dir, "references", "00-index.md"), os.path.join(skill_dir, "references", "sync-source.md"),
             os.path.join(skill_dir, "tools", "README.md"), os.path.join(plugin_root, "..", "README.md"), os.path.join(plugin_root, "..", ".claude-plugin", "marketplace.json")] + \
            [os.path.join(plugin_root, "skills", d, "SKILL.md") for d in os.listdir(os.path.join(plugin_root, "skills")) if d != os.path.basename(skill_dir)]
    for f in files:
        if not os.path.exists(f): continue
        rel = os.path.relpath(f, plugin_root); t = open(f, encoding="utf-8").read()
        SV = r"(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)"  # semver incl. pre-release (3.3.0-dev.1)
        for v in set(re.findall(r"Status: \**v" + SV, t)) | set(re.findall(r"Current version: \*\*" + SV + r"\*\*", t)):
            checked.append((rel, f"version {v}"))
            if v != ver: problems.append((rel, f"version string {v} != plugin.json {ver}"))
        for a, b in re.findall(r"D(\d+)[–-]D(\d+)", t):
            checked.append((rel, f"range D{a}–D{b}"))
            if max_d and int(b) != max_d: problems.append((rel, f"range D{a}–D{b} but register max is D{max_d}"))
    print("## lint-prose (plugin.json version " + ver + f", register max D{max_d})")
    print(table(["file", "checked"], checked or [("-", "nothing matched")]))
    print(table(["file", "finding"], problems or [("-", f"OK — {len(checked)} version/range strings checked, all consistent")]))
    print("Not covered: prose that names sub-commands or features (e.g. Files table, --help text) — keep those in sync by hand.")
    print("RESULT:", "FAIL" if problems else "OK")
    return 1 if problems else 0

def cmd_lint_handover(g, args):
    """Free-text cross-checks on a handover file (the class of error --verify cannot see)."""
    path = args.handover
    if not os.path.exists(path): print(f"ERROR: {path} not found"); return 1
    text = open(path, encoding="utf-8").read(); problems, warnings = [], []
    cur = g.get("current_node")
    def sec(n):
        m = re.search(rf"^## {n}\..*?$(.*?)(?=^## \d|\Z)", text, re.M | re.S); return m.group(1) if m else ""
    s1, s4, s5, s2, s7 = sec(1), sec(4), sec(5), sec(2), sec(7)
    if cur and f"`{cur}`" not in s5 and f"hydrate {cur}" not in s5: problems.append(f"§5 does not mention current_node `{cur}`")
    if cur and f"current_node: `{cur}`" not in s1: problems.append(f"§1 does not state current_node: `{cur}`")
    m = re.search(r"Resolved[^\n]*?:\s*([^\n]+)", s4)
    if m:
        ids = re.findall(r"\bU\d+\b", m.group(1))
        rows = re.findall(r"^\| (U\d+) \|", s4, re.M)
        for i in ids:
            if i in rows: problems.append(f"§4 lists {i} as resolved/removed but a table row {i} still exists")
    footers = re.findall(r"<!-- graph_tool [a-z-]+ @([0-9a-f]+|-) graph md5", text)
    if len(footers) != 1: problems.append(f"expected exactly 1 graph_tool footer, found {len(footers)}")
    if footers:
        fhead = footers[-1]
        try:
            commits = subprocess.run(["git", "log", "--format=%h", f"{fhead}..HEAD"], capture_output=True, text=True).stdout.split()
        except Exception:
            commits = []
        missing = [c for c in commits if c not in s1]
        if missing: warnings.append(f"§1 does not mention commit(s) after the footer HEAD {fhead}: {', '.join(missing)}")
    if not re.search(r"^Generated: .*graph_tool", text, re.M): problems.append("header `Generated:` line is hand-typed (no graph_tool stamp)")
    prev = getattr(args, "prev", None)
    if prev and os.path.exists(prev):
        ptext = open(prev, encoding="utf-8").read()
        pm = re.search(r"^## 4\..*?$(.*?)(?=^## \d|\Z)", ptext, re.M | re.S); p4 = pm.group(1) if pm else ""
        prev_ids = set(re.findall(r"^\| (U\d+) \|", p4, re.M))
        head4 = s4.split("|")[0]  # text before the table: Resolved / Transferred lines
        for i in sorted(prev_ids, key=lambda x: int(x[1:])):
            if not re.search(rf"^\| {i} \|", s4, re.M) and i not in head4:
                problems.append(f"§4: {i} was in the previous handover's table but is neither a row nor named as resolved/transferred now")
    elif prev:
        warnings.append(f"--prev {prev} not found; U-id continuity not checked")
    # empty free-text cells on flagged rows
    for line in s7.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[3] not in ("—", "finding", "(no code_targets)") and not set(cells[3]) <= set("-: ") and not cells[4]:
            problems.append(f"§7 row `{cells[0]}` has finding `{cells[3]}` but empty action")
    empties = [l for l in s2.splitlines() if l.startswith("| ") and l.count("|") == 7 and l.rstrip().endswith("|  |")]
    if len(empties) > 0: warnings.append(f"§2 subgraph: {len(empties)} rows with empty `why it matters`")
    problems = list(dict.fromkeys(problems)); warnings = list(dict.fromkeys(warnings))
    print("## lint-handover " + path)
    rows = [("PROBLEM", p) for p in problems] + [("WARN", w) for w in warnings]
    print(table(["result", "detail"], rows or [("OK", "§1/§4/§5 consistent with graph and git; single footer; stamped header")]))
    print("RESULT:", "FAIL" if problems else ("OK (with warnings)" if warnings else "OK"))
    return 1 if problems else 0

def cmd_add_path(g, args):
    ns = g["nodes"]; field = "docs" if args.cmd == "add-doc" else "code_targets"
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    if not os.path.exists(args.path): print(f"ERROR: path `{args.path}` does not exist"); return 1
    lst = ns[args.node].setdefault(field, [])
    if args.path not in lst: lst.append(args.path)
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"{args.cmd} {args.node} {args.path}", args.graph, b4)
    print(f"{args.node}.{field} += {args.path}")
    return cmd_validate(g, args)

def cmd_add_node(g, args):
    ns = g["nodes"]
    if args.id in ns: print(f"ERROR: `{args.id}` exists"); return 1
    if not ID_RE.match(args.id): print(f"ERROR: bad id `{args.id}`"); return 1
    if args.type not in ("component", "feature", "function", "decision", "issue", "task"): print("ERROR: bad type"); return 1
    n = {"id": args.id, "type": args.type, "name": args.name, "docs": args.doc or [], "code_targets": args.code or []}
    if args.part_of: n["part_of"] = [args.part_of]
    if args.source_ref: n["source_ref"] = args.source_ref
    if getattr(args, "status", None):
        if args.status not in WIP: print(f"ERROR: status must be one of {WIP}"); return 1
        n["wip_status"] = args.status
    if getattr(args, "next", False): n["next"] = True
    if args.type == "issue":
        n["issue_status"] = "open"
        if getattr(args, "owner", None): n["owner"] = args.owner
        if getattr(args, "trigger", None): n["trigger"] = args.trigger
    elif getattr(args, "owner", None) or getattr(args, "trigger", None):
        print("ERROR: --owner / --trigger are for issue nodes only"); return 1
    ns[args.id] = n
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"add-node {args.id} ({args.type}) part_of={args.part_of}", args.graph, b4)
    print(f"added `{args.id}` ({args.type})")
    return cmd_validate(g, args)

def cmd_fold(g, args):
    ns = g["nodes"]; v, s = args.victim, args.survivor
    for x in (v, s):
        if x not in ns: print(f"ERROR: `{x}` not in nodes"); return 1
    if ns[s]["type"] != "decision": print("ERROR: survivor must be a decision"); return 1
    if ns[v].get("wip_status") in ("IN_PROGRESS", "BLOCKED"): print(f"ERROR: `{v}` is {ns[v]['wip_status']}; refuse to fold"); return 1
    vic, sur = ns[v], ns[s]
    sur.setdefault("folded", [])
    for i in [vic.get("source_ref")] + vic.get("folded", []):
        if i and i not in sur["folded"]: sur["folded"].append(i)
    for a in vic.get("affects", []):
        if a != s and a not in sur.setdefault("affects", []): sur["affects"].append(a)
    for d in vic.get("docs", []):
        if d not in sur["docs"]: sur["docs"].append(d)
    del ns[v]
    for n in ns.values():
        for e in EDGES:
            if e in n:
                n[e] = [t for t in n[e] if t != v]
                if not n[e]: del n[e]
    if g.get("current_node") == v: g["current_node"] = s
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"fold {v} -> {s}; {s}.folded={sur['folded']}", args.graph, b4)
    print(f"folded `{v}` into `{s}`; {s}.folded = {sur['folded']}")
    return cmd_validate(g, args)

def cmd_split(g, args):
    ns = g["nodes"]; parent = args.node
    if parent not in ns: print(f"ERROR: `{parent}` not in nodes"); return 1
    for spec in args.children:
        if "=" not in spec: print(f"ERROR: bad child spec `{spec}` (want child=id,id)"); return 1
        child, ids = spec.split("=", 1); ids = [i for i in ids.split(",") if i]
        if not ID_RE.match(child): print(f"ERROR: bad child id `{child}`"); return 1
        if child in ns: print(f"ERROR: `{child}` exists"); return 1
        ns[child] = {"id": child, "type": "function", "name": child.replace("-", " "), "docs": list(ns[parent].get("docs", [])), "code_targets": [], "part_of": [parent], "wip_status": ns[parent].get("wip_status", "IN_PROGRESS")}
        for i in ids:
            if i not in ns: print(f"ERROR: `{i}` not in nodes"); return 1
            ns[i]["part_of"] = [child]
            ns[i]["affects"] = [child if a == parent else a for a in ns[i].get("affects", [])]
        print(f"created function `{child}` under `{parent}` with {len(ids)} attachments; fill name/code_targets by hand")
    b4 = md5(args.graph); guarded_save(args.graph, g)
    for spec in args.children:
        log_op(g, f"split {parent} -> {spec}", args.graph, b4)
    return cmd_validate(g, args)

def cmd_set_status(g, args):
    ns = g["nodes"]
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    if args.status not in WIP + ("none",): print("ERROR: status must be PLANNED|IN_PROGRESS|BLOCKED|DONE|none"); return 1
    if ns[args.node]["type"] == "issue": print("ERROR: issues carry issue_status; use `close`"); return 1
    old = ns[args.node].get("wip_status")
    if args.status == "none": ns[args.node].pop("wip_status", None)
    else: ns[args.node]["wip_status"] = args.status
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"set-status {args.node} {old} -> {args.status}", args.graph, b4)
    print(f"{args.node}.wip_status: {old} -> {args.status}")
    return cmd_validate(g, args)

def cmd_add_edge(g, args):
    ns = g["nodes"]
    if args.kind not in EDGES: print(f"ERROR: kind must be one of {EDGES}"); return 1
    for x in (args.src, args.dst):
        if x not in ns: print(f"ERROR: `{x}` not in nodes"); return 1
    lst = ns[args.src].setdefault(args.kind, [])
    if args.dst not in lst: lst.append(args.dst)
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"add-edge {args.src}.{args.kind} -> {args.dst}", args.graph, b4)
    print(f"added {args.src}.{args.kind} -> {args.dst}")
    return cmd_validate(g, args)

def cmd_set_current(g, args):
    ns = g["nodes"]; v = None if args.node == "null" else args.node
    if v is not None and v not in ns: print(f"ERROR: `{v}` not in nodes"); return 1
    old = g.get("current_node"); g["current_node"] = v
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"set-current {old} -> {v}", args.graph, b4)
    print(f"current_node: {old} -> {v}")
    return cmd_validate(g, args)

def cmd_add(g, args):
    """P4 + P1: search before add; create the entity file and the node together, validated before anything is saved."""
    ns = g["nodes"]
    if args.type not in ENTITY_TYPES: print(f"ERROR: add is for {ENTITY_TYPES}; use add-node for structure nodes"); return 1
    if args.id in ns: print(f"ERROR: `{args.id}` exists — use `append {args.id}` to add to it"); return 1
    if not ID_RE.match(args.id): print(f"ERROR: bad id `{args.id}`"); return 1
    sections = {}
    for spec in args.section or []:
        if "=" not in spec: print(f"ERROR: --section wants Heading=text, got `{spec[:40]}`"); return 1
        h, t = spec.split("=", 1); sections[h.strip()] = t
    missing = [h for h in HEADINGS[args.type] if not sections.get(h, "").strip()]
    if missing: print(f"ERROR: {args.type} needs sections {missing} (--section 'Heading=text')"); return 1
    same, top = candidates(ns, args.type, args.name + " " + " ".join(sections.values()))
    print(f"## search before add (P4) — {len(same)} existing {args.type} entities")
    print(table(["similarity", "id", "name"], [(f"{sc:.2f}", i, nm) for sc, i, nm in top]))
    print("All existing (read them before declaring the new entity distinct):")
    for sc, i, nm in same: print(f"- {i}: {nm}")
    if not (args.new_not_duplicate or args.duplicate_of):
        print("\nNOT WRITTEN: state the outcome — `--new-not-duplicate \"<why it differs from the list>\"` or `--duplicate-of <id>` (then use append)."); return 1
    if args.duplicate_of:
        print(f"\nNOT WRITTEN: duplicate of `{args.duplicate_of}` — add to it with `append {args.duplicate_of}`."); return 1
    path = os.path.join(ENTITY_DIR, f"{args.id}.md")
    if os.path.exists(path): print(f"ERROR: `{path}` already exists"); return 1
    os.makedirs(ENTITY_DIR, exist_ok=True)
    open(path, "w", encoding="utf-8").write(render_entity(args.id, args.type, args.name, sections, now_iso()))
    n = {"id": args.id, "type": args.type, "name": args.name, "docs": [], "code_targets": [], "file": path, "sha256": sha256_of(path)}
    if args.part_of: n["part_of"] = [args.part_of]
    if args.source_ref: n["source_ref"] = args.source_ref
    if args.status: n["wip_status"] = args.status
    if args.type == "issue":
        n["issue_status"] = "open"
        if args.owner: n["owner"] = args.owner
        if args.trigger: n["trigger"] = args.trigger
    ns[args.id] = n
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        os.remove(path); raise
    log_op(g, f"add {args.id} ({args.type}) file={path} P4-outcome=new-not-duplicate: {args.new_not_duplicate}", args.graph, b4)
    print(f"added `{args.id}` ({args.type}) with {path}")
    return cmd_validate(g, args)

def cmd_append(g, args):
    """Entity files are append-only: add a dated line under Log (corrections, status notes, later user words)."""
    ns = g["nodes"]
    if args.node not in ns or not ns[args.node].get("file"): print(f"ERROR: `{args.node}` has no entity file"); return 1
    n = ns[args.node]; f = n["file"]
    if sha256_of(f) != n.get("sha256"): print(f"ERROR: `{f}` was changed outside graph_tool; resolve that first (validate shows it)"); return 1
    old = open(f, encoding="utf-8").read()
    new = old.rstrip("\n") + f"\n- {now_iso()} {args.text}\n"
    open(f, "w", encoding="utf-8").write(new); n["sha256"] = sha256_of(f)
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        open(f, "w", encoding="utf-8").write(old); raise
    log_op(g, f"append {args.node}: {args.text[:120]}", args.graph, b4)
    print(f"appended to {f}")
    return cmd_validate(g, args)

def cmd_render(g, args):
    views = g.get("config", {}).get("views", [])
    if not views: print("No config.views defined — nothing to render."); return 0
    rows = []
    for v in views:
        want = render_view(g, v["kind"]); cur = open(v["path"], encoding="utf-8").read() if os.path.exists(v["path"]) else None
        if args.check:
            rows.append((v["path"], v["kind"], "OK" if cur == want else "DRIFT"))
        else:
            if cur != want:
                os.makedirs(os.path.dirname(v["path"]) or ".", exist_ok=True); open(v["path"], "w", encoding="utf-8").write(want)
            rows.append((v["path"], v["kind"], "unchanged" if cur == want else "written"))
    print("## render" + (" --check" if args.check else "")); print(table(["path", "kind", "result"], rows))
    if not args.check and any(r[2] == "written" for r in rows): log_op(g, "render " + ", ".join(r[0] for r in rows if r[2] == "written"), args.graph, md5(args.graph))
    bad = any(r[2] == "DRIFT" for r in rows); print("RESULT:", "FAIL" if bad else "OK"); return 1 if bad else 0

def cmd_backlog(g, args):
    print("## Backlog (D33)")
    print(backlog_md(g, owner=args.owner, next_only=args.next_only, component=args.component, all_=args.all))
    return 0

def cmd_set_next(g, args):
    ns = g["nodes"]
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    if ns[args.node]["type"] in ("component", "decision"): print("ERROR: `next` is not allowed on component / decision nodes"); return 1
    if args.off: ns[args.node].pop("next", None)
    else: ns[args.node]["next"] = True
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"set-next {args.node} {'off' if args.off else 'on'}", args.graph, b4)
    print(f"{args.node}.next: {'cleared' if args.off else 'true'}")
    return cmd_validate(g, args)

def cmd_set_issue(g, args):
    ns = g["nodes"]
    if args.node not in ns or ns[args.node]["type"] != "issue": print(f"ERROR: `{args.node}` is not an issue node"); return 1
    if not (args.owner or args.trigger): print("ERROR: give --owner and/or --trigger"); return 1
    n = ns[args.node]; ch = []
    if args.owner: ch.append(f"owner {n.get('owner')} -> {args.owner}"); n["owner"] = args.owner
    if args.trigger: ch.append(f"trigger -> {args.trigger!r}"); n["trigger"] = args.trigger
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"set-issue {args.node} " + "; ".join(ch), args.graph, b4)
    print(f"{args.node}: " + "; ".join(ch))
    return cmd_validate(g, args)

def cmd_close(g, args):
    ns = g["nodes"]
    if args.node not in ns or ns[args.node]["type"] != "issue": print(f"ERROR: `{args.node}` is not an issue node"); return 1
    if args.state not in ("resolved", "transferred"): print("ERROR: state must be resolved|transferred"); return 1
    n = ns[args.node]; by = args.by; dec = None
    if by in ns and ns[by]["type"] == "decision": dec = by
    else:
        m = [k for k, x in ns.items() if x["type"] == "decision" and x.get("source_ref") == by]
        dec = m[0] if len(m) == 1 else None
    if dec and args.state != "resolved": print("ERROR: a decision resolves an issue; use state `resolved`"); return 1
    old = n.get("issue_status"); n["issue_status"] = args.state; n["closed_by"] = ns[dec].get("source_ref", dec) if dec else by
    n.pop("next", None)
    if dec:
        lst = ns[dec].setdefault("resolves", [])
        if args.node not in lst: lst.append(args.node)
    b4 = md5(args.graph); guarded_save(args.graph, g)
    log_op(g, f"close {args.node} {old} -> {args.state} by {n['closed_by']}" + (f"; {dec}.resolves += {args.node}" if dec else ""), args.graph, b4)
    print(f"{args.node}: {old} -> {args.state} (closed_by {n['closed_by']})" + (f"; added {dec}.resolves -> {args.node}" if dec else ""))
    return cmd_validate(g, args)

# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="dependency_graph.json"); ap.add_argument("--lang", default=None, choices=["en", "ja"])
    sub = ap.add_subparsers(dest="cmd", required=True)
    def sp(name, *posargs, nargs=None):
        p = sub.add_parser(name); p.add_argument("--lang", default=None, choices=["en", "ja"], dest="lang_sub")
        for a in posargs: p.add_argument(a, nargs=nargs) if nargs and a == posargs[-1] else p.add_argument(a)
        return p
    sp("validate"); sp("hydrate", "node"); sp("check"); sp("handover-tables")
    sp("fold", "victim", "survivor"); sp("split", "node", "children", nargs="+")
    sp("set-status", "node", "status"); sp("add-edge", "src", "kind", "dst"); sp("set-current", "node"); sp("lint-prose")
    p = sp("lint-handover", "handover"); p.add_argument("--prev", default=None, metavar="PREV_HANDOVER_MD")
    sp("add-doc", "node", "path"); sp("add-code", "node", "path")
    p = sp("add-node", "id", "type", "name"); p.add_argument("--part-of", dest="part_of"); p.add_argument("--doc", action="append"); p.add_argument("--code", action="append"); p.add_argument("--source-ref", dest="source_ref"); p.add_argument("--status")
    p.add_argument("--next", action="store_true"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger")
    p = sp("backlog"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--next-only", dest="next_only", action="store_true"); p.add_argument("--component"); p.add_argument("--all", action="store_true")
    p = sp("set-next", "node"); p.add_argument("--off", action="store_true")
    p = sp("set-issue", "node"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger")
    p = sp("close", "node", "state"); p.add_argument("--by", required=True)
    p = sp("add", "id", "type", "name"); p.add_argument("--part-of", dest="part_of"); p.add_argument("--source-ref", dest="source_ref"); p.add_argument("--status")
    p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger"); p.add_argument("--section", action="append")
    p.add_argument("--new-not-duplicate", dest="new_not_duplicate"); p.add_argument("--duplicate-of", dest="duplicate_of")
    p = sp("append", "node", "text")
    p = sp("render"); p.add_argument("--check", action="store_true")
    for name, a in ap._subparsers._group_actions[0].choices.items():
        if name == "handover-tables": a.add_argument("--verify", default=None, metavar="HANDOVER_MD")
        if name == "hydrate": a.add_argument("--dry-run", dest="dry_run", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.exists(args.graph):
        print(f"ERROR: {args.graph} not found (run from the project root, or pass --graph)"); return 1
    g = load(args.graph)
    args.lang = args.lang_sub or args.lang or g.get("config", {}).get("interaction_language", "en")
    if args.lang not in ("en", "ja"): args.lang = "en"
    before = md5(args.graph)
    try:
      rc = {"validate": cmd_validate, "hydrate": cmd_hydrate, "check": cmd_check, "handover-tables": cmd_handover_tables,
          "fold": cmd_fold, "split": cmd_split, "set-status": cmd_set_status, "add-edge": cmd_add_edge, "set-current": cmd_set_current,
          "add-node": cmd_add_node, "lint-prose": cmd_lint_prose, "lint-handover": cmd_lint_handover,
          "add-doc": cmd_add_path, "add-code": cmd_add_path, "backlog": cmd_backlog, "set-next": cmd_set_next,
          "set-issue": cmd_set_issue, "close": cmd_close, "add": cmd_add, "append": cmd_append, "render": cmd_render}[args.cmd](g, args)
    except WriteRefused as e:
        print("## write refused — the graph would be invalid; nothing was written (U31)")
        print(table(["severity", "finding"], [("error", p) for p in e.args[0]]))
        print("RESULT: FAIL"); rc = 1
    after = md5(args.graph)
    print(f"\n<!-- graph_tool {args.cmd} @{git_head()} graph md5 {before}" + (f" -> {after} (WRITTEN)" if after != before else " (unchanged)") + " -->")
    return rc

if __name__ == "__main__":
    sys.exit(main())
