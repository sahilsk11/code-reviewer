# Dynamic workflows and run state phased implementation plan

## Phase 1: Dynamic workflow generation

Status: DONE

- Extract agent prompts from the static Archon YAML into package prompt files.
- Add a Python workflow builder that renders the Archon YAML from node metadata, prompt files, harness/provider, model, and workflow name.
- Keep `install-workflow` useful by writing a generated default workflow instead of copying a static resource.
- Make `code-review review` generate a runtime workflow before invoking Archon.

## Phase 2: Code-reviewer run state

Status: DONE

- Add a small SQLite store owned by code-reviewer under `~/.code-reviews`.
- Track review runs by repository, PR number, head SHA, workflow name, workflow path, status, timestamps, and exit code.
- Mark prior active runs for the same repository and PR as canceled/replaced when a new run starts.
- Ensure runner exits update the state to succeeded or failed.

## Phase 3: CLI, docs, and verification

Status: DONE

- Add CLI options for model and harness.
- Remove consumer-side whole-run retry from the example GitHub Actions workflow.
- Update docs for dynamic workflow generation and run-state storage.
- Add focused tests for workflow rendering and run-state transitions.
- Run the full test suite plus an integrated local probe that renders and records a dry run without invoking Archon.

## Final verification

Status: DONE

Final verification completed:

- `uv run --extra dev pytest`: 27 passed.
- `uv run --extra dev python -m compileall src`: passed.
- Integrated fake-Archon probe: ran `code-review review` against a temporary repo/event, generated a run-specific workflow with `model: probe-model`, recorded a succeeded run in SQLite, captured `probe-archon-run`, and verified the stored workflow path/YAML.
