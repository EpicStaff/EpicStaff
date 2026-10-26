"""Unit tests for the usage-report building blocks in delete_services.usage.

No database: BucketCollector is plain Python over `(entity_id, ref_id, name)`
triples, so the dedup rules can be pinned without fixtures.
"""

from tables.services.delete_services.usage import (
    SAMPLE_LIMIT,
    BucketCollector,
    build_reports,
)


def test_same_id_through_several_paths_counts_once():
    """One Flow reaching a config through several paths is one flow.

    LLMConfig's FLOWS bucket reaches the containing Graph through a
    decision-table node, a decision-table prompt and a flow assistant; the
    same flow found three ways must count once, not three times.
    """
    flows = BucketCollector("flows", visible=True)
    for _path in ("cdt_node", "cdt_prompt", "flow_assistant"):
        flows.add(1, 42, "Support flow")

    assert flows.bucket_for(1).visible_count == 1


def test_invisible_bucket_counts_hidden_refs_without_disclosing_them():
    collector = BucketCollector("flows", visible=False)
    collector.add(1, 10, "secret flow")

    bucket = collector.bucket_for(1)

    assert bucket.total_count == 1
    assert bucket.visible_count == 0
    assert bucket.visible_sample == []
    assert bucket.has_hidden is True


def test_sample_is_capped_and_marked_truncated():
    collector = BucketCollector("flows", visible=True)
    collector.add_rows(
        ((1, ref_id, f"flow {ref_id}") for ref_id in range(SAMPLE_LIMIT + 1))
    )

    bucket = collector.bucket_for(1)

    assert bucket.visible_count == SAMPLE_LIMIT + 1
    assert len(bucket.visible_sample) == SAMPLE_LIMIT
    assert bucket.truncated is True


def test_every_id_gets_a_report_even_with_no_references():
    """Uniform shape: an unreferenced id reports empty buckets, not nothing."""
    collector = BucketCollector("flows", visible=True)
    collector.add(1, 10, "flow")

    reports = build_reports([1, 2], [collector])

    assert set(reports) == {1, 2}
    assert reports[2].buckets[0].visible_count == 0
    assert reports[2].blocked is False


def test_refs_come_back_sorted_whatever_order_the_queries_returned():
    """A preview and a refresh must show the same sample.

    The source queries have no ORDER BY, so rows can arrive in any order; the
    collector sorts on id so the capped sample does not shift.
    """
    collector = BucketCollector("flows", visible=True)
    collector.add(1, 9, "b")
    collector.add(1, 7, "a")
    collector.add(1, 3, "c")

    refs = collector.bucket_for(1).visible_refs

    assert [ref.id for ref in refs] == [3, 7, 9]
