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
        "interaction_language": "ja",
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
                   "source_ref": "TBD-24", "part_of": ["commit-protocol"], "affects": ["commit-protocol"],
                   "issue_status": "resolved", "closed_by": "D-022", "owner": "user", "trigger": "before release"},
        "d-022": {"id": "d-022", "type": "decision", "name": "No hardcode", "docs": [], "code_targets": [],
                  "source_ref": "D-022", "part_of": ["core"], "affects": ["commit-protocol", "settle-lazy"],
                  "resolves": ["tbd-24"], "supersedes": []}}}

SY = {"id": "sys", "type": "system", "name": "Interlock", "docs": ["docs/design/00-overview.md"], "code_targets": []}
RQ = {"id": "req-1", "type": "requirement", "name": "Guarantees are never cut", "docs": [], "code_targets": [], "part_of": ["sys"], "affects": ["core"]}
GR = {"id": "common", "type": "group", "name": "Common", "docs": [], "code_targets": [], "part_of": ["core"], "class": "common"}

def bad(label, mutate, expect=False):
    b = copy.deepcopy(good); mutate(b); run(label, b, expect)

run("template", json.load(open(TEMPLATE)), True)
run("full v2 graph", good, True)
bad("root extra key rejected", lambda b: b.__setitem__("version", 1))
bad("config unknown key rejected", lambda b: b["config"].__setitem__("code_roots", ["src/"]))
bad("handover_path rejected (retired, D30)", lambda b: b["config"].__setitem__("handover_path", ".context/WIP_HANDOVER.md"))
bad("missing config rejected", lambda b: b.pop("config"))
bad("system with part_of rejected (D38)", lambda b: b["nodes"].__setitem__("sys", dict(SY, part_of=["core"])))
bad("part_of >1 rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("part_of", ["core", "settler"]))
bad("source_ref on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("source_ref", "D-001"))
bad("resolves on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("resolves", ["d-022"]))
bad("folded field rejected (dropped, D37)", lambda b: b["nodes"]["d-022"].__setitem__("folded", ["D-001"]))
bad("refines on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("refines", ["d-022"]))
bad("refines on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("refines", ["d-022"]))
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
# D33 / Q3 = A: PLANNED, next, issue_status / owner / trigger / closed_by
bad("PLANNED feature with next OK", lambda b: b["nodes"]["commit-protocol"].update(wip_status="PLANNED", next=True), True)
bad("open issue without closed_by OK", lambda b: [b["nodes"]["tbd-24"].__setitem__("issue_status", "open"), b["nodes"]["tbd-24"].pop("closed_by")], True)
bad("issue next OK", lambda b: b["nodes"]["tbd-24"].__setitem__("next", True), True)
bad("bad wip_status rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("wip_status", "TODO"))
bad("issue without issue_status rejected", lambda b: b["nodes"]["tbd-24"].pop("issue_status"))
bad("bad issue_status rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("issue_status", "closed"))
bad("resolved issue without closed_by rejected", lambda b: b["nodes"]["tbd-24"].pop("closed_by"))
bad("transferred issue without closed_by rejected", lambda b: [b["nodes"]["tbd-24"].__setitem__("issue_status", "transferred"), b["nodes"]["tbd-24"].pop("closed_by")])
bad("wip_status on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("wip_status", "DONE"))
bad("issue_status on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("issue_status", "open"))
bad("owner on decision rejected", lambda b: b["nodes"]["d-022"].__setitem__("owner", "user"))
bad("bad owner rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("owner", "team"))
bad("next on decision rejected", lambda b: b["nodes"]["d-022"].__setitem__("next", True))
bad("next on component rejected", lambda b: b["nodes"]["core"].__setitem__("next", True))
bad("non-boolean next rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("next", "yes"))
bad("backlog_filter OK", lambda b: b["config"].__setitem__("backlog_filter", {"owner": "user", "next_only": False, "component": "core"}), True)
bad("backlog_filter unknown key rejected", lambda b: b["config"].__setitem__("backlog_filter", {"status": "open"}))
bad("backlog_filter bad owner rejected", lambda b: b["config"].__setitem__("backlog_filter", {"owner": "team"}))
# plan integrity-store: plan / rule entities, file + sha256
PL = {"id": "plan-x", "type": "plan", "name": "Plan X", "docs": [], "code_targets": [], "part_of": ["core"], "wip_status": "IN_PROGRESS", "file": "docs/entities/plan-x.md", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
RU = {"id": "rule-a", "type": "rule", "name": "Rule A", "docs": [], "code_targets": [], "part_of": ["core"], "file": "docs/entities/rule-a.md", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
bad("plan entity with file + sha256 OK", lambda b: b["nodes"].__setitem__("plan-x", dict(PL)), True)
bad("rule entity OK", lambda b: b["nodes"].__setitem__("rule-a", dict(RU)), True)
bad("decision with file + sha256 OK", lambda b: b["nodes"]["d-022"].update(file="docs/entities/d-022.md", sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), True)
bad("file without sha256 rejected", lambda b: b["nodes"].__setitem__("plan-x", {k: v for k, v in PL.items() if k != "sha256"}))
bad("bad sha256 rejected", lambda b: b["nodes"].__setitem__("plan-x", dict(PL, sha256="xyz")))
bad("file on feature OK (every node has a file)", lambda b: b["nodes"]["commit-protocol"].update(file="docs/entities/c.md", sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), True)
bad("next on rule rejected", lambda b: b["nodes"].__setitem__("rule-a", dict(RU, next=True)))
bad("source_ref on plan rejected", lambda b: b["nodes"].__setitem__("plan-x", dict(PL, source_ref="P1")))
bad("owner on plan rejected", lambda b: b["nodes"].__setitem__("plan-x", dict(PL, owner="user")))
bad("FOLDED decision OK", lambda b: b["nodes"]["d-022"].__setitem__("wip_status", "FOLDED"), True)
bad("FOLDED feature OK (dissolved, D43)", lambda b: b["nodes"]["commit-protocol"].__setitem__("wip_status", "FOLDED"), True)
bad("FOLDED component rejected", lambda b: b["nodes"]["core"].__setitem__("wip_status", "FOLDED"))
# structure model (D38-D43): system, requirement, group, class, test_targets, config keys
bad("system + component part_of system OK", lambda b: [b["nodes"].__setitem__("sys", dict(SY)), b["nodes"]["core"].__setitem__("part_of", ["sys"])], True)
bad("requirement with affects OK", lambda b: [b["nodes"].__setitem__("sys", dict(SY)), b["nodes"].__setitem__("req-1", dict(RQ))], True)
bad("group with class OK", lambda b: b["nodes"].__setitem__("common", dict(GR)), True)
bad("class on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("class", "common"))
bad("test_targets on feature OK", lambda b: b["nodes"]["commit-protocol"].__setitem__("test_targets", ["src/test/x/CommitIT.java"]), True)
bad("test_targets on decision rejected", lambda b: b["nodes"]["d-022"].__setitem__("test_targets", ["src/test/x/A.java"]))
bad("next on system rejected", lambda b: b["nodes"].__setitem__("sys", dict(SY, next=True)))
bad("next on group rejected", lambda b: b["nodes"].__setitem__("common", dict(GR, next=True)))
bad("source_ref on requirement rejected", lambda b: b["nodes"].__setitem__("req-1", dict(RQ, source_ref="R-1")))
bad("FOLDED group OK (dissolved)", lambda b: b["nodes"].__setitem__("common", dict(GR, wip_status="FOLDED")), True)
bad("config classes / leaf_unit / thresholds / tests OK", lambda b: b["config"].update(classes=[{"id": "common", "label": "Common", "rank": 0, "source": "docs/design/01-architecture.md#2"}, {"id": "features", "label": "Backend-specific", "rank": 1}], leaf_unit="class", source_extensions=[".java"], child_threshold=7, test_roots=["src/test/"], test_kinds={"unit": ["*Test.java"], "integration": ["*IT.java"], "helper": ["*Support.java"]}), True)
bad("revises between decisions OK (D45)", lambda b: [b["nodes"].__setitem__("d-023", {"id": "d-023", "type": "decision", "name": "x", "docs": [], "code_targets": [], "revises": ["d-022"]})], True)
bad("revises on feature rejected", lambda b: b["nodes"]["commit-protocol"].__setitem__("revises", ["d-022"]))
bad("revises on issue rejected", lambda b: b["nodes"]["tbd-24"].__setitem__("revises", ["d-022"]))
bad("class without rank rejected", lambda b: b["config"].__setitem__("classes", [{"id": "common", "label": "Common"}]))
bad("bad leaf_unit rejected", lambda b: b["config"].__setitem__("leaf_unit", "method"))
bad("bad extension rejected", lambda b: b["config"].__setitem__("source_extensions", ["java"]))
bad("child_threshold 1 rejected", lambda b: b["config"].__setitem__("child_threshold", 1))
bad("unknown test kind rejected", lambda b: b["config"].__setitem__("test_kinds", {"e2e": ["*E2E.java"]}))

print(f"\n{sum(results)}/{len(results)} fixtures as expected")
sys.exit(0 if all(results) else 1)
