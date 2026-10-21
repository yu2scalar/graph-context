#!/usr/bin/env python3
"""graph_tool.py — protocol-as-code for the graph plugin (D26).

Runs the mechanical parts of the graph-context protocol so that Claude executes them instead of
re-deriving them from prose. Read-only: validate, gate, check, lint-prose,
hydrate --dry-run, backlog. Writing: hydrate (current_node), fold, split, set-status, add-edge, remove-edge, set-current, add-node, add-doc, add-code,
set-next, set-issue, close.

Usage (run from the project root that holds dependency_graph.json):
  graph_tool.py install [--dry-run]           seed dependency_graph.json, append the CLAUDE.md / .gitignore marked blocks, record config.install
  graph_tool.py uninstall [--dry-run]         remove the footprint, restore CLAUDE.md / .gitignore and verify them against config.install
  graph_tool.py validate                      R1 + schema (schema needs `jsonschema`; degrades with a warning)
  graph_tool.py gate                          completion gate (D30), read-only: FAIL (exit 1) on an uncommitted tree, current_node unset
                                              while work is pending, an open issue without owner + trigger, no `next`, validate or
                                              content-layer errors; WARN for unpushed commits (@{u}..HEAD, else last 20) naming no id
  graph_tool.py hydrate <node_id>             hop 0-2 subgraph, components, files, re-examine, capabilities,
                                              staleness (timestamp + content), blast radius; sets current_node
  graph_tool.py check                         growth / fold candidates, staleness (both layers)
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
  graph_tool.py add-edge <src> <kind> <dst>   add one edge (part_of|depends_on|affects|resolves|supersedes|refines), validate
  graph_tool.py remove-edge <src> <kind> <dst>   remove one edge, validate
  graph_tool.py set-current <node|null>       set current_node, validate
  graph_tool.py add-node <id> <type> "<name>" [--part-of P] [--doc PATH ...] [--code PATH ...] [--source-ref ID]
                     [--status S] [--next] [--owner user|claude] [--trigger TEXT]   (issue nodes get issue_status open)
                                              create a node (the last hand-edit of the JSON), validate
  graph_tool.py lint-prose                    version strings and D-ranges in SKILL.md / README / delegates vs plugin.json and the register
  graph_tool.py add-doc <node> <path[#section]>  /  add-code <node> <path>  /  add-test <node> <path>
                                              append to docs / code_targets / test_targets (D42), validate
  graph_tool.py set-source-ref <node> <ID>    give a decision / issue its registry id afterwards; closed_by values move with it (u58)
  graph_tool.py move <node> <new-parent> --reason TEXT          change part_of in one validated step (D43 R1)
  graph_tool.py group <id> <group|feature|function> "<name>" --under <parent> <child> ... --reason TEXT [--class C] [--summary T] [--criterion T]
                                              insert a node between a parent and some children (D43 R2)
  graph_tool.py dissolve <node> --reason TEXT [--map <referrer>=<target> ...] [--docs-to N] [--code-to N] [--tests-to N]
                                              children to the parent, node kept as hidden history; refuses while a reference is unmapped (D43 R3)
  graph_tool.py migrate --add-system --system-name "<name>" [--system-id ID] [--dry-run]   add the apex over every component (D38 P6)
  graph_tool.py hydrate --dry-run <node>      same output, no current_node write
Options: --graph PATH (default dependency_graph.json). --lang ja|en may be given before or after the sub-command;
default = config.interaction_language. Tables stay English; proposal sentences follow --lang.
Every write is appended to .context/graph_tool.log; every run ends with a footer line
`<!-- graph_tool <cmd> @<git head> graph md5 <before>[ -> <after> (WRITTEN)] -->`.
Exit code: 0 ok, 1 = validation errors or bad usage.
"""
import argparse, datetime, hashlib, json, os, re, shutil, subprocess, sys
from collections import Counter, defaultdict

EDGES = ("part_of", "depends_on", "affects", "resolves", "supersedes", "refines")  # refines: decision -> decision it narrows but does not replace (u46); never a fold candidate
WIP = ("PLANNED", "IN_PROGRESS", "BLOCKED", "DONE")
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.normpath(os.path.join(HERE, "..", "schema", "graph_schema.json"))
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

MSG = {
    "growth": {"en": "Proposal: split `{n}` — {c} attached decisions/issues (threshold {t}).",
               "ja": "提案: `{n}` の分割 — 付属する decision/issue が {c} 件（しきい値 {t}）。"},
    "fold": {"en": "Proposal: fold `{v}` into `{s}` ({why}).",
             "ja": "提案: `{v}` を `{s}` に畳み込む（{why}）。"},
    "regroup": {"en": "Proposal: regroup `{n}` — {c} structure children (child_threshold {t}); use `group` / `move` / `dissolve` (D43).",
                "ja": "提案: `{n}` の組み替え — 構造の子が {c} 個（child_threshold {t}）。`group` / `move` / `dissolve` で（D43）。"},
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

LOG_PATH = ".context/graph_tool.log"  # fixed since D30 (config.handover_path retired; migrate --drop-handover-path)

def log_path(g):
    return LOG_PATH

def log_op(g, line, graph_path="dependency_graph.json", before=None, force=False):
    """One line per accepted write. A write that left the graph byte-identical is not logged (G12) unless `force`
    (render: the graph is unchanged but view files were written)."""
    after = md5(graph_path) if os.path.exists(graph_path) else "-"
    if before and before == after and not force:
        return
    lp = log_path(g)
    os.makedirs(os.path.dirname(lp) or ".", exist_ok=True)
    with open(lp, "a") as f:
        f.write(f"{now_iso()} @{git_head()} md5 {before or '?'} -> {after} {line}\n")

# ---------------------------------------------------------------- install / uninstall (R6 footprint, Q-B of plan-protocol-text-7)
TEMPLATE_PATH = os.path.normpath(os.path.join(HERE, "..", "templates", "graph_context.template.json"))
PLUGIN_JSON = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".claude-plugin", "plugin.json"))
CLAUDE_BLOCK = """<!-- graph-context:begin -->
## CRITICAL PROTOCOL (graph-context)
- You must strictly follow the protocol of the `graph` plugin (skill `graph:protocol`, installed via `/plugin`).
- Before modifying any feature or fixing bugs, verify if `dependency_graph.json` exists. If so, run `/graph:hydrate <node_id>` to load 1-hop/2-hop dependencies first.
- When ending a session or pausing work, run `/graph:handover`: record the state on the graph through `graph_tool.py` and finish only when `graph_tool.py gate` prints `RESULT: OK`. No handover document is written; the next session starts with `/graph:hydrate <current_node>`.
- Registry mapping (decision / issue ids \u2192 files) = `dependency_graph.json` \u2192 `config.registries`.
<!-- graph-context:end -->
"""
GITIGNORE_BLOCK = "# graph-context:begin\n.context/\n# graph-context:end\n"
BLOCKS = (("CLAUDE.md", CLAUDE_BLOCK, "<!-- graph-context:begin -->", "<!-- graph-context:end -->", "claude_md_sha256_before"),
          (".gitignore", GITIGNORE_BLOCK, "# graph-context:begin", "# graph-context:end", "gitignore_sha256_before"))

def sha_or_none(path):
    return sha256_of(path) if os.path.exists(path) else None

def git_tracked(path):
    return subprocess.run(["git", "ls-files", "--error-unmatch", path], capture_output=True).returncode == 0

def cmd_install(g, args):
    """Seed the graph, append the two marked blocks, record sha256 snapshots (R6). --dry-run prints the footprint only.
    The block is appended with no blank line before it (only a newline when the file lacks a final one), so uninstall can
    restore the file byte-identical."""
    rows = [("dependency_graph.json", "keep (exists)" if os.path.exists(args.graph) else "create from the template")]
    for f, block, begin, _, _ in BLOCKS:
        cur = open(f, encoding="utf-8").read() if os.path.exists(f) else None
        rows.append((f, "keep (block present)" if cur and begin in cur else ("append the marked block" if cur is not None else "create with the marked block")))
    rows.append((".context/graph_tool.log", "append one line"))
    print("## install" + (" --dry-run" if args.dry_run else "")); print(table(["path", "action"], rows))
    if args.dry_run: print("Nothing written. Ask the user, then run `install` without --dry-run."); return 0
    snap = {k: sha_or_none(f) for f, _, _, _, k in BLOCKS}
    if not os.path.exists(args.graph): shutil.copyfile(TEMPLATE_PATH, args.graph)
    g = load(args.graph); b4 = md5(args.graph)
    for f, block, begin, _, _ in BLOCKS:
        cur = open(f, encoding="utf-8").read() if os.path.exists(f) else ""
        if begin in cur: continue
        open(f, "w", encoding="utf-8").write(cur + ("" if cur == "" or cur.endswith("\n") else "\n") + block)
    if "install" not in g["config"]:
        ver = json.load(open(PLUGIN_JSON)).get("version", "?") if os.path.exists(PLUGIN_JSON) else "?"
        g["config"]["install"] = {"installed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "skill_version": ver,
                                  "claude_md_sha256_before": snap["claude_md_sha256_before"], "gitignore_sha256_before": snap["gitignore_sha256_before"]}
    guarded_save(args.graph, g); log_op(g, "install: graph seeded / marked blocks appended / config.install recorded", args.graph, b4, force=True)
    print("installed. Next: `/graph:init`."); return cmd_validate(g, args)

def strip_block(path, begin, end, before):
    """Remove the marked block (begin..end line incl. its newline); undo the newline install added when the file lacked one.
    Returns the restored text, or None when the file should not exist."""
    txt = open(path, encoding="utf-8").read()
    a = txt.find(begin); b = txt.find(end, a)
    if a < 0 or b < 0: return txt
    b = txt.find("\n", b); b = len(txt) if b < 0 else b + 1
    out = txt[:a] + txt[b:]
    h = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()
    if before is None and out == "": return None
    if before and h(out) != before and out.endswith("\n") and h(out[:-1]) == before: out = out[:-1]
    return out

def cmd_uninstall(g, args):
    """Remove the footprint (R6) and verify CLAUDE.md / .gitignore byte-identical to the install snapshot. --dry-run lists only."""
    inst = g["config"].get("install")
    if not inst: print("ERROR: config.install missing — this graph was not installed by `install`; remove the footprint by hand"); return 1
    files = [args.graph] + sorted({n["file"] for n in g["nodes"].values() if n.get("file") and os.path.exists(n["file"])}) \
            + [v["path"] for v in g["config"].get("views", []) if os.path.exists(v["path"])] + [f for f in (LOG_PATH, ".context/WIP_HANDOVER.md", ".context/WIP_HANDOVER.prev.md") if os.path.exists(f)]
    rows = [(f, "delete file", "tracked" if git_tracked(f) else "untracked") for f in files]
    rows += [(f, "strip marked block", "tracked" if git_tracked(f) else "untracked") for f, *_ in BLOCKS if os.path.exists(f)]
    print("## uninstall" + (" --dry-run" if args.dry_run else "")); print(table(["path", "action", "git"], rows))
    if args.dry_run: print("Nothing removed. Ask the user, then run `uninstall` without --dry-run."); return 0
    res = []
    for f, _, begin, end, key in BLOCKS:
        if not os.path.exists(f): continue
        out = strip_block(f, begin, end, inst.get(key))
        if out is None: os.remove(f); res.append((f, "removed (did not exist before install)"))
        else:
            open(f, "w", encoding="utf-8").write(out)
            ok = sha_or_none(f) == inst.get(key); res.append((f, "restored byte-identical" if ok else "differs from the install snapshot (edits outside the markers are kept)"))
    for f in files: os.remove(f)
    for d in sorted({os.path.dirname(f) for f in files if os.path.dirname(f)}, key=len, reverse=True):
        if os.path.isdir(d) and not os.listdir(d): os.rmdir(d)
    print(table(["path", "result"], res))
    if any(r[2] == "tracked" for r in rows): print("Some removed paths were tracked by git: `git rm` / commit them together.")
    print("The plugin itself: `/plugin uninstall graph@graph-context` (a skill cannot uninstall itself)."); return 0

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
            if k != origin and ns[k]["type"] == "system":  # D38: the apex is always shown, never expanded (it reaches every component)
                continue
            for t, e in adj[k]:
                if t not in hop:
                    hop[t] = (h, f"{k} {e}"); nxt.append(t)
        frontier = nxt
    return hop

