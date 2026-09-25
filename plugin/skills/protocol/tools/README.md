# tools/

> Status: v3.3.0-dev.2 (2026-09-25, D36 entity files, add/append/attach/migrate/render; dev.1: D33: backlog, set-next, set-issue, close, PLANNED; v3.2.0 2026-09-24, D26; revised after peer review: seconds precision, --lang default from config, D24b scoping, scan counts, log, footer, write helpers)

`graph_tool.py` is the executable part of the protocol (D26). Run it from the project root that holds
`dependency_graph.json`; it resolves the schema relative to its own location.

| command | writes? | what it does |
|---|---|---|
| `validate` | no | JSON Schema (if `jsonschema` is installed) + every R1 rule; exit 1 on errors |
| `hydrate <node_id>` | `current_node` | full Impact Assessment Checklist for the node (hops 0–2 over all edge kinds, both directions) |
| `check` | no | growth candidates, fold candidates, staleness (timestamp + D24 content layer), proposals (`--lang ja`) |
| `handover-tables` | no | Markdown for handover §2, §6 lines, §7 table — paste verbatim (D25) |
| `fold <victim> <survivor>` | yes | fold a superseded decision / resolved issue into the survivor, then validate |
| `split <node> <child>=<id,id> …` | yes | create `function` children under a feature and move attachments, then validate |
| `set-status <node> <PLANNED\|IN_PROGRESS\|BLOCKED\|DONE\|none>` | yes | change `wip_status` (not on issues), then validate |
| `add <id> <decision\|issue\|plan\|rule> "<name>" --section 'Heading=text' … (--new-not-duplicate "<why>" \| --duplicate-of <id>)` | yes | search before add (P4): lists every existing entity of that type + similarity top 5; writes nothing until the outcome is stated; then creates `docs/entities/<id>.md` (fixed headings, Log last) and the node (`file`, `sha256`) together |
| `append <id> "<text>"` | yes | entity files are append-only: adds a dated line under `## Log`; refuses when the file was edited outside the tool |
| `migrate [--dry-run]` | yes | gives every node without an entity file its file, mechanically (reproducible: same input → same files): decision / issue text = the row of the first matching registry in `config.registries` order, every other copy (table rows and `- <ID> ` list items in registries + `docs_scope`) verbatim with file:line, folded ids' copies, 「…」 quotes collected, `Public summary` from the registry with `public_column`; missing sections say "(not recorded in the source)"; ids whose copies differ are listed for review |
| `attach <id> --section … [--as-plan]` | yes | give one existing node its entity file from given sections (`--as-plan` turns a feature / function into a plan) |
| `rename <id> "<name>"` | yes | the name is a copy of the entity heading: changes both and logs it |
| `render [--check]` | views | writes / checks every `config.views` document (decisions, public-decisions, issues, current, plans); views are also re-rendered on every accepted write |
| `backlog [--owner user\|claude] [--next-only] [--component C] [--all]` | no | graph-wide Backlog view (D33): open issues (default filter = `config.backlog_filter`), all PLANNED / IN_PROGRESS / BLOCKED / `next` nodes; issues the filter hides are counted per component; warns when nothing carries `next`. The same table is printed in `hydrate` |
| `set-next <node> [--off]` | yes | set / clear `next` (not on component / decision), then validate |
| `set-issue <issue> [--owner user\|claude] [--trigger TEXT]` | yes | set who resolves an issue and when, then validate |
| `close <issue> <resolved\|transferred> --by <decision\|commit\|text>` | yes | set `issue_status` + `closed_by`; when `--by` names a decision (node id or registry id) also adds `<decision>.resolves -> <issue>`, then validate |
| `add-edge <src> <kind> <dst>` | yes | add one edge, then validate |
| `set-current <node\|null>` | yes | set `current_node`, then validate |
| `add-node <id> <type> "<name>" [--part-of P] [--doc F]… [--code F]… [--source-ref ID] [--status S] [--next] [--owner O] [--trigger T]` | yes | create a node (issue nodes start with `issue_status: open`; `--owner`/`--trigger` issue only), then validate |
| `handover-tables --verify <handover.md>` | no | compare the pasted §2 / §6 / §7 blocks and the footer md5 with current output; `RESULT: OK` or the differing rows (U14) |
| `lint-prose` | no | version strings and `Dx–Dy` ranges in SKILL.md, README, references, delegates vs plugin.json and the decision register (marketplace.json is scanned but carries no version); lists every string checked (U15). Not covered: prose naming sub-commands/features |
| `lint-handover <handover.md> [--prev <previous.md>]` | no | with `--prev`: every U-id in the previous §4 must still be a row or be named as resolved/transferred; plus free-text cross-checks: §1 states current_node and mentions commits since the footer HEAD, §5 names current_node, §4 resolved ids have no remaining row, exactly one footer, tool-stamped `Generated:` header, no empty action on flagged §7 rows, warns on empty `why it matters` |
| `add-doc <node> <path>` / `add-code <node> <path>` | yes | append to `docs` / `code_targets`, then validate |
| `hydrate --dry-run <node>` | no | full checklist without writing `current_node` (for reviews) |

`--verify` semantics: differing §2/§6 rows or a footer md5 mismatch → `MISMATCH` (exit 1). §7-only differences while the
graph md5 is unchanged → `WARN` with a diagnosis (HEAD moved, or a docs/code path was edited after generation): regenerate §7
as the very last step. A hand-typed `Generated:` header → `WARN`.

`--lang ja|en` may be given before or after the sub-command; the default is `config.interaction_language`.
Every write is validated **before** it is saved; an invalid write is refused and nothing is written (U31). Every write appends a line to `graph_tool.log` next to the handover file (session history for handover §6).
Every run ends with a footer `<!-- graph_tool <cmd> @<git head> graph md5 <before>[ -> <after> (WRITTEN)] -->`,
so a pasted block can be traced to a graph state and read-only commands can be seen not to have written.
Timestamps are seconds-precision and compared as datetimes (git commit time for tracked paths, mtime otherwise).

Dependencies: Python 3.8+, standard library. `jsonschema` is optional (schema layer is skipped with a warning).
Test: `python3 test_graph_tool.py` (synthetic graph; exercises validate, hops, growth, fold, split, content layer, add-node,
add-doc, set-status, handover-tables --verify OK/FAIL, lint-handover, hydrate --dry-run, backlog filter + excluded counts, set-next,
set-issue, close by decision / by action, the resolves → issue_status invariant).
