#!/usr/bin/env python3
"""Self-test for graph_schema.json: positive and negative fixtures.
Usage: python3 run_fixtures.py   (from anywhere; resolves the schema relative to this file)
Exit code 0 when every fixture behaves as expected, 1 otherwise. Requires `jsonschema` >= 4.
"""
import copy, json, os, sys
from jsonschema import Draft202012Validator as V, FormatChecker

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "..", "graph_schema.json")
TEMPLATE = os.path.join(HERE, "..", "..", "templates", "graph_context.template.json")

schema = json.load(open(SCHEMA))
V.check_schema(schema)
v = V(schema, format_checker=FormatChecker())
results = []

def run(label, doc, expect_ok):
    errs = list(v.iter_errors(doc))
    ok = not errs
    results.append(ok == expect_ok)
    msg = "" if ok else " | " + errs[0].message[:80]
    print(("PASS" if ok == expect_ok else "FAIL"), label, msg)

P1, P2 = "docs/design/decision-log.md", "docs/design/tbd-registry.md"
good = {
    "current_node": "commit-protocol",
    "config": {
        "interaction_language": "ja", "handover_path": "docs/handover/WIP_HANDOVER.md",
        "design_root": "docs/design/", "docs_scope": ["docs/design/**/*.md"],
        "registries": [{"type": "decision", "id_pattern": "^D-\\d{3}$", "file": P1},
                       {"type": "issue", "id_pattern": "^TBD-\\d{2}$", "file": P2}],
        "growth_threshold": 5,
        "install": {"installed_at": "2026-09-24T10:00:00Z", "skill_version": "3.1.1",
                    "claude_md_sha256_before": "a" * 64, "gitignore_sha256_before": None}},
    "nodes": {
        "core": {"id": "core", "type": "component", "name": "Core", "docs": ["docs/design/00-overview.md"], "code_targets": ["src/"]},
        "settler": {"id": "settler", "type": "component", "name": "Settler", "docs": [], "code_targets": ["settler/"]},
        "commit-protocol": {"id": "commit-protocol", "type": "feature", "name": "Commit protocol",
                            "docs": ["docs/design/common/commit-protocol.md"], "code_targets": ["src/main/java/x/Commit.java"],
                            "part_of": ["core"], "depends_on": ["settle-lazy"], "wip_status": "IN_PROGRESS"},
        "settle-lazy": {"id": "settle-lazy", "type": "function", "name": "Lazy settle", "docs": [], "code_targets": ["settler/Lazy.java"], "part_of": ["settler"]},
        "tbd-24": {"id": "tbd-24", "type": "issue", "name": "Porting semantics", "docs": [], "code_targets": [],
                   "source_ref": "TBD-24", "part_of": ["commit-protocol"], "affects": ["commit-protocol"]},
        "d-022": {"id": "d-022", "type": "decision", "name": "No hardcode", "docs": [], "code_targets": [],
                  "source_ref": "D-022", "part_of": ["core"], "affects": ["commit-protocol", "settle-lazy"],
                  "resolves": ["tbd-24"], "supersedes": [], "folded": ["D-010", "TBD-03"]}}}

def bad(label, mutate, expect=False):
    b = copy.deepcopy(good); mutate(b); run(label, b, expect)

run("template", json.load(open(TEMPLATE)), True)
run("full v2 graph", good, True)
bad("root extra key rejected", lambda b: b.__setitem__("version", 1))
bad("config unknown key rejected", lambda b: b["config"].__setitem__("code_roots", ["src/"]))
bad("missing config rejected", lambda b: b.pop("config"))
bad("component with part_of rejected", lambda b: b["nodes"]["core"].__setitem__("part_of", ["settler"]))
bad("part_of >1 rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("part_of", ["core", "settler"]))
bad("source_ref on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("source_ref", "D-001"))
bad("resolves on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("resolves", ["d-022"]))
bad("folded on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("folded", ["D-001"]))
bad("supersedes on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("supersedes", ["d-022"]))
bad("registry missing file rejected", lambda b: b["config"]["registries"][0].pop("file"))
bad("registry bad type rejected", lambda b: b["config"]["registries"][0].__setitem__("type", "feature"))
bad("growth_threshold 0 rejected", lambda b: b["config"].__setitem__("growth_threshold", 0))
bad("bad sha rejected", lambda b: b["config"]["install"].__setitem__("claude_md_sha256_before", "zz"))
bad("bad type enum rejected", lambda b: b["nodes"]["core"].__setitem__("type", "module"))
bad("node extra key rejected", lambda b: b["nodes"]["core"].__setitem__("summary", "x"))
bad("bad id key rejected", lambda b: b["nodes"].__setitem__("Bad Key", b["nodes"]["settler"]))
bad("numeric current_node rejected", lambda b: b.__setitem__("current_node", 5))
bad("dup edge rejected", lambda b: b["nodes"]["d-022"].__setitem__("affects", ["core", "core"]))
bad("task with source_ref rejected", lambda b: b["nodes"].__setitem__("t1", {"id": "t1", "type": "task", "name": "t", "docs": [], "code_targets": [], "source_ref": "X"}))
bad("decision without source_ref OK (optional)", lambda b: b["nodes"]["d-022"].pop("source_ref"), True)
bad("empty registries OK", lambda b: b["config"].__setitem__("registries", []), True)

print(f"\n{sum(results)}/{len(results)} fixtures as expected")
sys.exit(0 if all(results) else 1)