def hidden(n):
    """History nodes hidden by default (D31, D37): folded decisions and resolved issues; transferred issues stay visible."""
    return n.get("wip_status") == "FOLDED" or (n["type"] == "issue" and n.get("issue_status") == "resolved")

def attached(ns, f):
    return sorted(k for k, n in ns.items() if n["type"] in ("decision", "issue") and n.get("part_of") == [f] and not hidden(n))

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

# ---------------------------------------------------------------- structure model (D38-D43)
STRUCT_CHILD = ("component", "group", "feature", "function")  # what counts as a structure child (regrouping, leaves)
CONTRACT = ("Responsibility", "Promises", "Invariants", "Boundaries", "Acceptance criteria", "Expectations")  # D41 K3; optional entity sections
SKIP_DIRS = {"build", ".gradle", "node_modules", "target", "dist", ".git", "out", "__pycache__"}

def structure_children(ns, k):
    return sorted(j for j, m in ns.items() if m.get("part_of") == [k] and m["type"] in STRUCT_CHILD and not hidden(m))

def is_leaf(ns, k):
    return ns[k]["type"] in ("feature", "function") and not hidden(ns[k]) and not structure_children(ns, k)

def in_plan(ns, k):
    """Plan steps (and anything under a plan) are work items, not structure: the structure checks skip them."""
    return ns[k]["type"] == "plan" or any(ns[x]["type"] == "plan" for x in parent_chain(ns, k)[0])

def code_leaf(ns, k):
    """D39: a leaf in the structure sense = a feature / function without structure children that holds code."""
    return is_leaf(ns, k) and bool(ns[k].get("code_targets")) and not in_plan(ns, k)

def class_rank(g, k):
    """Rank of the nearest group ancestor (or k itself) that names a configured class; None when unclassified (D38 P3)."""
    ns = g["nodes"]; ranks = {c["id"]: c["rank"] for c in g["config"].get("classes", [])}
    for x in [k] + parent_chain(ns, k)[0]:
        if ns[x]["type"] == "group" and ns[x].get("class") in ranks:
            return ns[x]["class"], ranks[ns[x]["class"]]
    return None

def covered(path, targets):
    return any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)

