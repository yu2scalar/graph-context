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
                   "tbd-01": {"id": "tbd-01", "type": "issue", "name": "q", "docs": ["docs/log.md"], "code_targets": [], "source_ref": "TBD-01", "part_of": ["f"], "affects": ["f"]}}}
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
        assert rc == 0 and "d-001" not in g2["nodes"] and g2["nodes"]["d-002"]["folded"] == ["D-001"], g2["nodes"]["d-002"]
        # split via CLI
        class B: graph = p; node = "f"; children = ["f-sub=d-002"]; lang = "en"
        rc = gt.cmd_split(gt.load(p), B); g3 = gt.load(p)
        assert rc == 0 and g3["nodes"]["f-sub"]["part_of"] == ["f"] and g3["nodes"]["d-002"]["part_of"] == ["f-sub"]
        # add-node via CLI
        class C: graph = p; id = "g"; type = "feature"; name = "G"; part_of = "core"; doc = None; code = None; source_ref = None; status = "IN_PROGRESS"; lang = "en"
        rc = gt.cmd_add_node(gt.load(p), C); g4 = gt.load(p)
        assert rc == 0 and g4["nodes"]["g"]["part_of"] == ["core"]
        # handover-tables --verify: OK on a fresh paste, FAIL after a graph change
        import io, contextlib
        g5 = gt.load(p); g5["current_node"] = "f"; gt.save(p, g5)
        class H: graph = p; verify = None; lang = "en"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): gt.cmd_handover_tables(gt.load(p), H)
        out = buf.getvalue()
        ho = os.path.join(tmp, "HANDOVER.md")
        open(ho, "w").write("# x\n## 2. Components and Subgraph Context Range\n" + out.split("<!-- §6 lines -->")[0] + "Files read outside the subgraph\n## 3. Hard Decisions Log\n## 6. Decision Drift\n" + out.split("<!-- §6 lines -->")[1].split("<!-- §7 table -->")[0] + "## 7. Staleness\n" + out.split("<!-- §7 table -->")[1] + f"\n<!-- graph_tool handover-tables @{gt.git_head()} graph md5 {gt.md5(p)} (unchanged) -->\n")
        class VOK: graph = p; verify = ho; lang = "en"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = gt.cmd_handover_tables(gt.load(p), VOK)
        assert rc == 0, buf.getvalue()
        class S2: graph = p; node = "g"; status = "DONE"; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): gt.cmd_set_status(gt.load(p), S2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = gt.cmd_handover_tables(gt.load(p), VOK)
        assert rc == 1 and "md5" in buf.getvalue(), buf.getvalue()
        # add-doc + dry-run hydrate + lint-handover
        class AD: graph = p; cmd = "add-doc"; node = "g"; path = "docs/log.md"; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): rc = gt.cmd_add_path(gt.load(p), AD)
        assert rc == 0 and "docs/log.md" in gt.load(p)["nodes"]["g"]["docs"]
        before = gt.md5(p)
        class DR: graph = p; node = "g"; dry_run = True; lang = "en"
        with contextlib.redirect_stdout(io.StringIO()): gt.cmd_hydrate(gt.load(p), DR)
        assert gt.md5(p) == before, "dry-run must not write"
        g6 = gt.load(p); cur = g6["current_node"]
        good = f"# h\nGenerated: x by graph_tool @y\n## 1. A\n- current_node: `{cur}`\n## 4. U\nResolved and removed: U1\n| # |\n|---|\n| U2 |\n## 5. R\n1. `/graph:hydrate {cur}`\n## 7. S\n<!-- graph_tool handover-tables @{gt.git_head()} graph md5 {gt.md5(p)} (unchanged) -->\n"
        hp = os.path.join(tmp, "H2.md"); open(hp, "w").write(good)
        class LH: graph = p; handover = hp; lang = "en"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = gt.cmd_lint_handover(gt.load(p), LH)
        assert rc == 0, buf.getvalue()
        open(hp, "w").write(good.replace(f"- current_node: `{cur}`", "- current_node: `zzz`").replace("| U2 |", "| U1 |"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = gt.cmd_lint_handover(gt.load(p), LH)
        assert rc == 1 and "U1" in buf.getvalue(), buf.getvalue()
        print("test_graph_tool: all assertions hold")
    except AssertionError as e:
        ok = False; print("FAIL:", e)
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
