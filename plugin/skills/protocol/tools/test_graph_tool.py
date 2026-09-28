#!/usr/bin/env python3
"""Synthetic-graph test for graph_tool.py. Exit 0 = all assertions hold."""
import json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import graph_tool as gt

def mk(tmp):
    os.makedirs(os.path.join(tmp, "src"), exist_ok=True); os.makedirs(os.path.join(tmp, "docs"), exist_ok=True)
    open(os.path.join(tmp, "src", "a.py"), "w").write("x")
    open(os.path.join(tmp, "docs", "log.md"), "w").write("| D-001 | x |\n| D-002 | y |\n| TBD-01 | z |\n")
    g = {"current_node": None, "config": {"registries": [{"type": "decision", "id_pattern": "^D-\\d{3}$", "file": "docs/log.md"},
                                                          {"type": "issue", "id_pattern": "^TBD-\\d{2}$", "file": "docs/log.md"}], "growth_threshold": 2},
         "nodes": {"core": {"id": "core", "type": "component", "name": "Core", "docs": [], "code_targets": ["src/"]},
                   "f": {"id": "f", "type": "feature", "name": "Feature F", "docs": ["docs/log.md"], "code_targets": ["src/a.py"], "part_of": ["core"]},
                   "d-001": {"id": "d-001", "type": "decision", "name": "one", "docs": ["docs/log.md"], "code_targets": [], "source_ref": "D-001", "part_of": ["f"], "affects": ["f"], "wip_status": "DONE"},
                   "d-002": {"id": "d-002", "type": "decision", "name": "two", "docs": ["docs/log.md"], "code_targets": [], "source_ref": "D-002", "part_of": ["f"], "affects": ["f"], "supersedes": ["d-001"], "wip_status": "DONE"},
                   "tbd-01": {"id": "tbd-01", "type": "issue", "name": "q", "docs": ["docs/log.md"], "code_targets": [], "source_ref": "TBD-01", "part_of": ["f"], "affects": ["f"], "issue_status": "open", "owner": "user"}}}
    p = os.path.join(tmp, "dependency_graph.json"); gt.save(p, g); return p