def list_files(root, exts):
    """File names under a root with the given extensions — listed by name only, never read (S3, D39 G6)."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        out += [os.path.join(d, f) for f in sorted(files) if os.path.splitext(f)[1] in exts]
    return out

def test_kind(g, path):
    import fnmatch
    base = os.path.basename(path)
    for kind in ("helper", "unit", "integration"):
        if any(fnmatch.fnmatch(base, p_) for p_ in g["config"].get("test_kinds", {}).get(kind, [])):
            return kind
    return None

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
    for p in dict.fromkeys(x.split("#", 1)[0] for x in paths):  # docs may carry a section anchor (D41 K2)
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
    if "handover_path" in g.get("config", {}):
        problems.append("config.handover_path is retired (D30: no authored handover) — run `graph_tool.py migrate --drop-handover-path`")
    cur = g.get("current_node")
    if cur is not None and cur not in ns:
        problems.append(f"current_node `{cur}` not in nodes")
    systems = sorted(k for k, n in ns.items() if n.get("type") == "system")
    if len(systems) > 1:
        problems.append(f"more than one system node: {', '.join(systems)} (D38: at most one)")
    class_ids = {c["id"] for c in g.get("config", {}).get("classes", [])}
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
        for e in ("supersedes", "refines"):
            if n.get(e) and n["type"] != "decision":
                problems.append(f"{k}.{e} on a {n['type']} (decision nodes only)")
            for t in n.get(e, []):
                if t in ns and ns[t]["type"] != "decision":
                    problems.append(f"{k}.{e} -> {t} is not a decision")
        par = n.get("part_of", [None])[0]
        ptype = ns[par]["type"] if par in ns else None
        if n["type"] == "component" and (par and ptype != "system" or systems and not par):  # D38 P1
            problems.append(f"component `{k}` must be part_of the system node" + (f" (is part_of `{par}`)" if par else "") if systems else f"component `{k}` has part_of but there is no system node")
        if n["type"] == "requirement" and ptype != "system":
            problems.append(f"requirement `{k}` must be part_of the system node (D38 P2)")
        if n["type"] == "group":
            if ptype not in ("component", "group"):
                problems.append(f"group `{k}` must be part_of a component or a group (D38 P3)")
            if "class" in n and n["class"] not in class_ids:
                problems.append(f"group `{k}`.class `{n['class']}` is not a config.classes id")
        if len(n.get("part_of", [])) > 1:
            problems.append(f"{k}.part_of has {len(n['part_of'])} entries")
        _, cyc = parent_chain(ns, k)
        if cyc:
            problems.append(f"part_of cycle through `{k}`")
        if "source_ref" in n and regs:
            if not any(r["type"] == n["type"] and re.match(r["id_pattern"], n["source_ref"]) for r in regs):
                problems.append(f"{k}.source_ref `{n['source_ref']}` matches no registry of type {n['type']}")
        view_paths = {v["path"] for v in g.get("config", {}).get("views", [])}  # rendered right after an accepted save
        for p in [d.split("#", 1)[0] for d in n.get("docs", [])] + n.get("code_targets", []) + n.get("test_targets", []):  # docs may carry a section anchor (D41 K2)
            if not os.path.exists(p) and p not in view_paths:
                problems.append(f"{k}: path missing `{p}`")
        if n["type"] != "component" and roots:
            for c in n.get("code_targets", []) + n.get("test_targets", []):
                if not any(c.startswith(r) for r in roots):
                    problems.append(f"{k}: code_target `{c}` outside component roots")
        if n["type"] in ("decision", "issue") and not n.get("part_of") and not n.get("affects"):
            warnings.append(f"{k}: {n['type']} attached to nothing (R5)")
        if not n.get("file"):
            warnings.append(f"{k}: no entity file (P1 — run `migrate`)")
        if n.get("file"):
            f = n["file"]
            if not os.path.exists(f):
                problems.append(f"{k}: entity file missing `{f}`")
            else:
                if n.get("sha256") and sha256_of(f) != n["sha256"]:
                    problems.append(f"{k}: entity file `{f}` changed outside graph_tool (sha256 mismatch) — P2; restore it or record the change with `append`")
                copied = [h for h in ("Docs", "Code") if h in entity_sections(f)]
                if copied:
                    problems.append(f"{k}: entity file `{f}` holds sections {copied} that copy graph fields (P1) — run `migrate --strip-graph-copies`")
                if entity_title(f) != n["name"]:
                    problems.append(f"{k}: name differs from the heading of `{f}` (the name is a copy of the heading; use `rename`)")
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

def regroup_candidates(g):
    ns = g["nodes"]; th = g["config"].get("child_threshold", 7)
    return [(k, len(structure_children(ns, k)), th) for k, n in sorted(ns.items()) if not hidden(n) and not in_plan(ns, k) and len(structure_children(ns, k)) > th]

def structure_checks(g):
    """D38-D42 findings as (severity, scope, finding); warnings and information only — nothing here blocks a write.
    Plan steps are work items and are skipped; leaf checks apply to leaves that hold code (D39)."""
    ns = g["nodes"]; cfg = g["config"]; out = []
    live = {k: n for k, n in ns.items() if not hidden(n) and not in_plan(ns, k)}
    for k, n in sorted(live.items()):  # D38 P4: dependency direction against the class ranks
        for t in n.get("depends_on", []):
            a, b = class_rank(g, k), class_rank(g, t) if t in ns else None
            if a and b and a[1] < b[1]:
                out.append(("warn", k, f"depends_on `{t}`: class `{a[0]}` (rank {a[1]}) depends on class `{b[0]}` (rank {b[1]}) — against the rank order (D38 P4)"))
    for k, n in sorted(live.items()):  # D39 G3: code only on leaves
        if n["type"] in ("group", "feature", "function") and n.get("code_targets") and structure_children(ns, k):
            out.append(("warn", k, f"holds code_targets but has structure children — only leaves hold code (D39 G3)"))
        if n["type"] == "group" and n.get("code_targets"):
            out.append(("warn", k, "a group holds code_targets (D39 G3: never)"))
    for k, c, th in regroup_candidates(g):  # D39 G4
        out.append(("proposal", k, f"{c} structure children > child_threshold {th} — propose regrouping (D43)"))
    leaves = [k for k in sorted(live) if code_leaf(ns, k)]
    for k in leaves:  # D41 K3: every leaf needs a contract source
        sec = entity_sections(ns[k]["file"]) if ns[k].get("file") and os.path.exists(ns[k]["file"]) else {}
        resp = sec.get("Responsibility", "")
        if not ns[k].get("docs") and (not resp or resp.startswith(NOT_RECORDED)):
            out.append(("warn", k, "contract missing: no design document points here and the entity has no Responsibility (D41 K3)"))
    exts = set(cfg.get("source_extensions", []))
    if exts:  # D39 G6: code without a leaf, by name only (files are never read)
        owned = [c for n in live.values() if n["type"] != "component" for c in n.get("code_targets", [])]
        troots = cfg.get("test_roots", [])
        loose = [f for r in component_roots(ns) if os.path.isdir(r) for f in list_files(r, exts) if not covered(f, owned) and not covered(f, troots) and not test_kind(g, f)]
        if loose:
            out.append(("info", "code without a leaf", f"{len(loose)} files under component roots (names only, D39 G6): " + ", ".join(loose)))
    if cfg.get("test_roots") and exts:  # D42 T4: tests without a node; helpers are never test_targets
        tt = [t for n in live.values() for t in n.get("test_targets", [])]
        files = [f for r in cfg["test_roots"] if os.path.isdir(r) for f in list_files(r, exts)]
        loose_t = [f for f in files if test_kind(g, f) in ("unit", "integration") and not covered(f, tt)]
        unrule = [f for f in files if test_kind(g, f) is None and not covered(f, tt)]
        if loose_t: out.append(("info", "tests without a node", f"{len(loose_t)} unit / integration test files (D42 T4): " + ", ".join(loose_t)))
        if unrule: out.append(("info", "test files matching no rule", f"{len(unrule)} files under test_roots match no config.test_kinds pattern: " + ", ".join(unrule)))
    tested_docs = {d.split("#", 1)[0] for n in live.values() if n.get("test_targets") for d in n.get("docs", [])}
    for k in leaves:  # D42 T5: a leaf reached by no test
        if not ns[k].get("test_targets") and not any(d.split("#", 1)[0] in tested_docs for d in ns[k].get("docs", [])):
            out.append(("info", k, "no test reaches this leaf (neither its own test_targets nor a test on a node of its documents) (D42 T5)"))
    for k, n in sorted(live.items()):  # D42 T3 / D41 K3: the caller states its expectations
        if n["type"] not in ("group", "feature", "function", "component"): continue
        exp = (entity_sections(n["file"]).get("Expectations", "") if n.get("file") and os.path.exists(n["file"]) else "")
        for t in n.get("depends_on", []):
            if t in ns and ns[t]["type"] in STRUCT_CHILD and not in_plan(ns, t) and not n.get("docs") and t not in exp:
                out.append(("warn", k, f"depends_on `{t}` but states no expectation of it (no design document, no `{t}` in an Expectations section) (D42 T3)"))
    for k, n in sorted(live.items()):  # D42 T5: contract newer than its tests
        if n.get("test_targets"):
            c = newest(n.get("docs") or ([n["file"]] if n.get("file") else [])); t = newest(n["test_targets"])
            if c[0] and t[0] and newer(c[0], t[0]):
                out.append(("warn", k, f"contract source changed {c[0]} ({c[1]}) after its tests {t[0]} ({t[1]}) — tests may lag the contract (D42 T5)"))
    return out

def fold_candidates(g):
    ns = g["nodes"]; ins = in_edges(ns); out = []
    for k, n in ns.items():
        if n.get("wip_status") in ("IN_PROGRESS", "BLOCKED", "FOLDED") or not ins[k]:
            continue
        if n["type"] == "decision" and all(e == "supersedes" for _, e in ins[k]):
            out.append((k, ins[k][0][0], "superseded, no other live in-edges"))
        # resolved issues need no fold: they are hidden by issue_status (D37)
    return out

# ---------------------------------------------------------------- entities (plan integrity-store P1–P5)
ENTITY_TYPES = ("decision", "issue", "plan", "rule", "requirement")  # created with `add`; structure nodes get their file via `add-node` / `migrate` / `attach`
ENTITY_DIR = "docs/entities"
HEADINGS = {  # required sections per entity type, in order; "Log" is always last and append-only
    "decision": ["Statement", "Public summary", "User's words", "Reason", "Date"],
    "issue": ["Text", "Source"],
    "plan": ["Goal", "Approval"],
    "rule": ["Statement", "Source"],
    "system": ["Purpose", "Premises", "Values"], "requirement": ["Statement", "Source"], "group": ["Summary", "Criterion"],  # D38
    "component": ["Summary"], "feature": ["Summary"], "function": ["Summary"], "task": ["Summary"],
}
NOT_RECORDED = "(not recorded in the source)"
ENTITY_MARK = "<!-- entity {id} · {type} · written by graph_tool; do not edit by hand — use `graph_tool.py append` · when a heading appears more than once, the LAST section with that heading is the current one -->"

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

def render_entity(nid, ntype, title, sections, when, how="add"):
    lines = [ENTITY_MARK.format(id=nid, type=ntype), f"# {nid} — {title}", ""]
    for h in HEADINGS[ntype]:
        lines += [f"## {h}", sections[h].strip(), ""]
    for h, t in sections.items():
        if h not in HEADINGS[ntype] and h != "Log":
            lines += [f"## {h}", t.strip(), ""]
    lines += ["## Log", f"- {when} created by graph_tool {how}", ""]
    return "\n".join(lines)

def entity_title(path):
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^# (\S+) — (.+?)\s*$", line)
        if m: return m.group(2)
    return None

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
        if k in m.get("supersedes", []) and ns[k].get("wip_status") == "FOLDED":
            return j
    return None

def decision_status(ns, k):
    n = ns[k]; st = n.get("wip_status")
    if st == "FOLDED":
        by = folded_into(ns, k)
        return f"folded into {ns[by].get('source_ref', by)}" if by else "folded"
    if st == "PLANNED": return "decided, not yet implemented"
    if st == "IN_PROGRESS": return "in progress"
    if st == "BLOCKED": return "blocked"
    return "active"

def render_view(g, kind):
    ns = g["nodes"]; out = [VIEW_MARK.format(kind=kind), ""]
    sec = lambda k: entity_sections(ns[k]["file"]) if ns[k].get("file") and os.path.exists(ns[k]["file"]) else {}
    rel = lambda k: "; ".join(x for x in (("supersedes " + ", ".join(ns[k]["supersedes"])) if ns[k].get("supersedes") else "",
                                          ("refines " + ", ".join(ns[k]["refines"])) if ns[k].get("refines") else "",
                                          ("resolves " + ", ".join(ns[k]["resolves"])) if ns[k].get("resolves") else "") if x) or "—"
    ref = lambda k: ns[k].get("source_ref", k)
    decs = sorted((k for k, n in ns.items() if n["type"] == "decision"), key=lambda k: (re.sub(r"\d", "", ref(k)), int(re.sub(r"\D", "", ref(k)) or 0)))
    if kind == "decisions":
        out += ["# Decision register (generated)", "", "| id | decision | supersedes / resolves | status | entity |", "|---|---|---|---|---|"]
        for k in decs:
            out.append(f"| {ref(k)} | {first_line(sec(k).get('Statement')) if sec(k) else ns[k]['name']} | {rel(k)} | {decision_status(ns, k)} | {ns[k].get('file', '(no entity file yet)')} |")
    elif kind == "public-decisions":
        out += ["# Public decision register (generated from each decision's Public summary)", "", "| id | Decision | Supersedes / resolves | Status |", "|----|----------|-----------------------|--------|"]
        pub_files = [r["file"] for r in g["config"].get("registries", []) if r.get("public_column")]
        pub_col = {r["file"]: r["public_column"] for r in g["config"].get("registries", []) if r.get("public_column")}
        rows_ = []
        for k in decs:
            s_ = sec(k)
            if not s_: continue  # no entity file yet: nothing public to show
            rows_.append((ref(k), f"| {ref(k)} | {first_line(s_.get('Public summary'))} | {rel(k)} | {decision_status(ns, k)} |"))
            for fid in [x for x in ns[k].get("folded", []) if x not in {m.get("source_ref") for m in ns.values()}]:  # legacy folded[] ids without a node (until restore-folds)
                txt = "—"
                for m in re.finditer(r"^- " + re.escape(fid) + r" `([^`]+):\d+`\n  (.+)$", s_.get("Folded", ""), re.M):
                    if m.group(1) in pub_files:
                        cells = split_cells(m.group(2)); c = pub_col[m.group(1)] - 1
                        if c < len(cells): txt = cells[c]
                rows_.append((fid, f"| {fid} | {txt} | — | folded into {ref(k)} |"))
        key = lambda x: (re.sub(r"\d", "", x[0]), int(re.sub(r"\D", "", x[0]) or 0))
        out += [r for _, r in sorted(rows_, key=key)]
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
            if ns[k].get("wip_status") != "FOLDED": by[(ns[k].get("part_of") or ["(unattached)"])[0]].append(k)
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
    comp = next((x for x in chain if ns[x]["type"] == "component"), None)  # under a system the top of the chain is the system (D38)
    if comp:
        return comp
    if ns[k]["type"] in ("system", "requirement") or (chain and ns[chain[-1]]["type"] == "system"):
        return "(system)"
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

def system_table(ns):
    """D38: the apex and its requirements, shown in every hydrate next to the components (the apex is never expanded by hops)."""
    rows = []
    for k, n in sorted(ns.items(), key=lambda x: (x[1]["type"] != "system", x[0])):
        if n["type"] in ("system", "requirement") and not hidden(n):
            rows.append((k, n["type"], n["name"], ", ".join(f"`{d}`" for d in n["docs"]) or "—", ", ".join(n.get("affects", [])) or "—", n.get("file", "—")))
    return table(["id", "type", "name", "docs", "affects", "entity (read it)"], rows) if rows else None

SUBGRAPH_LEGEND = "Legend: one row per node; hop = shortest distance over all edge kinds in both directions (`rev-` = traversed against the arrow); `path from origin` = the first path found (BFS, ids sorted), other paths may exist; `(index)` = group/feature/function that has structure children; the system node is reached but never expanded (D38)."

def subgraph_table(ns, hop, why_col=False):
    rows = []
    for k, (h, path) in sorted(hop.items(), key=lambda x: (x[1][0], x[0])):
        is_index = ns[k]["type"] in ("group", "feature", "function") and bool(structure_children(ns, k))
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
    hop_all = hops(ns, origin)
    hist = {k for k in hop_all if k != origin and hidden(ns[k])}
    hop = hop_all if getattr(args, "history", False) else {k: v for k, v in hop_all.items() if k not in hist}
    print(f"## Impact Assessment Checklist — {origin}\n")
    st_ = system_table(ns)
    if st_: print("### System and requirements (always shown — D38)"); print(st_); print()
    print("### Components (always shown — R7)"); print(components_table(ns)); print()
    print("### Backlog (graph-wide, always shown — D33)"); print(backlog_md(g)); print()
    print("### Subgraph"); print(subgraph_table(ns, hop)); print(SUBGRAPH_LEGEND)
    if hist and not getattr(args, "history", False):
        nf = sum(1 for k in hist if ns[k]["type"] == "decision"); ni = len(hist) - nf
        print(f"History hidden (D31, D37): {len(hist)} nodes in hops 0–2 — {nf} folded decisions, {ni} resolved issues; run with `--history` to show them.")
    print()
    rows = []
    for k in sorted(hop, key=lambda x: (hop[x][0], x)):
        if ns[k].get("file"):  # P1: the node's own text — read it first
            f = ns[k]["file"]
            st = "MISSING" if not os.path.exists(f) else ("exists" if sha256_of(f) == ns[k].get("sha256") else "exists — CHANGED OUTSIDE graph_tool")
            rows.append((k, "entity (the node's text)", f"`{f}`", st))
        for kind in ("docs", "code_targets", "test_targets"):
            for p in ns[k].get(kind, []):
                fp = p.split("#", 1)[0]
                st = "MISSING" if not os.path.exists(fp) else ("exists (dir: read every file under it)" if os.path.isdir(fp) else "exists" + (" (read the anchored section)" if "#" in p else ""))
                rows.append((k, kind, f"`{p}`", st))
        if "source_ref" in ns[k] and not ns[k].get("file"):  # with an entity file the registry rows are already in its Copies
            regs = [r for r in g["config"].get("registries", []) if r["type"] == ns[k]["type"] and re.match(r["id_pattern"], ns[k]["source_ref"])]
            for r in regs:
                rows.append((k, "registry entry", f"`{ns[k]['source_ref']}` in `{r['file']}`", "exists" if os.path.exists(r["file"]) else "MISSING"))
    print("### Files loaded (read every `exists` row in full before ticking the first box)"); print(table(["node", "kind", "path", "status"], rows)); print()
    print("### Constraints inherited from decisions")
    dec = [k for k in hop if ns[k]["type"] == "decision"]
    for k in sorted(dec, key=lambda x: (hop[x][0], x)):
        n = ns[k]; st_ = entity_sections(n["file"]).get("Statement", "") if n.get("file") and os.path.exists(n["file"]) else ""
        st_ = re.sub(r"\s+", " ", st_)[:220] if st_ and not st_.startswith(NOT_RECORDED) else n["name"]
        print(f"- hop {hop[k][0]} `{k}` ({n.get('source_ref', '—')}): {st_}" + (f" — folded: {', '.join(n['folded'])}" if n.get("folded") else ""))
    if not dec: print("- none")
    print()
    print("### Decisions to re-examine (hop 0–1 decisions: affects ∪ resolves ∪ supersedes ∪ superseded-by ∪ refines ∪ refined-by ∪ same-parent decisions)")
    adj = adjacency(ns); rows = []
    for k in sorted(hop, key=lambda x: (hop[x][0], x)):
        if hop[k][0] <= 1 and ns[k]["type"] == "decision":
            n = ns[k]
            rel = set(n.get("affects", [])) | set(n.get("resolves", [])) | set(n.get("supersedes", [])) | set(n.get("refines", [])) | {s for s, e in adj[k] if e in ("rev-supersedes", "rev-refines")}
            parent = n.get("part_of", [None])[0]
            sib = sorted(j for j, m in ns.items() if m["type"] == "decision" and m.get("part_of") == [parent] and j != k)
            rows.append((k, n.get("source_ref", "—"), ", ".join(sorted(rel)) or "—", f"{len(sib)} siblings under `{parent}`"))
    print(table(["decision", "registry id", "affects/resolves/supersedes/refines", "same-parent"], rows)); print()
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
    elif g.get("current_node") == origin:  # u48: a resume must leave a clean tree clean — no graph write, no log line
        print(f"\n(current_node already `{origin}`: nothing written)")
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
    for k, c, t in regroup_candidates(g):
        lines.append(MSG["regroup"][lang].format(n=k, c=c, t=t))
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
    print("\n### Structure model (D38–D42: rank direction, code only on leaves, regrouping, contracts, code / tests without a node, expectations, tests behind contracts)")
    print(table(["severity", "scope", "finding"], structure_checks(g)))
    print("\n### Proposals (" + args.lang + ")")
    for l in proposals(g, args.lang): print("- " + l)
    return 0

GATE_NO_UPSTREAM_COMMITS = 20

def git_lines(*cmd):
    r = subprocess.run(["git", *cmd], capture_output=True, text=True)
    return r.returncode, [l for l in r.stdout.splitlines() if l.strip()]

def link_set():
    """Commits the commit-link warning checks (plan-gate Qb): unpushed commits @{u}..HEAD; the last 20 when there is no upstream."""
    rc, out = git_lines("log", "--format=%h %s", "@{u}..HEAD")
    if rc == 0: return "unpushed commits (@{u}..HEAD)", out
    rc, out = git_lines("log", "--format=%h %s", f"-{GATE_NO_UPSTREAM_COMMITS}")
    return f"no upstream: last {GATE_NO_UPSTREAM_COMMITS} commits", out if rc == 0 else []

def cmd_gate(g, args):
    """Completion gate (D30): read-only; FAIL (exit 1) when the pause is not complete. Writes nothing, logs nothing."""
    ns = g["nodes"]; rows = []  # (result, check, detail)
    def add(ok, check, detail, warn=False): rows.append(("PASS" if ok else ("WARN" if warn else "FAIL"), check, detail))
    rc, dirty = git_lines("status", "--porcelain")
    add(rc == 0 and not dirty, "working tree committed", "clean" if rc == 0 and not dirty else ("not a git repository" if rc else f"{len(dirty)} uncommitted paths: " + ", ".join(l[3:] for l in dirty[:8]) + (" …" if len(dirty) > 8 else "")))
    pending = sorted(k for k, n in ns.items() if not hidden(n) and n.get("wip_status") in ("PLANNED", "IN_PROGRESS", "BLOCKED"))
    cur = g.get("current_node")
    if pending:
        add(cur is not None and cur in ns, "current_node set", f"`{cur}`" if cur in ns else (f"`{cur}` not in nodes" if cur else f"unset while {len(pending)} nodes are PLANNED / IN_PROGRESS / BLOCKED"))
    else:
        add(cur is None or cur in ns, "current_node set", f"`{cur}` (no pending work)" if cur else "null (no pending work)")
    bare = sorted(k for k, n in ns.items() if n["type"] == "issue" and n.get("issue_status", "open") == "open" and not (n.get("owner") and n.get("trigger")))
    add(not bare, "open issues have owner + trigger", "all" if not bare else "missing on " + ", ".join(bare))
    nxt = sorted(k for k, n in ns.items() if n.get("next") and not hidden(n))
    add(bool(nxt) or not pending, "a next item exists", ", ".join(nxt) if nxt else ("none, and no pending work" if not pending else f"none while {len(pending)} nodes are pending — run `set-next`"))
    problems, _ = validate(g)
    add(not problems, "validate (R1, schema, entity files, views)", "OK" if not problems else f"{len(problems)} errors: " + "; ".join(problems[:3]) + (" …" if len(problems) > 3 else ""))
    cerr = [f for f in content_checks(g) if f[0] == "error"]
    add(not cerr, "content layer (D24)", "no errors" if not cerr else "; ".join(f"{f[1]}: {f[2]}" for f in cerr[:3]))
    what, commits = link_set()
    ids = set(ns) | {n["source_ref"] for n in ns.values() if n.get("source_ref")}
    idre = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, ids), key=len, reverse=True)) + r")(?![\w-])", re.I) if ids else None
    unlinked = [c for c in commits if not (idre and idre.search(c.split(" ", 1)[1] if " " in c else ""))]
    add(not unlinked, "commits name a node or registry id", f"{what}: {len(commits)} checked" + ("" if not unlinked else f", unlinked: " + "; ".join(unlinked[:5])), warn=True)
    print("## gate (D30 completion gate — read-only)")
    print(table(["result", "check", "detail"], rows))
    fail = any(r[0] == "FAIL" for r in rows)
    print("RESULT:", "FAIL" if fail else "OK")
    if not fail: print(f"The pause is complete: the successor runs `/graph:hydrate {cur}`." if cur else "The pause is complete: no pending work.")
    return 1 if fail else 0

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

def cmd_add_path(g, args):
    ns = g["nodes"]; field = {"add-doc": "docs", "add-code": "code_targets", "add-test": "test_targets"}[args.cmd]
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    if not os.path.exists(args.path.split("#", 1)[0]): print(f"ERROR: path `{args.path}` does not exist"); return 1
    if field == "test_targets" and test_kind(g, args.path) == "helper": print(f"ERROR: `{args.path}` matches a helper rule (config.test_kinds.helper); helpers are never test_targets (D42 T4)"); return 1
    lst = ns[args.node].setdefault(field, [])
    if args.path not in lst: lst.append(args.path)
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"{args.cmd} {args.node} {args.path}", args.graph, b4)
    print(f"{args.node}.{field} += {args.path}")
    return cmd_validate(g, args)

def cmd_add_node(g, args):
    ns = g["nodes"]
    if args.id in ns: print(f"ERROR: `{args.id}` exists"); return 1
    if not ID_RE.match(args.id): print(f"ERROR: bad id `{args.id}`"); return 1
    if args.type not in ("system", "requirement", "component", "group", "feature", "function", "decision", "issue", "task"): print("ERROR: bad type"); return 1
    n = {"id": args.id, "type": args.type, "name": args.name, "docs": args.doc or [], "code_targets": args.code or []}
    if getattr(args, "test", None): n["test_targets"] = args.test
    if getattr(args, "cls", None):
        if args.type != "group": print("ERROR: --class is for group nodes only"); return 1
        n["class"] = args.cls
    given = {}
    for spec in getattr(args, "section", None) or []:
        if "=" not in spec: print(f"ERROR: --section wants Heading=text, got `{spec[:40]}`"); return 1
        h, t = spec.split("=", 1); given[h.strip()] = t
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
    path = os.path.join(ENTITY_DIR, f"{args.id}.md")  # every node has its entity file (P1); structure text = --summary or NOT_RECORDED
    if not os.path.exists(path):
        heads = HEADINGS.get(args.type, ["Summary"])
        sec = {h: NOT_RECORDED for h in heads}
        if args.type in ("decision", "issue") and args.source_ref:  # u49: registry-backed node — text copied verbatim, as migrate does
            reg, differ = migrate_sections(g, args.id, scan_rows(g))
            if reg.get("Source" if args.type == "issue" else "Primary source") == NOT_RECORDED:
                del ns[args.id]; print(f"ERROR: no registry row for `{args.source_ref}` in config.registries files — add the row first, or use `add` without --source-ref"); return 1
            sec.update(reg)
            if differ: print(f"note: copies of {args.source_ref} differ ({', '.join(differ)}) — review, then `append {args.id}`")
        elif getattr(args, "summary", None): sec["Summary" if "Summary" in heads else heads[0]] = args.summary
        sec.update({h: t for h, t in given.items() if t.strip()})  # --section: required headings and optional contract sections (D41 K3)
        os.makedirs(ENTITY_DIR, exist_ok=True)
        open(path, "w", encoding="utf-8").write(render_entity(args.id, args.type, args.name, sec, now_iso(), how="add-node"))
        n["file"] = path; n["sha256"] = sha256_of(path)
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        if n.get("file") and os.path.exists(n["file"]): os.remove(n["file"])
        raise
    log_op(g, f"add-node {args.id} ({args.type}) part_of={args.part_of}", args.graph, b4)
    print(f"added `{args.id}` ({args.type})")
    return cmd_validate(g, args)

def cmd_fold(g, args):
    ns = g["nodes"]; v, s = args.victim, args.survivor
    for x in (v, s):
        if x not in ns: print(f"ERROR: `{x}` not in nodes"); return 1
    if ns[s]["type"] != "decision": print("ERROR: survivor must be a decision"); return 1
    if ns[v].get("wip_status") in ("IN_PROGRESS", "BLOCKED"): print(f"ERROR: `{v}` is {ns[v]['wip_status']}; refuse to fold"); return 1
    vic, sur = ns[v], ns[s]
    if vic["type"] != "decision": print("ERROR: only decisions are folded; a resolved issue is already hidden (D37)"); return 1
    if vic.get("wip_status") == "FOLDED": print(f"ERROR: `{v}` is already folded"); return 1
    # D31: hide, do not delete — the victim stays as a history node under the survivor
    vic["wip_status"] = "FOLDED"
    if v not in sur.setdefault("supersedes", []): sur["supersedes"].append(v)
    for a in vic.get("affects", []):  # the survivor inherits the constraints so drift tracking stays complete
        if a != s and a not in sur.setdefault("affects", []): sur["affects"].append(a)
    if g.get("current_node") == v: g["current_node"] = s
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"fold {v} -> {s} (hidden: {v}.wip_status FOLDED, {s}.supersedes {v})", args.graph, b4)
    if vic.get("file"): pass  # the entity file is unchanged; history is the node + edge
    print(f"folded `{v}` into `{s}` — kept as a hidden history node")
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

def cmd_remove_edge(g, args):
    """Remove one edge (e.g. a supersedes that only ever meant refines, u46), then validate."""
    ns = g["nodes"]
    if args.kind not in EDGES: print(f"ERROR: kind must be one of {EDGES}"); return 1
    if args.src not in ns or args.dst not in ns.get(args.src, {}).get(args.kind, []): print(f"ERROR: no edge {args.src}.{args.kind} -> {args.dst}"); return 1
    ns[args.src][args.kind].remove(args.dst)
    if not ns[args.src][args.kind]: del ns[args.src][args.kind]
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"remove-edge {args.src}.{args.kind} -> {args.dst}", args.graph, b4)
    print(f"removed {args.src}.{args.kind} -> {args.dst}")
    return cmd_validate(g, args)

def cmd_add_edge(g, args):
    ns = g["nodes"]
    if args.kind not in EDGES: print(f"ERROR: kind must be one of {EDGES}"); return 1
    for x in (args.src, args.dst):
        if x not in ns: print(f"ERROR: `{x}` not in nodes"); return 1
    lst = ns[args.src].setdefault(args.kind, [])
    if args.dst in lst: print(f"unchanged: {args.src}.{args.kind} -> {args.dst} already exists"); return 0
    lst.append(args.dst)
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

def cmd_attach(g, args):
    """Migration: give an existing decision / issue / plan / rule node its entity file (P1). `--as-plan` turns a
    feature / function node that represents a plan into a `plan` node (P3b). The text comes from --section only."""
    ns = g["nodes"]
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    n = ns[args.node]
    if n.get("file") and args.as_plan and n["type"] in ("feature", "function"):  # convert: add the plan sections to the existing file
        sections = dict(sp_.split("=", 1) for sp_ in (args.section or []) if "=" in sp_)
        missing = [h for h in HEADINGS["plan"] if not sections.get(h, "").strip()]
        if missing: print(f"ERROR: plan needs sections {missing}"); return 1
        f = n["file"]
        if sha256_of(f) != n.get("sha256"): print(f"ERROR: `{f}` changed outside graph_tool"); return 1
        old = open(f, encoding="utf-8").read()
        for h, t in sections.items(): append_section(f, h.strip(), t)
        txt = open(f, encoding="utf-8").read().rstrip("\n") + f"\n- {now_iso()} converted to plan by attach --as-plan\n"
        txt = re.sub(r"^(<!-- entity \S+ · )\w+( ·)", r"\1plan\2", txt, count=1, flags=re.M)
        open(f, "w", encoding="utf-8").write(txt); n["type"] = "plan"; n["sha256"] = sha256_of(f)
        b4 = md5(args.graph)
        try:
            guarded_save(args.graph, g)
        except WriteRefused:
            open(f, "w", encoding="utf-8").write(old); raise
        log_op(g, f"attach {args.node} --as-plan (existing file)", args.graph, b4); print(f"converted `{args.node}` to plan"); return cmd_validate(g, args)
    if n.get("file"): print(f"ERROR: `{args.node}` already has {n['file']} — use append"); return 1
    if args.as_plan:
        if n["type"] not in ("feature", "function"): print("ERROR: --as-plan converts a feature / function node only"); return 1
        n["type"] = "plan"
    if n["type"] not in ENTITY_TYPES: print(f"ERROR: `{args.node}` is a {n['type']}; entity files are for {ENTITY_TYPES}"); return 1
    sections = {}
    for spec in args.section or []:
        if "=" not in spec: print(f"ERROR: --section wants Heading=text, got `{spec[:40]}`"); return 1
        h, t = spec.split("=", 1); sections[h.strip()] = t
    missing = [h for h in HEADINGS[n["type"]] if not sections.get(h, "").strip()]
    if missing: print(f"ERROR: {n['type']} needs sections {missing}"); return 1
    path = os.path.join(ENTITY_DIR, f"{args.node}.md")
    if os.path.exists(path): print(f"ERROR: `{path}` already exists"); return 1
    os.makedirs(ENTITY_DIR, exist_ok=True)
    title = n["name"]
    open(path, "w", encoding="utf-8").write(render_entity(args.node, n["type"], title, sections, now_iso()))
    n["file"] = path; n["sha256"] = sha256_of(path)
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        os.remove(path); raise
    log_op(g, f"attach {args.node} ({n['type']}) file={path}" + (" (converted to plan)" if args.as_plan else ""), args.graph, b4)
    print(f"attached {path} to `{args.node}`")
    return cmd_validate(g, args)

ROW_RE = r"^\| {id} \|"

def split_cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]

def scan_rows(g):
    """id -> [(file, line_no, row)] over registry files + docs_scope, excluding generated/entity files. Deterministic order."""
    files = []
    for r in g["config"].get("registries", []):
        if r["file"] not in files: files.append(r["file"])
    import glob
    for pat in g["config"].get("docs_scope", []):
        for f in sorted(glob.glob(pat, recursive=True)):
            if f not in files and not f.startswith((ENTITY_DIR + "/", "docs/views/")): files.append(f)
    rows = defaultdict(list)
    for f in files:
        if not os.path.exists(f): continue
        for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            m = re.match(r"^\| ([A-Za-z]+-?\d+) \|", line) or re.match(r"^- ([A-Z]+-?\d+) ", line)  # table row or list item
            if m: rows[m.group(1)].append((f, i, line.rstrip("\n")))
    return rows

def migrate_sections(g, k, rows):
    """Deterministic sections for node k (no judgment): primary copy = first registry in config order whose pattern matches
    and whose file holds a row for the id; every copy verbatim with file:line; folded ids' rows; quotes 「…」 collected."""
    n = g["nodes"][k]; regs = g["config"].get("registries", []); t = n["type"]
    if t not in ("decision", "issue"):
        sec = {"Summary": NOT_RECORDED + " — the name is the heading"}  # docs / code_targets stay in the graph only (P1)
        if t == "plan": sec.update({"Goal": NOT_RECORDED, "Approval": NOT_RECORDED})
        if t == "rule": sec.update({"Statement": n["name"], "Source": NOT_RECORDED})
        return sec, None
    ref = n.get("source_ref"); copies = rows.get(ref, []) if ref else []
    primary = None
    for r in regs:
        if r["type"] == t and ref and re.match(r["id_pattern"], ref):
            hit = [c for c in copies if c[0] == r["file"]]
            if hit: primary = (r, hit[0]); break
    public = NOT_RECORDED
    for r in regs:
        if r.get("public_column") and ref and re.match(r["id_pattern"], ref):
            hit = [c for c in copies if c[0] == r["file"]]
            if hit:
                cells = split_cells(hit[0][2]); col = r["public_column"] - 1
                if col < len(cells): public = cells[col]
                break
    prim_txt = primary[1][2] if primary else NOT_RECORDED
    prim_src = f"`{primary[1][0]}:{primary[1][1]}` (first matching registry in config order)" if primary else NOT_RECORDED
    quotes = []
    for c in copies:
        for q in re.findall(r"「[^」]+」", c[2]):
            if q not in quotes: quotes.append(q)
    copy_txt = "\n".join(f"- `{f}:{i}`\n  {row}" for f, i, row in copies) or NOT_RECORDED
    folded = []
    for fid in n.get("folded", []):
        for f, i, row in rows.get(fid, []):
            folded.append(f"- {fid} `{f}:{i}`\n  {row}")
    if t == "decision":
        sec = {"Statement": prim_txt, "Public summary": public, "User's words": " ".join(quotes) or NOT_RECORDED,
               "Reason": NOT_RECORDED + " — see the copies", "Date": NOT_RECORDED, "Primary source": prim_src, "Copies": copy_txt}
    else:
        sec = {"Text": prim_txt + ("\n\n(The row's status / owner / trigger columns are historical; the current state is on the node.)" if primary else ""),
               "Source": prim_src, "Copies": copy_txt}
    if folded: sec["Folded"] = "\n".join(folded)
    differ = None
    if len(copies) > 1:
        texts = {re.sub(r"\W+", "", " ".join(split_cells(c[2])[1:2]).lower()) for c in copies}
        if len(texts) > 1: differ = [f"{f}:{i}" for f, i, _ in copies]
    return sec, differ

