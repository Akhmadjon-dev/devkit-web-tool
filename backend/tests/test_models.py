from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import Plan, PlanTask, Review, TaskRole


def test_plan_task_defaults_role_to_engineer():
    t = PlanTask(id="t1", title="x", spec="do x", branch="feat/x")
    assert t.role == TaskRole.engineer
    assert t.depends_on == []


def test_plan_round_trips_through_json_schema_shape():
    plan = Plan(tasks=[PlanTask(id="t1", title="x", spec="do x", branch="feat/x", depends_on=[])])
    schema = Plan.model_json_schema()
    assert "tasks" in schema["properties"]
    dumped = plan.model_dump()
    assert Plan.model_validate(dumped) == plan


def test_review_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        Review.model_validate({"verdict": "maybe", "issues": [], "notes": ""})


def test_review_accepts_valid_verdict():
    r = Review.model_validate({"verdict": "request_changes", "issues": ["missing tests"], "notes": "n/a"})
    assert r.verdict == "request_changes"