def main():
    tmp = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(tmp); ok = True
    try:
        p = mk(tmp); g = gt.load(p)
        problems, _ = gt.validate(g, want_schema=False); assert not problems, problems
        hop = gt.hops(g["nodes"], "f"); assert hop["core"][0] == 1 and hop["d-001"][0] == 1 and hop["tbd-01"][0] == 1
        assert gt.growth_candidates(g) == [("f", 3, 2)], gt.growth_candidates(g)
        fc = gt.fold_candidates(g); assert ("d-001", "d-002", "superseded, no other live in-edges") in fc, fc
        # negative R1: dangling edge
        bad = json.loads(json.dumps(g)); bad["nodes"]["f"]["depends_on"] = ["ghost"]
        problems, _ = gt.validate(bad, want_schema=False); assert any("dangling" in x for x in problems)
        # content layer: orphan source_ref
        bad = json.loads(json.dumps(g)); bad["nodes"]["d-002"]["source_ref"] = "D-999"
        cf = gt.content_checks(bad); assert any("orphan source_ref `D-999`" in x[2] for x in cf), cf
        # fold via CLI
        class A: graph = p; victim = "d-001"; survivor = "d-002"; lang = "en"
        rc = gt.cmd_fold(gt.load(p), A); g2 = gt.load(p)
        assert rc == 0 and g2["nodes"]["d-001"]["wip_status"] == "FOLDED" and "d-001" in g2["nodes"]["d-002"]["supersedes"] and "folded" not in g2["nodes"]["d-002"], g2["nodes"]["d-002"]
        assert ("d-001", "d-002", "superseded, no other live in-edges") not in gt.fold_candidates(g2), "a folded decision is no candidate"
        import io as _io, contextlib as _cl
        class HD: graph = p; node = "f"; dry_run = True; history = False; lang = "en"
        b_ = _io.StringIO()
        with _cl.redirect_stdout(b_): gt.cmd_hydrate(gt.load(p), HD)
        assert "| d-001 |" not in b_.getvalue() and "History hidden" in b_.getvalue(), b_.getvalue()[:400]
        HD.history = True; b_ = _io.StringIO()
        with _cl.redirect_stdout(b_): gt.cmd_hydrate(gt.load(p), HD)
        assert "d-001" in b_.getvalue(), "--history shows folded nodes"
        # u46: refines is a live in-edge that is never a fold candidate; remove-edge drops a supersedes
        g_r = gt.load(p); g_r["nodes"]["d-003x"] = {"id": "d-003x", "type": "decision", "name": "three", "docs": [], "code_targets": [], "part_of": ["f"], "refines": ["d-002"], "wip_status": "DONE"}
        g_r["nodes"]["d-004x"] = {"id": "d-004x", "type": "decision", "name": "four", "docs": [], "code_targets": [], "part_of": ["f"], "supersedes": ["d-002"], "wip_status": "DONE"}
        assert not any(c[0] == "d-002" for c in gt.fold_candidates(g_r)), "a refined decision is no fold candidate"
        g_r["nodes"]["d-003x"].pop("refines"); assert any(c[0] == "d-002" for c in gt.fold_candidates(g_r)), "superseded only -> candidate"
        bad_r = json.loads(json.dumps(g_r)); bad_r["nodes"]["f"]["refines"] = ["d-002"]
        assert any("decision nodes only" in x for x in gt.validate(bad_r, want_schema=False)[0])
        gt.save(p, g_r)
        class RE: graph = p; src = "d-004x"; kind = "supersedes"; dst = "d-002"; lang = "en"
        with _cl.redirect_stdout(_io.StringIO()): rc = gt.cmd_remove_edge(gt.load(p), RE)
        g_r = gt.load(p); assert rc == 0 and "supersedes" not in g_r["nodes"]["d-004x"]
        del g_r["nodes"]["d-003x"], g_r["nodes"]["d-004x"]; gt.save(p, g_r)
        # G12: a write that changes nothing logs nothing
        lp0 = gt.log_path(gt.load(p)); n0 = open(lp0).read().count("\n") if os.path.exists(lp0) else 0
        class NE: graph = p; src = "d-002"; kind = "supersedes"; dst = "d-001"; lang = "en"
        b_ = _io.StringIO()
        with _cl.redirect_stdout(b_): rc = gt.cmd_add_edge(gt.load(p), NE)
        n1 = open(lp0).read().count("\n") if os.path.exists(lp0) else 0
        assert rc == 0 and "unchanged" in b_.getvalue() and n1 == n0, (b_.getvalue(), n0, n1)
        # u49: add-node --source-ref copies the registry row verbatim (like migrate); an unknown ref writes nothing
        open("docs/log.md", "a").write("| D-007 | seven, from the register 「quoted」 |\n")
        class AN: graph = p; id = "d-007"; type = "decision"; name = "seven"; part_of = "f"; doc = None; code = None; source_ref = "D-007"; status = None; next = False; owner = None; trigger = None; summary = None; lang = "en"
        with _cl.redirect_stdout(_io.StringIO()): rc = gt.cmd_add_node(gt.load(p), AN)
        sec7 = gt.entity_sections("docs/entities/d-007.md")
        assert rc == 0 and sec7["Statement"] == "| D-007 | seven, from the register 「quoted」 |" and sec7["User's words"] == "「quoted」" and "docs/log.md:" in sec7["Primary source"], sec7
        AN.id = "d-008"; AN.source_ref = "D-008"; b_ = _io.StringIO()
        with _cl.redirect_stdout(b_): rc = gt.cmd_add_node(gt.load(p), AN)
        assert rc == 1 and "no registry row" in b_.getvalue() and "d-008" not in gt.load(p)["nodes"] and not os.path.exists("docs/entities/d-008.md"), b_.getvalue()
        g7 = gt.load(p); del g7["nodes"]["d-007"]; gt.save(p, g7); os.remove("docs/entities/d-007.md")
        # u48: hydrate of the current node writes nothing (graph bytes and log unchanged)
        HD.dry_run = False; HD.history = False
        with _cl.redirect_stdout(_io.StringIO()): gt.cmd_hydrate(gt.load(p), HD)
        lp = gt.log_path(gt.load(p)); gb, lb = open(p).read(), open(lp).read()
        b_ = _io.StringIO()
        with _cl.redirect_stdout(b_): gt.cmd_hydrate(gt.load(p), HD)
        assert open(p).read() == gb and open(lp).read() == lb and "nothing written" in b_.getvalue(), "re-hydrate of current_node must not write"
        # split via CLI
        class B: graph = p; node = "f"; children = ["f-sub=d-002"]; lang = "en"
        rc = gt.cmd_split(gt.load(p), B); g3 = gt.load(p)
        assert rc == 0 and g3["nodes"]["f-sub"]["part_of"] == ["f"] and g3["nodes"]["d-002"]["part_of"] == ["f-sub"]
        # add-node via CLI
        class C: graph = p; id = "g"; type = "feature"; name = "G"; part_of = "core"; doc = None; code = None; source_ref = None; status = "IN_PROGRESS"; lang = "en"
        rc = gt.cmd_add_node(gt.load(p), C); g4 = gt.load(p)
        assert rc == 0 and g4["nodes"]["g"]["part_of"] == ["core"]
        import io, contextlib
        g5 = gt.load(p); g5["current_node"] = "f"; gt.save(p, g5)
        class S2: graph = p; node = "g"; status = "DONE"; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): gt.cmd_set_status(gt.load(p), S2)
        # add-doc + dry-run hydrate
        class AD: graph = p; cmd = "add-doc"; node = "g"; path = "docs/log.md"; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): rc = gt.cmd_add_path(gt.load(p), AD)
        assert rc == 0 and "docs/log.md" in gt.load(p)["nodes"]["g"]["docs"]
        before = gt.md5(p)
        class DR: graph = p; node = "g"; dry_run = True; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): gt.cmd_hydrate(gt.load(p), DR)
        assert gt.md5(p) == before, "dry-run must not write"
        # D33: backlog, set-next, set-issue, close
        q = lambda **kw: type("A", (), dict(graph=p, lang="en", **kw))
        def _run(fn, a):
            b = io.StringIO()
            try:
                with contextlib.redirect_stdout(b): rc = fn(gt.load(p), a)
            except gt.WriteRefused as e:
                return 1, b.getvalue() + "write refused " + str(e.args[0])
            return rc, b.getvalue()
        rc, out = _run(gt.cmd_add_node, q(id="i2", type="issue", name="I2", part_of="f", doc=None, code=None, source_ref=None, status=None, next=False, owner="claude", trigger="after step 2"))
        assert rc == 0 and gt.load(p)["nodes"]["i2"]["issue_status"] == "open", out
        rc, out = _run(gt.cmd_add_node, q(id="p1", type="function", name="Plan step", part_of="f", doc=None, code=None, source_ref=None, status="PLANNED", next=False, owner=None, trigger=None))
        assert rc == 0 and gt.load(p)["nodes"]["p1"]["wip_status"] == "PLANNED", out
        rc, out = _run(gt.cmd_add_node, q(id="x1", type="feature", name="X", part_of="core", doc=None, code=None, source_ref=None, status=None, next=False, owner="user", trigger=None))
        assert rc == 1 and "x1" not in gt.load(p)["nodes"], "owner on a feature must be refused"
        rows, exc, _ = gt.backlog(gt.load(p))
        ids = [r[1] for r in rows]; assert "tbd-01" in ids and "i2" in ids and "p1" in ids and not exc, rows
        rows, exc, _ = gt.backlog(gt.load(p), owner="user")
        assert [r[1] for r in rows if r[0] == "issue"] == ["tbd-01"] and exc == {"core": 1}, (rows, exc)
        assert "Excluded by the filter: core: 1" in gt.backlog_md(gt.load(p), owner="user")
        assert "WARNING: no item carries `next`" in gt.backlog_md(gt.load(p))
        rc, _ = _run(gt.cmd_set_next, q(node="p1", off=False)); assert rc == 0 and gt.load(p)["nodes"]["p1"]["next"] is True
        rows, _, _ = gt.backlog(gt.load(p)); assert rows[0][1] == "p1" and rows[0][2] == "Plan step", rows
        rc, _ = _run(gt.cmd_set_next, q(node="d-002", off=False)); assert rc == 1, "next on a decision must be refused"
        rc, _ = _run(gt.cmd_set_issue, q(node="i2", owner="user", trigger="now")); assert rc == 0 and gt.load(p)["nodes"]["i2"]["trigger"] == "now"
        rc, _ = _run(gt.cmd_set_status, q(node="i2", status="DONE")); assert rc == 1, "set-status on an issue must be refused"
        rc, out = _run(gt.cmd_close, q(node="tbd-01", state="resolved", by="D-002"))
        g7 = gt.load(p); assert rc == 0 and g7["nodes"]["tbd-01"]["closed_by"] == "D-002" and "tbd-01" in g7["nodes"]["d-002"]["resolves"], out
        rc, out = _run(gt.cmd_close, q(node="i2", state="transferred", by="interlock session"))
        g8 = gt.load(p); assert rc == 0 and g8["nodes"]["i2"]["issue_status"] == "transferred" and "resolves" not in g8["nodes"].get("interlock session", {}), out
        rows, _, _ = gt.backlog(g8); assert not [r for r in rows if r[0] == "issue"], rows
        bad = json.loads(json.dumps(g8)); bad["nodes"]["tbd-01"]["issue_status"] = "open"
        problems, _ = gt.validate(bad, want_schema=False); assert any("must be resolved" in x for x in problems), problems
        # plan integrity-store: validate-before-save (U31), add with P4, entity hash (P2), append, views (P3)
        before = open(p).read()
        rc, out = _run(gt.cmd_add_edge, q(src="d-002", kind="resolves", dst="f"))
        assert rc == 1 and "write refused" in out and open(p).read() == before, "invalid write must leave the graph untouched"
        sec = ["Statement=Fold hides nodes", "Public summary=Fold hides", "User's words=「隠す」", "Reason=keep history", "Date=2026-09-25"]
        A = dict(id="d-003", type="decision", name="Fold hides", part_of="f", source_ref=None, status=None, owner=None, trigger=None, section=sec, new_not_duplicate=None, duplicate_of=None)
        rc, out = _run(gt.cmd_add, q(**A))
        assert rc == 1 and "NOT WRITTEN" in out and "d-002" in out and not os.path.exists("docs/entities/d-003.md"), out
        rc, out = _run(gt.cmd_add, q(**dict(A, section=sec[:2], new_not_duplicate="x")))
        assert rc == 1 and "needs sections" in out, out
        rc, out = _run(gt.cmd_add, q(**dict(A, new_not_duplicate="differs from d-002: hide vs fold")))
        g9 = gt.load(p); f3 = "docs/entities/d-003.md"
        assert rc == 0 and g9["nodes"]["d-003"]["file"] == f3 and g9["nodes"]["d-003"]["sha256"] == gt.sha256_of(f3), out
        assert "P4-outcome=new-not-duplicate" in open(".context/graph_tool.log").read() if os.path.exists(".context/graph_tool.log") else True
        rc, out = _run(gt.cmd_append, q(node="d-003", text="correction: also issues"))
        assert rc == 0 and "correction: also issues" in open(f3).read() and gt.load(p)["nodes"]["d-003"]["sha256"] == gt.sha256_of(f3), out
        open(f3, "a").write("hand edit\n")
        probs, _ = gt.validate(gt.load(p), want_schema=False); assert any("changed outside graph_tool" in x for x in probs), probs
        rc, out = _run(gt.cmd_append, q(node="d-003", text="more")); assert rc == 1, "append must refuse a hand-edited file"
        txt = open(f3).read(); open(f3, "w").write(txt.replace("hand edit\n", ""))
        probs, _ = gt.validate(gt.load(p), want_schema=False); assert not [x for x in probs if "d-003" in x], probs
        g10 = gt.load(p); g10["config"]["views"] = [{"kind": "decisions", "path": "docs/views/decisions.md"}, {"kind": "public-decisions", "path": "docs/views/public.md"}]; gt.save(p, g10)
        rc, out = _run(gt.cmd_render, q(check=False)); assert rc == 0 and os.path.exists("docs/views/public.md"), out
        assert "| D-001 |" not in open("docs/views/public.md").read() and "Fold hides" in open("docs/views/public.md").read(), "public view lists migrated decisions only"
        rc, out = _run(gt.cmd_set_next, q(node="p1", off=True)); assert rc == 0
        rc, out = _run(gt.cmd_render, q(check=True)); assert rc == 0, "views are re-rendered on every accepted write: " + out
        open("docs/views/decisions.md", "a").write("hand\n")
        rc, out = _run(gt.cmd_render, q(check=True)); assert rc == 1 and "DRIFT" in out, out
        probs, _ = gt.validate(gt.load(p), want_schema=False, drift=True)
        rc, out = _run(gt.cmd_attach, q(node="d-002", section=sec, as_plan=False))
        assert rc == 0 and gt.load(p)["nodes"]["d-002"]["file"] == "docs/entities/d-002.md", out
        rc, out = _run(gt.cmd_attach, q(node="d-002", section=sec, as_plan=False)); assert rc == 1, "attach twice must be refused"
        rc, out = _run(gt.cmd_attach, q(node="g", section=["Goal=G", "Approval=user OK"], as_plan=True))
        assert rc == 0 and gt.load(p)["nodes"]["g"]["type"] == "plan", out
        # migrate: deterministic, reproducible (same input -> same files), every node gets a file; rename keeps name == heading
        g11 = gt.load(p); g11["config"]["registries"][0]["public_column"] = 2; gt.save(p, g11)
        rc, out = _run(gt.cmd_migrate, q(dry_run=True)); assert rc == 0 and "core" in out and not os.path.exists("docs/entities/core.md"), out
        snap = {k: dict(v) for k, v in gt.load(p)["nodes"].items()}
        rc, out = _run(gt.cmd_migrate, q(dry_run=False)); g12 = gt.load(p)
        assert rc == 0 and all(n.get("file") for n in g12["nodes"].values()), out
        first = {k: open(n["file"]).read().split("## Log")[0] for k, n in g12["nodes"].items()}
        assert "(not recorded in the source)" in first["tbd-01"] or "TBD-01" in first["tbd-01"], first["tbd-01"]
        for k, n in g12["nodes"].items():
            if k in snap and not snap[k].get("file"):
                os.remove(n["file"]); n.pop("file"); n.pop("sha256")
        gt.save(p, g12)
        rc, out = _run(gt.cmd_migrate, q(dry_run=False)); g13 = gt.load(p)
        again = {k: open(n["file"]).read().split("## Log")[0] for k, n in g13["nodes"].items()}
        assert again == first, "migrate must be reproducible"
        rc, out = _run(gt.cmd_rename, q(node="core", name="Core v2")); g14 = gt.load(p)
        assert rc == 0 and g14["nodes"]["core"]["name"] == "Core v2" and gt.entity_title(g14["nodes"]["core"]["file"]) == "Core v2", out
        g14["nodes"]["core"]["name"] = "stale"; probs, _ = gt.validate(g14, want_schema=False); assert any("name differs from the heading" in x for x in probs)
        # retire-registry: lines moved into entity logs; a refused write restores everything
        open("docs/reg.md", "w").write("# reg\n| TBD-01 | q | open |\n- 2026-09-25 TBD-01: note about it\n")
        g15 = gt.load(p); g15["config"]["registries"].append({"type": "issue", "id_pattern": "^TBD-\\d{2}$", "file": "docs/reg.md"}); g15["nodes"]["tbd-01"]["docs"].append("docs/reg.md"); g15["config"]["views"].append({"kind": "issues", "path": "docs/views/issues.md"}); gt.save(p, g15)
        before_e = open(g15["nodes"]["tbd-01"]["file"]).read()
        g16 = gt.load(p); g16["nodes"]["core"]["part_of"] = ["f"]; gt.save(p, g16)  # make the graph invalid -> the retire write must be refused
        rc, out = _run(gt.cmd_migrate, q(dry_run=False, plans=False, retire_registry="docs/reg.md"))
        assert rc == 1 and os.path.exists("docs/reg.md") and open(gt.load(p)["nodes"]["tbd-01"]["file"]).read() == before_e, "refused retire must restore everything"
        g17 = gt.load(p); g17["nodes"]["core"].pop("part_of"); gt.save(p, g17)
        rc, out = _run(gt.cmd_migrate, q(dry_run=False, plans=False, retire_registry="docs/reg.md"))
        g18 = gt.load(p)
        assert rc == 0 and not os.path.exists("docs/reg.md") and "note about it" in open(g18["nodes"]["tbd-01"]["file"]).read() and "docs/reg.md" not in g18["nodes"]["tbd-01"]["docs"], out
        rc, out = _run(gt.cmd_append, q(node="core", text="Core runtime of the product", section="Summary"))
        assert rc == 0 and gt.entity_sections(gt.load(p)["nodes"]["core"]["file"])["Summary"] == "Core runtime of the product", out
        rc, out = _run(gt.cmd_config, q(action="set", key="growth_threshold", value="7")); assert rc == 0 and gt.load(p)["config"]["growth_threshold"] == 7, out
        rc, out = _run(gt.cmd_config, q(action="set", key="growth_threshold", value="0")); assert rc == 1 and gt.load(p)["config"]["growth_threshold"] == 7, "invalid config must be refused"
        rc, out = _run(gt.cmd_config, q(action="set", key="registries.0.public_column", value="3")); assert rc == 0 and gt.load(p)["config"]["registries"][0]["public_column"] == 3, out
        rc, out = _run(gt.cmd_add_node, q(id="h", type="function", name="H", part_of="f", doc=None, code=None, source_ref=None, status="PLANNED", next=False, owner=None, trigger=None, summary="does H"))
        gh = gt.load(p)["nodes"]["h"]; assert rc == 0 and gh["file"] == "docs/entities/h.md" and gt.entity_sections(gh["file"])["Summary"] == "does H", out
        # restore-folds: a legacy folded[] id comes back as a hidden history node from the verbatim Folded copy
        g19 = gt.load(p); sv = g19["nodes"]["d-003"]; sv["folded"] = ["D-009"]
        gt.append_section(sv["file"], "Folded", "- D-009 `docs/log.md:9`\n  | D-009 | old rule | — | folded into D-003 |")
        sv["sha256"] = gt.sha256_of(sv["file"]); gt.save(p, g19)
        rc, out = _run(gt.cmd_migrate, q(dry_run=False, plans=False, retire_registry=None, strip_graph_copies=False, restore_folds=True))
        g20 = gt.load(p)
        assert rc == 0 and g20["nodes"]["d-009"]["wip_status"] == "FOLDED" and "d-009" in g20["nodes"]["d-003"]["supersedes"], out
        assert "folded" not in g20["nodes"]["d-003"] and "Folded" not in gt.entity_sections(g20["nodes"]["d-003"]["file"]), "folded[] and the Folded section must be gone"
        assert "| D-009 | old rule |" in open(g20["nodes"]["d-009"]["file"]).read()
        # D30: config.handover_path is retired — validate names the migrate; migrate removes it and moves the log
        g21 = gt.load(p); g21["config"]["handover_path"] = "docs/ho/WIP.md"; gt.save(p, g21)
        problems, _ = gt.validate(gt.load(p), want_schema=False); assert any("--drop-handover-path" in x for x in problems), problems
        os.makedirs("docs/ho", exist_ok=True); shutil.move(gt.LOG_PATH, "docs/ho/graph_tool.log"); nlog = open("docs/ho/graph_tool.log").read().count("\n")
        rc, out = _run(gt.cmd_migrate, q(dry_run=False, plans=False, retire_registry=None, strip_graph_copies=False, restore_folds=False, drop_handover_path=True))
        assert rc == 0 and "handover_path" not in gt.load(p)["config"] and not os.path.exists("docs/ho/graph_tool.log"), out
        assert open(gt.LOG_PATH).read().count("\n") == nlog + 1, "log moved, then the migrate line appended"
        print("test_graph_tool: all assertions hold")
    except AssertionError as e:
        ok = False; print("FAIL:", e)
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)
    return 0 if ok else 1