def append_section(path, heading, text):
    """Add a new section before `## Log` (content is only ever added, never changed)."""
    t = open(path, encoding="utf-8").read(); i = t.rfind("\n## Log")
    open(path, "w", encoding="utf-8").write(t[:i] + f"\n## {heading}\n{text.rstrip()}\n" + t[i:])

def demote(doc):
    """Plan document body inside an entity: every heading two levels deeper, so it cannot collide with entity sections."""
    return "\n".join(("##" + l) if re.match(r"^#{1,4} ", l) else l for l in doc.splitlines())

def migrate_plans(g, args):
    import glob
    ns = g["nodes"]; pats = g["config"].get("plan_docs", ["docs/plan-*.md", "docs/apply-*.md"])
    docs = sorted({f for p_ in pats for f in glob.glob(p_)})
    report, moved = [], []
    for d in docs:
        users = sorted(k for k, n in ns.items() if d in n.get("docs", []))
        owners = [k for k in users if ns[k]["type"] == "plan" and ns[k].get("file")]
        body = open(d, encoding="utf-8").read()
        m = re.search(r"^# (.+)$", body, re.M); title = m.group(1).strip() if m else os.path.basename(d)
        if len(owners) == 1:
            target = owners[0]; how = f"added as section to existing plan `{target}`"
        else:
            target = re.sub(r"[^a-z0-9_-]", "-", os.path.splitext(os.path.basename(d))[0].lower())
            how = "new plan entity"
        report.append((d, target, how, len(users)))
        if args.dry_run: continue
        if how == "new plan entity":
            if target in ns: print(f"ERROR: node `{target}` exists"); return 1
            comps = Counter(component_of(ns, k) for k in users)
            part = sorted(comps.items(), key=lambda x: (-x[1], x[0]))[0][0] if comps else None
            path = os.path.join(ENTITY_DIR, f"{target}.md")
            sec = {"Goal": NOT_RECORDED + " — see Document", "Approval": NOT_RECORDED + " — see Document",
                   "Document": f"(moved verbatim from `{d}` by `migrate --plans`; headings demoted two levels)\n\n" + demote(body)}
            open(path, "w", encoding="utf-8").write(render_entity(target, "plan", title, sec, now_iso(), how="migrate --plans"))
            n = {"id": target, "type": "plan", "name": title, "docs": [], "code_targets": [], "file": path, "sha256": sha256_of(path)}
            if part and part in ns: n["part_of"] = [part]
            ns[target] = n
        else:
            path = ns[target]["file"]
            append_section(path, f"Document (moved from {d})", demote(body)); ns[target]["sha256"] = sha256_of(path)
        for k in users:
            ns[k]["docs"] = [path if x == d else x for x in ns[k]["docs"]]
            if ns[k]["docs"].count(path) > 1: ns[k]["docs"] = list(dict.fromkeys(ns[k]["docs"]))
            if k == target: ns[k]["docs"] = [x for x in ns[k]["docs"] if x != path]
        for r in g["config"].get("registries", []):
            if r["file"] == d: r["file"] = path
        moved.append(d)
    print("## migrate --plans" + (" --dry-run" if args.dry_run else ""))
    print(table(["document", "plan node", "how", "nodes referring to it"], report))
    if args.dry_run: return 0
    for d in moved: os.remove(d)
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        print("write refused: restore the documents with `git checkout -- " + " ".join(moved) + "` and the entity files with git"); raise
    log_op(g, f"migrate --plans: {len(moved)} plan documents moved into plan entities: " + ", ".join(moved), args.graph, b4)
    return cmd_validate(g, args)

