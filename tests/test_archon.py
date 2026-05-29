from __future__ import annotations

from code_reviewer.archon import extract_archon_run_id, first_json_object


def test_first_json_object_handles_archon_log_prefix() -> None:
    output = """{"level":30,"msg":"db.connection_sqlite_selected"}
{
  "runs": [
    {"id": "run-1", "workflowName": "ai-code-review"}
  ]
}
"""

    data = first_json_object(output)

    assert data["runs"][0]["id"] == "run-1"


def test_extract_archon_run_id_reads_json_log_lines() -> None:
    output = """Running workflow: ai-code-review
{"level":30,"workflowRunId":"7bac03432fab6b262675fd36a2eea2f3","msg":"workflow_starting"}
"""

    assert extract_archon_run_id(output) == "7bac03432fab6b262675fd36a2eea2f3"
