# Decision register (public)

Design decisions behind the protocol, in the order they were made. Folded = absorbed into a later decision
(kept here for traceability). Dates: 2026-09-24 unless noted.

| id | Decision | Supersedes / resolves | Status |
|----|----------|-----------------------|--------|
| D1 | v1: closed node objects, open root | — | folded into D13 |
| D2 | Node ids pattern-constrained (`^[a-z0-9][a-z0-9_-]*$`), applied to ids, keys, `current_node`, edges | — | active |
| D3 | JSON Schema draft 2020-12 | — | active |
| D4 | Ship a minimal seed template | — | active |
| S1 | `dependency_graph.json` lives at the project root | — | active |
| S2 | v1: single SKILL.md, `/graph-*` as sub-commands | — | folded into D16 |
| S3 | init scans design docs + referenced code, no blind source walk | — | folded into D17 |
| S4 | Skill text and stored artifacts in English | — | active |
| S5 | Every edge target must exist | — | folded into D18 (now rule R1) |
| D5 | Registry mapping lives in `config.registries`; project CLAUDE.md carries prose nuance + a pointer | resolves OP1 | active |
| D6 | Bounded footprint: fixed path list, marked blocks, install/uninstall, sha256 snapshot, rule R6 | — | active (footprint shrunk by D20) |
| D7 | Compaction = fold superseded decisions / resolved issues into the survivor via `folded[]`; proposal-only | — | active |
| D8 | Typed edges `resolves` and `supersedes` | — | active |
| D9 | `growth_threshold` default 5, tunable; init idempotent, preserves human decisions; `--reset-structure` | — | active |
| D10 | `source_ref` single-valued on decision/issue nodes only; growth measured on the feature side | resolves OP2 | active |
| D11 | `code_roots` not in config; derived from component nodes | resolves OP3 | active |
| D12 | Component layer under Root; R7 components always visible; R8 no reinvention | — | active |
| D13 | Root closed: `current_node`, `nodes`, `config` only | resolves OP4; supersedes D1 | active |
| D14 | Staleness check (code newer than docs, missing paths, unknown `source_ref`) | — | active |
| D15 | First application target: the skill's own repo, then a real project | — | active |
| D16 | Thin delegating skills per command | supersedes S2 | folded into D21 → D23 |
| D17 | Component detection = top-level directory listing; S3 governs `code_targets` derivation | supersedes S3 | active |
| D18 | S5 absorbed into R1 | supersedes S5 | active |
| D19 | Handover template hardening: legend, "Resolved this session" line, who/when, local-only marker | — | active |
| D20 | Package as a Claude Code plugin (marketplace + `plugin/`); skill files never enter the project; paths via `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`; footprint = graph + handover + 2 marked blocks | refines D6 | active |
| D21 | Delegate skills renamed to `install/uninstall/init/hydrate/handover/compact` under the plugin namespace; bare `/graph-*` is impossible for plugin skills | refines D16 | folded into D23 |
| D22 | Protocol skill renamed `graph-context-sync` → `protocol` (was registering as `graph-context-sync:graph-context-sync`) | — | active |
| D23 | Plugin name shortened to `graph` (marketplace stays `graph-context-sync`): commands read `/graph:hydrate`, `/graph:init`, …; install string `graph@graph-context-sync` | refines D21 (folded D21, D16, S2) | folded into D27 (2026-09-24, user approval 「d23 → d27 の畳み込み」) |
| D24 | Content-based staleness in addition to timestamps: registry ↔ graph (unindexed ids, orphan `source_ref`, lost `folded` ids), docs-only nodes compared with the code of their parent / affected nodes, shipped registers treated as code + registry | extends D14 | active |
| D25 | Handover §2 tables, §6 counts/results and §7 timestamps are generated from the graph, never retyped; manual rows marked `(manual)` | extends D19 | active |
| D26 | Protocol as code: `tools/graph_tool.py` executes R1, hydrate, check (growth/fold/staleness), handover tables, fold, split; rule R9 — every id/count/timestamp shown comes from the tool. Rationale: every forgotten update in the authoring session was caught by a mechanical check or a peer, never by the author | extends D24, D25 | active (released in 3.2.0 by user decision 2026-09-24, Q1 「OK」; purpose-level validation still open, see private plan) |
| D27 | Repositories re-created (user, 2026-09-24): public `yu2scalar/graph-context` = the plugin only, marketplace `graph-context`, install `graph@graph-context`; private `yu2scalar/graph-context-dev` = project root holding the design records (`CLAUDE.md`, `docs/`, `dependency_graph.json`, `.context/graph_tool.log`) with the public repo as submodule `public/`. Marker strings renamed to `graph-context:begin/end`. Public history restarts at 3.2.0; the pre-3.2.0 history (hashes cited in the private plans) is kept as `.archive/graph-context-sync-history.bundle` in the private repo; the old remote `graph-context-sync` is to be deleted later. Reason (user): the records the skill must keep accurate had no git history because design and public skill shared one repo | supersedes the marketplace-name part of D23 and the "markers unchanged" choice (12:59 handover, decision 5) | active |