def retire_registry(g, args):
    """A hand-written registry whose rows are already in entity Copies: move its remaining lines that mention an id into
    entity logs (first mentioned id holds the line, the others get a pointer), repoint config.registries, remove the file."""
    ns = g["nodes"]; f = args.retire_registry
    if not os.path.exists(f): print(f"ERROR: {f} not found"); return 1
    by_ref = {n.get("source_ref"): k for k, n in ns.items() if n.get("source_ref")}
    lines = open(f, encoding="utf-8").read().splitlines(); moves = []
    for i, line in enumerate(lines, 1):
        if line.startswith("|"): continue  # table rows are already verbatim in each entity's Copies (migrate)
        ids = [x for x in dict.fromkeys(re.findall(r"(?<![\w-])([A-Z]+-?\d+)(?![\w-])", line)) if x in by_ref]
        if ids: moves.append((i, line, [by_ref[x] for x in ids]))
    unmatched_rows = [l for l in lines if l.startswith("| ") and re.match(r"^\| ([A-Za-z]+-?\d+) \|", l) and re.match(r"^\| ([A-Za-z]+-?\d+) \|", l).group(1) not in by_ref]
    print(f"## migrate --retire-registry {f}" + (" --dry-run" if args.dry_run else ""))
    print(table(["line", "held by", "pointers in", "text"], [(i, t[0], ", ".join(t[1:]) or "—", l[:70]) for i, l, t in moves]))
    if unmatched_rows: print(f"WARNING: {len(unmatched_rows)} rows with ids that have no node — not retired"); return 1
    views = {v["kind"]: v["path"] for v in g["config"].get("views", [])}
    for r in g["config"].get("registries", []):
        if r["file"] == f and ("issues" if r["type"] == "issue" else "decisions") not in views:
            print(f"ERROR: no `{'issues' if r['type'] == 'issue' else 'decisions'}` view in config.views to take over `{f}` — add one first"); return 1
    if args.dry_run: return 0
    touched = sorted({ns[k]["file"] for _, _, t in moves for k in t})
    backup = {fp: open(fp, encoding="utf-8").read() for fp in touched}
    backup_graph = json.loads(json.dumps(g))
    for i, line, targets in moves:
        holder = targets[0]
        for k in targets:
            fp = ns[k]["file"]
            if sha256_of(fp) != ns[k]["sha256"]: print(f"ERROR: {fp} changed outside graph_tool"); return 1
            txt = open(fp, encoding="utf-8").read().rstrip("\n")
            txt += (f"\n- moved from `{f}:{i}` (retired registry): {line.lstrip('- ').strip()}\n" if k == holder else f"\n- see the log of `{holder}` for `{f}:{i}` (retired registry, note about this entity too)\n")
            open(fp, "w", encoding="utf-8").write(txt); ns[k]["sha256"] = sha256_of(fp)
    new_home = None
    for r in g["config"].get("registries", []):
        if r["file"] == f:
            new_home = views.get("issues" if r["type"] == "issue" else "decisions", r["file"]); r["file"] = new_home
    for n in ns.values():  # nodes that listed the retired file now point at the generated view
        if f in n.get("docs", []):
            n["docs"] = list(dict.fromkeys(new_home if x == f else x for x in n["docs"])) if new_home else [x for x in n["docs"] if x != f]
    registry_text = open(f, encoding="utf-8").read(); os.rename(f, f + ".retiring")
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:  # P2: a refused write changes nothing — restore every touched file and the registry
        for fp, t in backup.items(): open(fp, "w", encoding="utf-8").write(t)
        os.rename(f + ".retiring", f); g.clear(); g.update(backup_graph)
        raise
    os.remove(f + ".retiring")
    log_op(g, f"migrate --retire-registry {f}: {len(moves)} lines moved into entity logs; registries repointed to generated views; file removed", args.graph, b4)
    return cmd_validate(g, args)

