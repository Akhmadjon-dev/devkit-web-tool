from __future__ import annotations

from app.core.executor import (
    ENGINEER_ROLE,
    PLANNER_ROLE,
    REVIEWER_ROLE,
    _extract_result_fields,
    build_command,
)


def test_build_command_json_role_has_no_verbose_flag():
    cmd = build_command("do the thing", PLANNER_ROLE, claude_bin="claude")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "do the thing" in cmd
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--verbose" not in cmd
    assert "--json-schema" in cmd  # planner role carries the Plan schema
    assert "--disallowedTools" in cmd


def test_build_command_stream_json_role_requires_verbose():
    cmd = build_command("implement the spec", ENGINEER_ROLE, claude_bin="claude")
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd
    assert "--include-partial-messages" in cmd


def test_reviewer_role_uses_cheap_model_by_default():
    cmd = build_command("review this", REVIEWER_ROLE, claude_bin="claude")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "haiku"


def test_build_command_includes_budget_and_add_dirs():
    cmd = build_command(
        "x", ENGINEER_ROLE, claude_bin="claude", max_budget_usd=2.5, add_dirs=["/some/shared/dir"]
    )
    assert "--max-budget-usd" in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2.5"
    assert "--add-dir" in cmd
    assert "/some/shared/dir" in cmd


def test_extract_result_fields_plain_json_output():
    payload = {
        "session_id": "abc123",
        "total_cost_usd": 0.0123,
        "num_turns": 3,
        "duration_ms": 4200,
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "result": '{"tasks": []}',
    }
    fields = _extract_result_fields(payload)
    assert fields["session_id"] == "abc123"
    assert fields["total_cost_usd"] == 0.0123
    assert fields["structured"] == {"tasks": []}
    assert fields["is_error"] is False


def test_extract_result_fields_structured_object_result():
    payload = {"result": {"verdict": "approve", "issues": [], "notes": "looks fine"}, "subtype": "success"}
    fields = _extract_result_fields(payload)
    assert fields["structured"] == {"verdict": "approve", "issues": [], "notes": "looks fine"}
    assert fields["is_error"] is False


def test_extract_result_fields_error_subtype():
    payload = {"result": "", "subtype": "error_max_turns"}
    fields = _extract_result_fields(payload)
    assert fields["is_error"] is True


def test_extract_result_fields_non_json_text_result():
    payload = {"result": "just some plain text, not json", "subtype": "success"}
    fields = _extract_result_fields(payload)
    assert fields["structured"] is None
    assert fields["result_text"] == "just some plain text, not json"