def test_gate():
    """D30 completion gate: read-only; FAIL on a dirty tree, an open issue without trigger, no next; WARN only for unlinked commits."""
    import io, contextlib, subprocess
    tmp = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(tmp)
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True, text=True, check=True)
    class A: graph = "dependency_graph.json"; lang = "en"
    def gate():
        b = io.StringIO()
        with contextlib.redirect_stdout(b): rc = gt.cmd_gate(gt.load(A.graph), A)
        return rc, b.getvalue()
    try:
        git("init", "-q")
        g = {"current_node": "w", "config": {"registries": []}, "nodes": {
            "c": {"id": "c", "type": "component", "name": "C", "docs": [], "code_targets": []},
            "w": {"id": "w", "type": "function", "name": "W", "docs": [], "code_targets": [], "part_of": ["c"], "wip_status": "IN_PROGRESS", "next": True},
            "i": {"id": "i", "type": "issue", "name": "I", "docs": [], "code_targets": [], "part_of": ["w"], "issue_status": "open", "owner": "user", "trigger": "t"}}}
        gt.save(A.graph, g); git("add", "-A"); git("commit", "-qm", "w: start")
        before = open(A.graph).read()
        rc, out = gate(); assert rc == 0 and "RESULT: OK" in out and "/graph:hydrate w" in out, out
        assert open(A.graph).read() == before and not os.path.exists(gt.LOG_PATH), "gate writes nothing"
        git("commit", "-q", "--allow-empty", "-m", "unrelated tweak")
        rc, out = gate(); assert rc == 0 and "| WARN | commits name" in out and "unrelated tweak" in out, out
        open("x.txt", "w").write("x")
        rc, out = gate(); assert rc == 1 and "| FAIL | working tree committed" in out and "x.txt" in out, out
        os.remove("x.txt")
        g["nodes"]["i"].pop("trigger"); g["nodes"]["w"]["next"] = False; gt.save(A.graph, g); git("commit", "-qam", "i, w")
        rc, out = gate(); assert rc == 1 and "missing on i" in out and "| FAIL | a next item exists" in out, out
        g["nodes"]["i"]["trigger"] = "t"; g["nodes"]["w"]["next"] = True; g["current_node"] = None; gt.save(A.graph, g); git("commit", "-qam", "w")
        rc, out = gate(); assert rc == 1 and "unset while 1 nodes" in out, out
        g["nodes"]["w"]["wip_status"] = "DONE"; g["nodes"]["w"]["next"] = False; gt.save(A.graph, g); git("commit", "-qam", "w done")
        rc, out = gate(); assert rc == 0 and "no pending work" in out, out
        print("test_gate: all assertions hold"); return 0
    except AssertionError as e:
        print("FAIL:", e); return 1
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)