def strip_graph_copies(g, args):
    """Remove `## Docs` / `## Code` sections that an earlier migrate copied from graph fields (P1); logged in each file."""
    ns = g["nodes"]; backup = {}; done = []
    for k, n in sorted(ns.items()):
        f = n.get("file")
        if not f or not os.path.exists(f): continue
        t = open(f, encoding="utf-8").read()
        new = re.sub(r"\n## (Docs|Code)\n(?:(?!\n## ).)*", "", t, flags=re.S)
        if new != t:
            if sha256_of(f) != n.get("sha256"): print(f"ERROR: {f} changed outside graph_tool"); return 1
            backup[f] = t
            new = new.rstrip("\n") + f"\n- {now_iso()} removed `## Docs` / `## Code` sections copied from the graph by the first migrate (P1: they live only in the graph)\n"
            if not args.dry_run: open(f, "w", encoding="utf-8").write(new); n["sha256"] = sha256_of(f)
            done.append(k)
    print(f"## migrate --strip-graph-copies{' --dry-run' if args.dry_run else ''}: {len(done)} entity files")
    if args.dry_run or not done: return 0
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        for f, t in backup.items(): open(f, "w", encoding="utf-8").write(t)
        raise
    log_op(g, f"migrate --strip-graph-copies: {len(done)} entity files", args.graph, b4)
    return cmd_validate(g, args)

FOLD_REF = re.compile(r"(?:supersedes|refines)\s+(?:the\s+[\w\s-]*?part\s+of\s+)?([A-Z]+-?\d+)")

def restore_folds(g, args):
    """D31 / D37: bring back every node an earlier fold deleted, as hidden history, from the verbatim copies in the
    survivor's Folded section; then drop folded[] and the survivors' Folded sections (they would be second copies)."""
    ns = g["nodes"]; regs = g["config"].get("registries", [])
    pub = {r["file"]: r["public_column"] for r in regs if r.get("public_column")}
    plan, backup = [], {}
    for sk in sorted(k for k, n in ns.items() if n.get("folded")):
        sec = entity_sections(ns[sk]["file"]).get("Folded", "") if ns[sk].get("file") else ""
        for fid in ns[sk]["folded"]:
            rows = [(m.group(1), m.group(2), m.group(3)) for m in re.finditer(r"^- " + re.escape(fid) + r" `([^`]+):(\d+)`\n  (.+)$", sec, re.M)]
            reg = next((r for r in regs if re.match(r["id_pattern"], fid)), None)
            plan.append((sk, fid, reg["type"] if reg else "decision", rows))
    report = [(fid.lower(), t, sk, len(rows)) for sk, fid, t, rows in plan]
    print("## migrate --restore-folds" + (" --dry-run" if args.dry_run else ""))
    print(table(["restored node", "type", "survivor", "copies"], report))
    missing = [r for r in report if r[3] == 0]
    if missing: print(f"ERROR: no verbatim copy for {[r[0] for r in missing]} in the survivors' Folded sections"); return 1
    if args.dry_run: return 0
    restored = {fid: fid.lower() for _, fid, _, _ in plan}
    written = []
    for sk, fid, t, rows in plan:
        k = fid.lower()
        if k in ns: print(f"ERROR: node `{k}` exists"); return 1
        prim = rows[0]; cells = split_cells(prim[2])
        pubrow = next((r for r in rows if r[0] in pub), None)
        pubtxt = split_cells(pubrow[2])[pub[pubrow[0]] - 1] if pubrow and pub[pubrow[0]] - 1 < len(split_cells(pubrow[2])) else NOT_RECORDED
        name = pubtxt if pubtxt != NOT_RECORDED else (cells[1] if len(cells) > 1 else fid)
        copies = "\n".join(f"- `{f}:{i}`\n  {row}" for f, i, row in rows)
        quotes = " ".join(dict.fromkeys(q for _, _, row in rows for q in re.findall(r"「[^」]+」", row))) or NOT_RECORDED
        src = f"`{prim[0]}:{prim[1]}` (restored from the Folded section of `{sk}` by migrate --restore-folds)"
        if t == "decision":
            sec_ = {"Statement": prim[2], "Public summary": pubtxt, "User's words": quotes, "Reason": NOT_RECORDED + " — see the copies",
                    "Date": NOT_RECORDED, "Primary source": src, "Copies": copies}
        else:
            sec_ = {"Text": prim[2], "Source": src, "Copies": copies}
        path = os.path.join(ENTITY_DIR, f"{k}.md")
        open(path, "w", encoding="utf-8").write(render_entity(k, t, name, sec_, now_iso(), how="migrate --restore-folds")); written.append(path)
        n = {"id": k, "type": t, "name": name, "docs": [], "code_targets": [], "source_ref": fid, "file": path, "sha256": sha256_of(path)}
        if ns[sk].get("part_of"): n["part_of"] = list(ns[sk]["part_of"])
        if t == "decision": n["wip_status"] = "FOLDED"
        else: n.update({"issue_status": "resolved", "closed_by": ns[sk].get("source_ref", sk)})
        ns[k] = n
    for sk, fid, t, rows in plan:  # edges: chain from the rows' own supersedes / refines cells, else from the survivor
        k = fid.lower()
        if t == "decision":
            for _, _, row in rows:
                for m in FOLD_REF.finditer(row):
                    tgt = restored.get(m.group(1))
                    if tgt and tgt != k and tgt not in ns[k].setdefault("supersedes", []): ns[k]["supersedes"].append(tgt)
            if not ns[k].get("supersedes"): ns[k].pop("supersedes", None)
    for sk, fid, t, rows in plan:
        k = fid.lower()
        if t == "issue":
            ns[sk].setdefault("resolves", []); ns[sk]["resolves"].append(k) if k not in ns[sk]["resolves"] else None
        elif not any(k in ns[j].get("supersedes", []) for j in restored.values() if j != k):
            ns[sk].setdefault("supersedes", []); ns[sk]["supersedes"].append(k) if k not in ns[sk]["supersedes"] else None
    for sk in {p_[0] for p_ in plan}:  # folded[] and the survivor's Folded section are now second copies (P1)
        ns[sk].pop("folded", None)
        f = ns[sk]["file"]; backup[f] = open(f, encoding="utf-8").read()
        t_ = re.sub(r"\n## Folded\n(?:(?!\n## ).)*", "", backup[f], flags=re.S)
        t_ = t_.rstrip("\n") + f"\n- {now_iso()} Folded section removed: its copies now live in the restored history nodes ({', '.join(p_[1].lower() for p_ in plan if p_[0] == sk)})\n"
        open(f, "w", encoding="utf-8").write(t_); ns[sk]["sha256"] = sha256_of(f)
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        for p_ in written: os.remove(p_)
        for f, t_ in backup.items(): open(f, "w", encoding="utf-8").write(t_)
        raise
    log_op(g, f"migrate --restore-folds: {len(written)} history nodes restored ({', '.join(sorted(restored.values()))}); folded[] dropped", args.graph, b4)
    return cmd_validate(g, args)

def drop_handover_path(g, args):
    """D30: remove config.handover_path; move graph_tool.log to the fixed LOG_PATH when it lived elsewhere.
    The authored handover file itself is reported, never deleted (it may hold text the user wants to keep)."""
    cfg = g.get("config", {})
    if "handover_path" not in cfg: print("nothing to do: config.handover_path is absent"); return 0
    hp = cfg["handover_path"]; old_log = os.path.join(os.path.dirname(hp) or ".", "graph_tool.log")
    move = os.path.normpath(old_log) != os.path.normpath(LOG_PATH) and os.path.exists(old_log)
    if move and os.path.exists(LOG_PATH): print(f"ERROR: both `{old_log}` and `{LOG_PATH}` exist — merge them by hand first"); return 1
    print("## migrate --drop-handover-path" + (" --dry-run" if args.dry_run else ""))
    print(f"- remove config.handover_path (`{hp}`)")
    if move: print(f"- move `{old_log}` -> `{LOG_PATH}`")
    for f in (hp, os.path.splitext(hp)[0] + ".prev.md"):
        if os.path.exists(f): print(f"- `{f}` is no longer read or written (D30); delete it by hand when nothing in it is needed")
    if args.dry_run: return 0
    b4 = md5(args.graph); del cfg["handover_path"]; guarded_save(args.graph, g)
    if move: os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True); shutil.move(old_log, LOG_PATH)
    log_op(g, f"migrate --drop-handover-path: removed config.handover_path `{hp}`" + (f", log moved from `{old_log}`" if move else ""), args.graph, b4)
    return cmd_validate(g, args)

