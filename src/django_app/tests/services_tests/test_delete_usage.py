"""Unit tests for the usage-report building blocks in delete_services.usage.

No database: BucketCollector is plain Python over `(entity_id, ref_id, name)`
triples, so the dedup rules can be pinned without fixtures.
"""

from tables.services.delete_services.usage import (
    SAMPLE_LIMIT,
    BucketCollector,
    RefKind,
    build_reports,
)


def test_same_id_under_different_kinds_stays_two_references():
    """The AGENTS bucket merges `tables.Agent` and `agents.AgentDefinition`.

    Their ids come from different sequences, so Agent#5 and AgentDefinition#5
    are two different parents. Keying on the bare id would fold them into
    one, under-counting usage and under-reporting `blocked`.
    """
    agents = BucketCollector("agents", visible=True)
    agents.add(1, 5, "Legacy bot", kind=RefKind.AGENT)
    agents.add(1, 5, "New bot", kind=RefKind.AGENT_DEFINITION)

    bucket = agents.bucket_for(1)

    assert bucket.visible_count == 2
    assert {(ref.kind, ref.id) for ref in bucket.visible_refs} == {
        (RefKind.AGENT, 5),
        (RefKind.AGENT_DEFINITION, 5),
    }


def test_same_kind_and_id_through_several_paths_counts_once():
    """One Flow reaching a config through several paths is one flow.

    LLMConfig's FLOWS bucket reaches the containing Graph through a
    decision-table node, a decision-table prompt and a flow assistant; the
    same flow found three ways must count once, not three times.
    """
    flows = BucketCollector("flows", visible=True)
    for _path in ("cdt_node", "cdt_prompt", "flow_assistant"):
        flows.add(1, 42, "Support flow", kind=RefKind.FLOW)

    assert flows.bucket_for(1).visible_count == 1


def test_invisible_bucket_counts_hidden_refs_without_disclosing_them():
    collector = BucketCollector("flows", visible=False)
    collector.add(1, 10, "secret flow", kind=RefKind.FLOW)

    bucket = collector.bucket_for(1)

    assert bucket.total_count == 1
    assert bucket.visible_count == 0
    assert bucket.visible_sample == []
    assert bucket.has_hidden is True


def test_sample_is_capped_and_marked_truncated():
    collector = BucketCollector("flows", visible=True)
    collector.add_rows(
        ((1, ref_id, f"flow {ref_id}") for ref_id in range(SAMPLE_LIMIT + 1)),
        kind=RefKind.FLOW,
    )

    bucket = collector.bucket_for(1)

    assert bucket.visible_count == SAMPLE_LIMIT + 1
    assert len(bucket.visible_sample) == SAMPLE_LIMIT
    assert bucket.truncated is True


def test_every_id_gets_a_report_even_with_no_references():
    """Uniform shape: an unreferenced id reports empty buckets, not nothing."""
    collector = BucketCollector("flows", visible=True)
    collector.add(1, 10, "flow", kind=RefKind.FLOW)

    reports = build_reports([1, 2], [collector])

    assert set(reports) == {1, 2}
    assert reports[2].buckets[0].visible_count == 0
    assert reports[2].blocked is False


def test_refs_come_back_sorted_whatever_order_the_queries_returned():
    """A preview and a refresh must show the same sample.

    The source queries have no ORDER BY, so rows can arrive in any order; the
    collector sorts on `(kind, id)` so the capped sample does not shift.
    """
    agents = BucketCollector("agents", visible=True)
    agents.add(1, 9, "b", kind=RefKind.AGENT_DEFINITION)
    agents.add(1, 7, "a", kind=RefKind.AGENT)
    agents.add(1, 3, "c", kind=RefKind.AGENT_DEFINITION)

    refs = agents.bucket_for(1).visible_refs

    assert [(ref.kind, ref.id) for ref in refs] == [
        (RefKind.AGENT, 7),
        (RefKind.AGENT_DEFINITION, 3),
        (RefKind.AGENT_DEFINITION, 9),
    ]