def test_install():
    """install / uninstall: blocks appended without a blank line, idempotent, byte-identical restore (G3, G5)."""
    import io, contextlib, hashlib
    tmp = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(tmp)
    try:
        open("CLAUDE.md", "w").write("# proj\nno final newline")  # .gitignore absent
        before = hashlib.sha256(open("CLAUDE.md", "rb").read()).hexdigest()
        def cli(*a):
            b = io.StringIO()
            with contextlib.redirect_stdout(b): rc = gt.main(list(a))
            return rc, b.getvalue()
        rc, out = cli("install", "--dry-run"); assert rc == 0 and not os.path.exists("dependency_graph.json") and "create from the template" in out, out
        rc, out = cli("install"); assert rc == 0, out
        g = gt.load("dependency_graph.json"); inst = g["config"]["install"]
        assert inst["claude_md_sha256_before"] == before and inst["gitignore_sha256_before"] is None, inst
        c = open("CLAUDE.md").read(); assert c == "# proj\nno final newline\n" + gt.CLAUDE_BLOCK, repr(c[:80])
        assert open(".gitignore").read() == gt.GITIGNORE_BLOCK
        rc, out = cli("install"); assert open("CLAUDE.md").read().count("graph-context:begin") == 1, "install is idempotent"
        skill = open(os.path.join(HERE, "..", "SKILL.md"), encoding="utf-8").read()
        assert all(l.strip() in skill for l in gt.CLAUDE_BLOCK.splitlines()), "SKILL.md shows the block the tool writes"
        rc, out = cli("uninstall", "--dry-run"); assert rc == 0 and os.path.exists("dependency_graph.json"), out
        rc, out = cli("uninstall"); assert rc == 0 and "restored byte-identical" in out, out
        assert hashlib.sha256(open("CLAUDE.md", "rb").read()).hexdigest() == before and not os.path.exists(".gitignore") and not os.path.exists("dependency_graph.json") and not os.path.exists(".context"), os.listdir(".")
        print("test_install: all assertions hold"); return 0
    except AssertionError as e:
        print("FAIL:", e); return 1
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)

if __name__ == "__main__":
    sys.exit(main() or test_gate() or test_install())