def cmd_migrate(g, args):
    """Give every node without an entity file its file, mechanically and reproducibly (no judgment, no paraphrase)."""
    if getattr(args, "add_system", False): return add_system(g, args)
    if getattr(args, "drop_handover_path", False): return drop_handover_path(g, args)
    if getattr(args, "restore_folds", False): return restore_folds(g, args)
    if getattr(args, "strip_graph_copies", False): return strip_graph_copies(g, args)
    if getattr(args, "plans", False): return migrate_plans(g, args)
    if getattr(args, "retire_registry", None): return retire_registry(g, args)
    ns = g["nodes"]; rows = scan_rows(g); todo = sorted(k for k, n in ns.items() if not n.get("file"))
    report, written = [], []
    for k in todo:
        sec, differ = migrate_sections(g, k, rows)
        path = os.path.join(ENTITY_DIR, f"{k}.md")
        report.append((k, ns[k]["type"], path, "copies differ: " + ", ".join(differ) if differ else "—"))
        if args.dry_run: continue
        if os.path.exists(path): print(f"ERROR: `{path}` exists without a node link — resolve by hand first"); return 1
        os.makedirs(ENTITY_DIR, exist_ok=True)
        heads = HEADINGS.get(ns[k]["type"], ["Summary"])
        full = {h: sec.get(h, NOT_RECORDED) for h in heads}; full.update(sec)
        open(path, "w", encoding="utf-8").write(render_entity(k, ns[k]["type"], ns[k]["name"], full, now_iso(), how="migrate"))
        ns[k]["file"] = path; ns[k]["sha256"] = sha256_of(path); written.append(path)
    print("## migrate" + (" --dry-run" if args.dry_run else ""))
    print(table(["node", "type", "entity file", "review"], report))
    print(f"{len(report)} nodes without a file; {sum(1 for r in report if r[3] != '—')} with copies whose text differs (resolve each with `append <id>`).")
    if args.dry_run: return 0
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        for p_ in written: os.remove(p_)
        raise
    log_op(g, f"migrate: {len(written)} entity files written", args.graph, b4)
    return cmd_validate(g, args)

def cmd_rename(g, args):
    """The name is a copy of the entity heading: change both together and log it."""
    ns = g["nodes"]
    if args.node not in ns: print(f"ERROR: `{args.node}` not in nodes"); return 1
    n = ns[args.node]; old = n["name"]; n["name"] = args.name
    if n.get("file"):
        f = n["file"]
        if sha256_of(f) != n.get("sha256"): print(f"ERROR: `{f}` was changed outside graph_tool"); return 1
        txt = open(f, encoding="utf-8").read()
        txt = re.sub(r"^# (\S+) — .+$", lambda m: f"# {m.group(1)} — {args.name}", txt, count=1, flags=re.M)
        txt = txt.rstrip("\n") + f"\n- {now_iso()} renamed from: {old}\n"
        open(f, "w", encoding="utf-8").write(txt); n["sha256"] = sha256_of(f)
    b4 = md5(args.graph); guarded_save(args.graph, g); log_op(g, f"rename {args.node}: {old!r} -> {args.name!r}", args.graph, b4)
    print(f"{args.node}: renamed"); return cmd_validate(g, args)

def cmd_config(g, args):
    """Config edits as a command (rule r2): `config get [key]`, `config set <dotted.key> <json>`; validated before saving."""
    c = g.setdefault("config", {})
    def walk(key, create=False):
        parts = key.split("."); cur = c
        for p_ in parts[:-1]:
            cur = cur[int(p_)] if isinstance(cur, list) else (cur.setdefault(p_, {}) if create else cur[p_])
        return cur, parts[-1]
    if args.action == "get":
        if not args.key: print(json.dumps(c, indent=2, ensure_ascii=False)); return 0
        try:
            cur, last = walk(args.key); print(json.dumps(cur[int(last)] if isinstance(cur, list) else cur[last], indent=2, ensure_ascii=False)); return 0
        except (KeyError, IndexError, ValueError): print(f"ERROR: no config key `{args.key}`"); return 1
    if args.action != "set" or not args.key or args.value is None: print("ERROR: config get [key] | config set <key> <json-value>"); return 1
    try: val = json.loads(args.value)
    except json.JSONDecodeError as e: print(f"ERROR: value is not JSON: {e}"); return 1
    try:
        cur, last = walk(args.key, create=True)
    except (KeyError, IndexError, ValueError): print(f"ERROR: bad key path `{args.key}`"); return 1
    old = (cur[int(last)] if isinstance(cur, list) else cur.get(last)) if True else None
    if isinstance(cur, list): cur[int(last)] = val
    else: cur[last] = val
    b4 = md5(args.graph); guarded_save(args.graph, g)
    log_op(g, f"config set {args.key}: {json.dumps(old, ensure_ascii=False)[:80]} -> {json.dumps(val, ensure_ascii=False)[:80]}", args.graph, b4)
    print(f"config {args.key} = {json.dumps(val, ensure_ascii=False)[:120]}"); return cmd_validate(g, args)

def cmd_append(g, args):
    """Entity files are append-only: add a dated line under Log (corrections, status notes, later user words)."""
    ns = g["nodes"]
    if args.node not in ns or not ns[args.node].get("file"): print(f"ERROR: `{args.node}` has no entity file"); return 1
    n = ns[args.node]; f = n["file"]
    if sha256_of(f) != n.get("sha256"): print(f"ERROR: `{f}` was changed outside graph_tool; resolve that first (validate shows it)"); return 1
    old = open(f, encoding="utf-8").read()
    if getattr(args, "section", None):  # a newer version of a section: the last section with a heading is the current one
        i = old.rfind("\n## Log")
        new = old[:i] + f"\n## {args.section}\n{args.text.strip()}\n" + old[i:]
        new = new.rstrip("\n") + f"\n- {now_iso()} section `{args.section}` added (supersedes any earlier `{args.section}`)\n"
    else:
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
    if not args.check and any(r[2] == "written" for r in rows): log_op(g, "render " + ", ".join(r[0] for r in rows if r[2] == "written"), args.graph, md5(args.graph), force=True)
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

def cmd_set_source_ref(g, args):
    """u58: give a decision / issue its registry id after it exists; closed_by values that named the node move with it."""
    ns = g["nodes"]
    if args.node not in ns or ns[args.node]["type"] not in ("decision", "issue"): print(f"ERROR: `{args.node}` is not a decision / issue node"); return 1
    n = ns[args.node]; old = n.get("source_ref", args.node); n["source_ref"] = args.ref; moved = []
    if n["type"] == "decision":
        for i in n.get("resolves", []):
            if ns[i].get("closed_by") in (old, args.node): ns[i]["closed_by"] = args.ref; moved.append(i)
    b4 = md5(args.graph); guarded_save(args.graph, g)
    log_op(g, f"set-source-ref {args.node}: {old} -> {args.ref}" + (f"; closed_by moved on {', '.join(moved)}" if moved else ""), args.graph, b4)
    print(f"{args.node}.source_ref: {old} -> {args.ref}" + (f"; closed_by -> {args.ref} on {', '.join(moved)}" if moved else ""))
    return cmd_validate(g, args)

def entity_log(ns, k, text, backup):
    """Append a dated Log line to k's entity file (sha-checked); the old text goes to `backup` for a rollback."""
    f = ns[k].get("file")
    if not f: return
    if sha256_of(f) != ns[k].get("sha256"): raise WriteRefused([f"`{f}` changed outside graph_tool — restore it first"])
    cur = open(f, encoding="utf-8").read()
    backup.setdefault(f, cur)
    open(f, "w", encoding="utf-8").write(cur.rstrip("\n") + f"\n- {now_iso()} {text}\n"); ns[k]["sha256"] = sha256_of(f)

def save_restructure(g, args, backup, line):
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        for f, t in backup.items(): open(f, "w", encoding="utf-8").write(t)
        raise
    log_op(g, line, args.graph, b4)

def cmd_move(g, args):
    """D43 R1: change part_of in one validated step; the reason goes to both parents' entity logs."""
    ns = g["nodes"]
    for x in (args.node, args.parent):
        if x not in ns: print(f"ERROR: `{x}` not in nodes"); return 1
    if ns[args.node]["type"] not in STRUCT_CHILD + ("task",): print("ERROR: move is for structure nodes (component / group / feature / function / task); decisions and issues use add-edge / remove-edge"); return 1
    old = ns[args.node].get("part_of", [None])[0]; backup = {}
    ns[args.node]["part_of"] = [args.parent]
    for k in dict.fromkeys(x for x in (old, args.parent) if x):
        entity_log(ns, k, f"move: `{args.node}` {old} -> {args.parent} — {args.reason}", backup)
    save_restructure(g, args, backup, f"move {args.node}: part_of {old} -> {args.parent} ({args.reason})")
    print(f"moved `{args.node}`: {old} -> {args.parent}"); return cmd_validate(g, args)

def cmd_group(g, args):
    """D43 R2: insert a group / feature / function between a parent and some of its children."""
    ns = g["nodes"]
    if args.id in ns or not ID_RE.match(args.id): print(f"ERROR: `{args.id}` exists or is not a valid id"); return 1
    if args.type not in ("group", "feature", "function"): print("ERROR: type must be group | feature | function"); return 1
    if args.under not in ns: print(f"ERROR: `{args.under}` not in nodes"); return 1
    bad = [c for c in args.children if c not in ns or ns[c].get("part_of") != [args.under]]
    if bad: print(f"ERROR: not children of `{args.under}`: {', '.join(bad)}"); return 1
    n = {"id": args.id, "type": args.type, "name": args.name, "docs": [], "code_targets": [], "part_of": [args.under]}
    if args.cls:
        if args.type != "group": print("ERROR: --class is for group nodes only"); return 1
        n["class"] = args.cls
    heads = HEADINGS[args.type]; sec = {h: NOT_RECORDED for h in heads}
    if args.summary: sec[heads[0]] = args.summary
    if args.criterion and "Criterion" in heads: sec["Criterion"] = args.criterion
    path = os.path.join(ENTITY_DIR, f"{args.id}.md")
    if os.path.exists(path): print(f"ERROR: `{path}` already exists"); return 1
    os.makedirs(ENTITY_DIR, exist_ok=True)
    open(path, "w", encoding="utf-8").write(render_entity(args.id, args.type, args.name, sec, now_iso(), how="group"))
    n["file"] = path; n["sha256"] = sha256_of(path); ns[args.id] = n
    for c in args.children: ns[c]["part_of"] = [args.id]
    backup = {}
    try:
        entity_log(ns, args.under, f"group: `{args.id}` inserted over {', '.join(args.children)} — {args.reason}", backup)
        save_restructure(g, args, backup, f"group {args.id} ({args.type}) under {args.under} over {', '.join(args.children)} ({args.reason})")
    except WriteRefused:
        os.remove(path); raise
    print(f"inserted `{args.id}` under `{args.under}` over {len(args.children)} children"); return cmd_validate(g, args)

