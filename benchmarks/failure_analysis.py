"""Structured failure analysis over a completed benchmark run: which
adversarial conditions correlate with false/missed matches, which tags are
the latency bottlenecks, and where the AI model was least confident."""

from collections import Counter, defaultdict

from fusion_compliance_loop.adversarial_generator import Mission

from .approaches import MissionOutcome

AI_UNCERTAINTY_BAND = (0.4, 0.6)


def analyze_failures(missions: list[Mission], outcomes_by_approach: dict[str, list[MissionOutcome]]) -> dict:
    by_id = {m.mission_id: m for m in missions}
    analysis = {}

    for approach, outcomes in outcomes_by_approach.items():
        false_match_tags = Counter()
        missed_match_tags = Counter()
        latency_by_tag = defaultdict(list)
        errors_sample = []
        uncertain_cases = []

        for outcome in outcomes:
            mission = by_id[outcome.mission_id]
            true_match = mission.ground_truth["correct_match_radar_id"]
            predicted = outcome.predicted_match_radar_id
            tags = outcome.tags or ["untagged"]

            for tag in tags:
                latency_by_tag[tag].append(outcome.latency_s)

            if true_match is not None and predicted is not None and predicted != true_match:
                for tag in tags:
                    false_match_tags[tag] += 1
            if true_match is not None and predicted is None:
                for tag in tags:
                    missed_match_tags[tag] += 1

            if outcome.error:
                errors_sample.append({"mission_id": outcome.mission_id, "tags": tags, "error": outcome.error})

            if (
                approach.startswith("C")
                and outcome.top_candidate_score is not None
                and AI_UNCERTAINTY_BAND[0] <= outcome.top_candidate_score <= AI_UNCERTAINTY_BAND[1]
            ):
                uncertain_cases.append({"mission_id": outcome.mission_id, "tags": tags, "score": outcome.top_candidate_score})

        avg_latency_by_tag = {tag: sum(v) / len(v) for tag, v in latency_by_tag.items()}
        latency_bottlenecks = sorted(avg_latency_by_tag.items(), key=lambda kv: kv[1], reverse=True)[:5]

        analysis[approach] = {
            "common_false_matches_by_tag": false_match_tags.most_common(10),
            "common_missed_matches_by_tag": missed_match_tags.most_common(10),
            "latency_bottleneck_tags": latency_bottlenecks,
            "error_count": len(errors_sample),
            "errors_sample": errors_sample[:10],
            "ai_uncertain_cases": sorted(uncertain_cases, key=lambda c: abs(c["score"] - 0.5))[:15],
        }

    return analysis
