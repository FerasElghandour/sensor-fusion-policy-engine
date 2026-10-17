import pytest

from fusion_compliance_loop.scenarios import SCENARIOS

SCENARIO_NAMES = [fn.__name__.replace("scenario_", "") for fn in SCENARIOS]


def test_ten_or_more_scenarios_defined():
    assert len(SCENARIOS) >= 10


@pytest.mark.parametrize("scenario_fn", SCENARIOS, ids=SCENARIO_NAMES)
def test_scenario_runs_without_error(scenario_fn):
    name, engine_or_planner, camera, result_or_outcomes = scenario_fn()
    assert name
    assert engine_or_planner is not None


def test_each_compliance_scenario_triggers_its_named_rule():
    """Guards against a scenario accidentally tripping a different rule than
    the one it's meant to demonstrate (e.g. leftover synthetic fields causing
    a misclassification hit instead of the intended missing-permission one)."""
    from fusion_compliance_loop.scenarios import (
        scenario_forbidden_cross_domain_fusion,
        scenario_incorrect_classification_markings,
        scenario_missing_release_permissions,
        scenario_normal_matching,
    )

    expectations = {
        scenario_normal_matching: "RESTRICTED_CROSS_DOMAIN",
        scenario_forbidden_cross_domain_fusion: "FORBIDDEN_DOMAIN",
        scenario_missing_release_permissions: "MISSING_RELEASE_PERMISSION",
        scenario_incorrect_classification_markings: "MISCLASSIFIED_FIELD",
    }
    for scenario_fn, expected_rule in expectations.items():
        _name, _engine, _camera, result = scenario_fn()
        assert any(expected_rule in rule for rule in result.applied_policy_rules), (
            f"{scenario_fn.__name__} expected {expected_rule} but got {result.applied_policy_rules}"
        )


def test_expected_scenario_topics_covered():
    required_topics = {
        "normal_matching",
        "delayed_sensor_data",
        "missing_timestamp",
        "conflicting_locations",
        "multiple_possible_matches",
        "dependent_evidence",
        "incorrect_classification_markings",
        "forbidden_cross_domain_fusion",
        "missing_release_permissions",
        "repeated_evidence_seeking_loop",
    }
    assert required_topics.issubset(set(SCENARIO_NAMES))