def cmd_dissolve(g, args):
    """D43 R3: the node's structure children go to its parent; the node stays as hidden history (FOLDED). Every other
    reference to it (attached decisions / issues, depends_on, affects) and its own docs / code / tests must be mapped
    explicitly; the command refuses while one is unmapped and changes nothing."""
    ns = g["nodes"]; k = args.node
    if k not in ns or ns[k]["type"] not in ("group", "feature", "function") or hidden(ns[k]): print(f"ERROR: `{k}` is not a live group / feature / function"); return 1
    parent = ns[k].get("part_of", [None])[0]
    if not parent: print(f"ERROR: `{k}` has no parent to receive its children"); return 1
    mp = {}
    for spec in args.map or []:
        if "=" not in spec: print(f"ERROR: --map wants <referrer>=<new-target>, got `{spec}`"); return 1
        a, b = spec.split("=", 1); mp[a] = b
    kids = structure_children(ns, k)
    refs = sorted(j for j, m in ns.items() if j != k and j not in kids and any(k in m.get(e, []) for e in EDGES))
    own = {"docs": args.docs_to, "code_targets": args.code_to, "test_targets": args.tests_to}
    flag = {"docs": "--docs-to", "code_targets": "--code-to", "test_targets": "--tests-to"}
    unmapped = [f"{j} (refers to `{k}` by {', '.join(e for e in EDGES if k in ns[j].get(e, []))})" for j in refs if j not in mp] + \
               [f"own {f_} ({len(ns[k][f_])} paths) — give {flag[f_]} <node>" for f_, to in own.items() if ns[k].get(f_) and not to]
    bad = [f"{a}={b}" for a, b in list(mp.items()) + [(f_, t) for f_, t in own.items() if t] if b not in ns or b == k]
    if unmapped or bad:
        print(f"## dissolve {k} — refused, nothing changed")
        if unmapped: print("Unmapped (map each with --map <referrer>=<new-target>, own fields with --docs-to / --code-to / --tests-to):"); [print(f"- {u}") for u in unmapped]
        if bad: print("Unknown targets: " + ", ".join(bad))
        return 1
    for j in kids: ns[j]["part_of"] = [parent]
    for j, t in mp.items():
        for e in EDGES:
            if k in ns[j].get(e, []): ns[j][e] = list(dict.fromkeys(t if x == k else x for x in ns[j][e]))
    for f_, to in own.items():  # one place per fact: the paths move, the dissolved node keeps none
        if to and ns[k].get(f_):
            ns[to][f_] = list(dict.fromkeys(ns[to].get(f_, []) + ns[k][f_]))
            ns[k][f_] = []
    ns[k].pop("test_targets", None); ns[k]["wip_status"] = "FOLDED"; ns[k].pop("next", None)
    if g.get("current_node") == k: g["current_node"] = parent
    backup = {}
    entity_log(ns, parent, f"dissolve: `{k}` dissolved, children {', '.join(kids) or 'none'} moved here — {args.reason}", backup)
    entity_log(ns, k, f"dissolved into `{parent}` (kept as hidden history, D43) — {args.reason}", backup)
    save_restructure(g, args, backup, f"dissolve {k} -> {parent}: children {', '.join(kids) or 'none'}; mapped {', '.join(f'{a}={b}' for a, b in mp.items()) or 'none'} ({args.reason})")
    print(f"dissolved `{k}`: {len(kids)} children moved to `{parent}`; kept as hidden history"); return cmd_validate(g, args)

def add_system(g, args):
    """D38 P6: existing graphs gain the apex — one system node, every component part_of it."""
    ns = g["nodes"]
    if any(n["type"] == "system" for n in ns.values()): print("nothing to do: a system node exists"); return 0
    sid = args.system_id or "system"; name = args.system_name
    if not name: print("ERROR: give --system-name \"<name>\""); return 1
    if sid in ns or not ID_RE.match(sid): print(f"ERROR: `{sid}` exists or is not a valid id"); return 1
    comps = sorted(k for k, n in ns.items() if n["type"] == "component")
    print("## migrate --add-system" + (" --dry-run" if args.dry_run else "")); print(table(["node", "change"], [(sid, "new system node")] + [(c, f"part_of -> {sid}") for c in comps]))
    if args.dry_run: return 0
    path = os.path.join(ENTITY_DIR, f"{sid}.md")
    if os.path.exists(path): print(f"ERROR: `{path}` already exists"); return 1
    os.makedirs(ENTITY_DIR, exist_ok=True)
    open(path, "w", encoding="utf-8").write(render_entity(sid, "system", name, {h: NOT_RECORDED for h in HEADINGS["system"]}, now_iso(), how="migrate --add-system"))
    ns[sid] = {"id": sid, "type": "system", "name": name, "docs": [], "code_targets": [], "file": path, "sha256": sha256_of(path)}
    for c in comps: ns[c]["part_of"] = [sid]
    b4 = md5(args.graph)
    try:
        guarded_save(args.graph, g)
    except WriteRefused:
        os.remove(path); raise
    log_op(g, f"migrate --add-system: {sid} over {', '.join(comps)}", args.graph, b4)
    print(f"added `{sid}`; fill Purpose / Premises / Values with `append {sid} \"<text>\" --section <Heading>`"); return cmd_validate(g, args)

# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="dependency_graph.json"); ap.add_argument("--lang", default=None, choices=["en", "ja"])
    sub = ap.add_subparsers(dest="cmd", required=True)
    def sp(name, *posargs, nargs=None):
        p = sub.add_parser(name); p.add_argument("--lang", default=None, choices=["en", "ja"], dest="lang_sub")
        for a in posargs: p.add_argument(a, nargs=nargs) if nargs and a == posargs[-1] else p.add_argument(a)
        return p
    p = sp("install"); p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p = sp("uninstall"); p.add_argument("--dry-run", dest="dry_run", action="store_true")
    sp("validate"); sp("gate"); sp("hydrate", "node"); sp("check")
    sp("fold", "victim", "survivor"); sp("split", "node", "children", nargs="+")
    sp("set-status", "node", "status"); sp("add-edge", "src", "kind", "dst"); sp("remove-edge", "src", "kind", "dst"); sp("set-current", "node"); sp("lint-prose")
    sp("add-doc", "node", "path"); sp("add-code", "node", "path"); sp("add-test", "node", "path")
    p = sp("add-node", "id", "type", "name"); p.add_argument("--part-of", dest="part_of"); p.add_argument("--doc", action="append"); p.add_argument("--code", action="append"); p.add_argument("--source-ref", dest="source_ref"); p.add_argument("--status")
    p.add_argument("--next", action="store_true"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger"); p.add_argument("--summary")
    p.add_argument("--test", action="append"); p.add_argument("--class", dest="cls"); p.add_argument("--section", action="append")
    sp("set-source-ref", "node", "ref")
    p = sp("move", "node", "parent"); p.add_argument("--reason", required=True)
    p = sp("group", "id", "type", "name"); p.add_argument("--under", required=True); p.add_argument("children", nargs="+"); p.add_argument("--class", dest="cls"); p.add_argument("--summary"); p.add_argument("--criterion"); p.add_argument("--reason", required=True)
    p = sp("dissolve", "node"); p.add_argument("--map", action="append"); p.add_argument("--docs-to", dest="docs_to"); p.add_argument("--code-to", dest="code_to"); p.add_argument("--tests-to", dest="tests_to"); p.add_argument("--reason", required=True)
    p = sp("backlog"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--next-only", dest="next_only", action="store_true"); p.add_argument("--component"); p.add_argument("--all", action="store_true")
    p = sp("set-next", "node"); p.add_argument("--off", action="store_true")
    p = sp("set-issue", "node"); p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger")
    p = sp("close", "node", "state"); p.add_argument("--by", required=True)
    p = sp("add", "id", "type", "name"); p.add_argument("--part-of", dest="part_of"); p.add_argument("--source-ref", dest="source_ref"); p.add_argument("--status")
    p.add_argument("--owner", choices=["user", "claude"]); p.add_argument("--trigger"); p.add_argument("--section", action="append")
    p.add_argument("--new-not-duplicate", dest="new_not_duplicate"); p.add_argument("--duplicate-of", dest="duplicate_of")
    p = sp("append", "node", "text"); p.add_argument("--section", default=None)
    p = sp("attach", "node"); p.add_argument("--section", action="append"); p.add_argument("--as-plan", dest="as_plan", action="store_true")
    p = sp("render"); p.add_argument("--check", action="store_true")
    p = sp("migrate"); p.add_argument("--dry-run", dest="dry_run", action="store_true"); p.add_argument("--plans", action="store_true"); p.add_argument("--retire-registry", dest="retire_registry", metavar="FILE"); p.add_argument("--strip-graph-copies", dest="strip_graph_copies", action="store_true"); p.add_argument("--restore-folds", dest="restore_folds", action="store_true"); p.add_argument("--drop-handover-path", dest="drop_handover_path", action="store_true")
    p.add_argument("--add-system", dest="add_system", action="store_true"); p.add_argument("--system-id", dest="system_id"); p.add_argument("--system-name", dest="system_name")
    p = sp("rename", "node", "name")
    p = sp("config", "action"); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    for name, a in ap._subparsers._group_actions[0].choices.items():
        if name == "hydrate": a.add_argument("--dry-run", dest="dry_run", action="store_true"); a.add_argument("--history", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "install":  # the only command that runs before the graph exists
        args.lang = args.lang_sub or args.lang or "en"
        try: return cmd_install(None, args)
        except WriteRefused as e: print(table(["severity", "finding"], [("error", p) for p in e.args[0]])); print("RESULT: FAIL"); return 1
    if not os.path.exists(args.graph):
        print(f"ERROR: {args.graph} not found (run from the project root, or pass --graph)"); return 1
    g = load(args.graph)
    args.lang = args.lang_sub or args.lang or g.get("config", {}).get("interaction_language", "en")
    if args.lang not in ("en", "ja"): args.lang = "en"
    before = md5(args.graph)
    try:
      rc = {"validate": cmd_validate, "gate": cmd_gate, "uninstall": cmd_uninstall, "hydrate": cmd_hydrate, "check": cmd_check,
          "fold": cmd_fold, "split": cmd_split, "set-status": cmd_set_status, "add-edge": cmd_add_edge, "remove-edge": cmd_remove_edge, "set-current": cmd_set_current,
          "add-node": cmd_add_node, "lint-prose": cmd_lint_prose,
          "add-doc": cmd_add_path, "add-code": cmd_add_path, "add-test": cmd_add_path, "set-source-ref": cmd_set_source_ref,
          "move": cmd_move, "group": cmd_group, "dissolve": cmd_dissolve, "backlog": cmd_backlog, "set-next": cmd_set_next,
          "set-issue": cmd_set_issue, "close": cmd_close, "add": cmd_add, "append": cmd_append, "attach": cmd_attach, "migrate": cmd_migrate, "rename": cmd_rename, "config": cmd_config, "render": cmd_render}[args.cmd](g, args)
    except WriteRefused as e:
        print("## write refused — the graph would be invalid; nothing was written (U31)")
        print(table(["severity", "finding"], [("error", p) for p in e.args[0]]))
        print("RESULT: FAIL"); rc = 1
    after = md5(args.graph) if os.path.exists(args.graph) else "(removed)"
    print(f"\n<!-- graph_tool {args.cmd} @{git_head()} graph md5 {before}" + (f" -> {after} (WRITTEN)" if after != before else " (unchanged)") + " -->")
    return rc

if __name__ == "__main__":
    sys.exit(main())
