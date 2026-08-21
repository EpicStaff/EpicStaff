"""Secret declarations must survive a version round trip.

The import/export serializers this snapshot is built from deliberately strip every
Secret reference, so versioning records the declarations itself. Without that, a
restore silently revokes them — and because the session-start validator treats an
undeclared get_secret() call as fatal, a working flow comes back refusing to run.

Recorded by name rather than id: rotating a credential is delete + recreate
(Secret.value is editable=False with no update endpoint), so an id would dangle on
every rotation. test_a_rotated_secret_relinks_by_name is the case that pins this.
"""

import pytest

from tables.graph_versioning.manager import GraphVersioningManager
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.id_mapper import IDMapper
from tables.models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    Graph,
    Organization,
    PythonCode,
    PythonNode,
    Secret,
    StartNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.services.secrets import secret_service
from tables.services.secrets.declaration_validator import SecretDeclarationValidator
from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES
from tests.fixtures import *  # noqa: F401,F403

CODE = 'def main(**kwargs):\n    return get_secret("{name}")\n'


def _secret(*, org, name):
    return secret_service.create(text=f"value-of-{name}", org=org, name=name)


def _python_node(*, graph, name, declared=(), node_name="Python-Node #1"):
    """A PythonNode whose code reads `name` and which declares `declared`."""
    python_code = PythonCode.objects.create(code=CODE.format(name=name))
    if declared:
        python_code.secrets.set(declared)
    return PythonNode.objects.create(
        graph=graph, node_name=node_name, python_code=python_code
    )


def _save(*, graph, name="v1"):
    return GraphVersioningService().save_version(graph=graph, name=name)


def _restore(*, version, graph):
    return GraphVersioningService().restore_version(
        version,
        expected_save_version=Graph.objects.values_list("save_version", flat=True).get(
            pk=graph.pk
        ),
    )


def _declared_names(*, graph):
    node = PythonNode.objects.filter(graph=graph).select_related("python_code").first()
    return sorted(node.python_code.secrets.values_list("name", flat=True))


# ---------------------------------------------------------------------------
# Collecting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollectSecretDeclarations:
    def test_a_declaring_python_node_is_recorded_under_its_node_id(
        self, manager, graph, default_org
    ):
        secret = _secret(org=default_org, name="STRIPE_KEY")
        node = _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])

        recorded = manager.collect_secret_declarations(graph=graph)

        assert recorded["nodes"] == {str(node.pk): {"python_code": ["STRIPE_KEY"]}}

    def test_a_node_that_declares_nothing_is_absent(self, manager, graph, default_org):
        """Recorded only when there is something to record, so the block stays small
        and a missing key is unambiguous."""
        _python_node(graph=graph, name="STRIPE_KEY")

        assert manager.collect_secret_declarations(graph=graph)["nodes"] == {}

    def test_an_empty_graph_produces_empty_sub_blocks(self, manager, graph):
        assert manager.collect_secret_declarations(graph=graph) == {
            "nodes": {},
            "conditional_edges": [],
            "telegram": {},
        }

    def test_classification_table_pre_and_post_are_recorded_separately(
        self, manager, graph, default_org
    ):
        """One node, two independent declarations — which is why the block keys on
        (node, code_field) rather than node alone."""
        pre_secret = _secret(org=default_org, name="PRE_KEY")
        post_secret = _secret(org=default_org, name="POST_KEY")
        pre = PythonCode.objects.create(code=CODE.format(name="PRE_KEY"))
        pre.secrets.set([pre_secret])
        post = PythonCode.objects.create(code=CODE.format(name="POST_KEY"))
        post.secrets.set([post_secret])
        node = ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name="CDT",
            pre_python_code=pre,
            post_python_code=post,
        )

        recorded = manager.collect_secret_declarations(graph=graph)

        assert recorded["nodes"][str(node.pk)] == {
            "pre_python_code": ["PRE_KEY"],
            "post_python_code": ["POST_KEY"],
        }

    def test_a_declaring_conditional_edge_is_recorded_against_its_source_node(
        self, manager, graph, default_org
    ):
        secret = _secret(org=default_org, name="EDGE_KEY")
        source = StartNode.objects.create(graph=graph, variables={})
        python_code = PythonCode.objects.create(code=CODE.format(name="EDGE_KEY"))
        python_code.secrets.set([secret])
        ConditionalEdge.objects.create(
            graph=graph, source_node_id=source.pk, python_code=python_code
        )

        recorded = manager.collect_secret_declarations(graph=graph)

        assert recorded["conditional_edges"] == [
            {"source_node_id": source.pk, "names": ["EDGE_KEY"]}
        ]

    def test_a_telegram_bot_token_is_recorded(self, manager, graph, default_org):
        """A plain FK, not the M2M, but excluded from its import serializer for the
        same reason and therefore lost the same way."""
        secret = _secret(org=default_org, name="TG_TOKEN")
        node = TelegramTriggerNode.objects.create(
            graph=graph, node_name="TG", telegram_bot_api_key_secret=secret
        )

        recorded = manager.collect_secret_declarations(graph=graph)

        assert recorded["telegram"] == {str(node.pk): "TG_TOKEN"}

    def test_graph_python_code_sites_still_holds_exactly_the_five_known_sites(self):
        """Canary for the decision-5 invariant. The collector walks this same tuple —
        the one the session-start validator walks — so a site the validator enforces
        cannot be a site the snapshot forgets. This asserts the constant's contents
        rather than the collector's behaviour: if a sixth site appears upstream it
        fails here, prompting a matching round-trip test below.
        """
        walked = {(site.model, site.code_field) for site in GRAPH_PYTHON_CODE_SITES}

        assert walked == {
            (PythonNode, "python_code"),
            (WebhookTriggerNode, "python_code"),
            (ClassificationDecisionTableNode, "pre_python_code"),
            (ClassificationDecisionTableNode, "post_python_code"),
            (ConditionalEdge, "python_code"),
        }

    def test_save_version_stores_the_block_in_the_snapshot(self, graph, default_org):
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])

        version = _save(graph=graph)

        assert version.snapshot["secret_declarations"]["nodes"]


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRestoreReattachesDeclarations:
    def test_a_round_trip_keeps_the_declaration_and_leaves_no_violation(
        self, graph, default_org
    ):
        """The end-to-end guarantee, and the case that fails without this work:
        restore wipes the PythonCode rows and assigns fresh node ids, so the
        declaration has to be re-attached through node_mapper."""
        secret = _secret(org=default_org, name="STRIPE_KEY")
        node = _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)

        result = _restore(version=version, graph=graph)

        restored = (
            PythonNode.objects.filter(graph=graph).select_related("python_code").get()
        )
        assert restored.pk != node.pk, "expected a fresh node id after wipe/recreate"
        assert _declared_names(graph=graph) == ["STRIPE_KEY"]
        assert result["warnings"] == []
        assert SecretDeclarationValidator().violations(graph_id=graph.pk) == []

    def test_the_graph_serializer_still_exports_no_secrets_key(
        self, graph, default_org
    ):
        """Pins the mechanism rather than only the outcome: the export path is
        untouched, so re-attachment is doing the work — not some incidental
        persistence of the old rows. Also the canary for decision 2: if someone
        "fixes" this by relaxing the import/export exclusion, this fails."""
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])

        snapshot = GraphVersioningManager().create_snapshot(graph)

        assert "secrets" not in snapshot["nodes"][0]["python_code"]

    def test_a_webhook_trigger_node_relinks_despite_sharing_a_code_field(
        self, graph, default_org
    ):
        """The one genuinely ambiguous lookup. WebhookTriggerNode and PythonNode both
        use code_field 'python_code', so _find_site_row separates them by pk alone --
        sound only because node ids come from one shared sequence. PythonNode is tried
        first, so this exercises the fall-through the other tests never reach."""
        secret = _secret(org=default_org, name="HOOK_KEY")
        python_code = PythonCode.objects.create(code=CODE.format(name="HOOK_KEY"))
        python_code.secrets.set([secret])
        node = WebhookTriggerNode.objects.create(
            graph=graph, node_name="Hook", python_code=python_code
        )
        version = _save(graph=graph)

        result = _restore(version=version, graph=graph)

        restored = (
            WebhookTriggerNode.objects.filter(graph=graph)
            .select_related("python_code")
            .get()
        )
        assert restored.pk != node.pk
        assert list(restored.python_code.secrets.values_list("name", flat=True)) == [
            "HOOK_KEY"
        ]
        assert result["warnings"] == []

    def test_a_python_node_and_a_webhook_node_keep_their_own_declarations(
        self, graph, default_org
    ):
        """Both sites present at once, so a pk mix-up between them would show up as a
        swapped or duplicated declaration rather than passing quietly."""
        py_secret = _secret(org=default_org, name="PY_KEY")
        hook_secret = _secret(org=default_org, name="HOOK_KEY")
        _python_node(graph=graph, name="PY_KEY", declared=[py_secret])
        hook_code = PythonCode.objects.create(code=CODE.format(name="HOOK_KEY"))
        hook_code.secrets.set([hook_secret])
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="Hook", python_code=hook_code
        )
        version = _save(graph=graph)

        result = _restore(version=version, graph=graph)

        py = PythonNode.objects.filter(graph=graph).select_related("python_code").get()
        hook = (
            WebhookTriggerNode.objects.filter(graph=graph)
            .select_related("python_code")
            .get()
        )
        assert list(py.python_code.secrets.values_list("name", flat=True)) == ["PY_KEY"]
        assert list(hook.python_code.secrets.values_list("name", flat=True)) == [
            "HOOK_KEY"
        ]
        assert result["warnings"] == []

    def test_classification_table_pre_and_post_keep_their_distinct_sets(
        self, graph, default_org
    ):
        pre_secret = _secret(org=default_org, name="PRE_KEY")
        post_secret = _secret(org=default_org, name="POST_KEY")
        pre = PythonCode.objects.create(code=CODE.format(name="PRE_KEY"))
        pre.secrets.set([pre_secret])
        post = PythonCode.objects.create(code=CODE.format(name="POST_KEY"))
        post.secrets.set([post_secret])
        ClassificationDecisionTableNode.objects.create(
            graph=graph, node_name="CDT", pre_python_code=pre, post_python_code=post
        )
        version = _save(graph=graph)

        _restore(version=version, graph=graph)

        node = ClassificationDecisionTableNode.objects.filter(graph=graph).get()
        assert sorted(node.pre_python_code.secrets.values_list("name", flat=True)) == [
            "PRE_KEY"
        ]
        assert sorted(node.post_python_code.secrets.values_list("name", flat=True)) == [
            "POST_KEY"
        ]

    def test_a_telegram_bot_token_is_reattached(self, graph, default_org):
        secret = _secret(org=default_org, name="TG_TOKEN")
        TelegramTriggerNode.objects.create(
            graph=graph, node_name="TG", telegram_bot_api_key_secret=secret
        )
        version = _save(graph=graph)

        result = _restore(version=version, graph=graph)

        node = TelegramTriggerNode.objects.filter(graph=graph).get()
        assert node.telegram_bot_api_key_secret_id == secret.pk
        assert result["warnings"] == []

    def test_a_rotated_secret_relinks_by_name(self, graph, default_org):
        """Rotation is delete + recreate, because Secret.value is editable=False and
        there is no update endpoint. Recording the name rather than the id is what
        makes a version saved before a rotation still restore afterwards."""
        original = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[original])
        version = _save(graph=graph)

        original.delete()
        rotated = _secret(org=default_org, name="STRIPE_KEY")

        result = _restore(version=version, graph=graph)

        node = (
            PythonNode.objects.filter(graph=graph).select_related("python_code").get()
        )
        assert list(node.python_code.secrets.values_list("id", flat=True)) == [
            rotated.pk
        ]
        assert result["warnings"] == []


@pytest.mark.django_db
class TestRestoreFailsClosed:
    """A declaration that cannot be re-attached is dropped and reported, never
    guessed. Under-declaring costs a precise error at session start; over-declaring
    authorises a node for a credential nobody granted it."""

    def test_a_deleted_secret_warns_and_leaves_the_declaration_off(
        self, graph, default_org
    ):
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)
        secret.delete()

        result = _restore(version=version, graph=graph)

        assert _declared_names(graph=graph) == []
        assert [w["type"] for w in result["warnings"]] == ["secret_declaration_dropped"]
        assert "STRIPE_KEY" in result["warnings"][0]["reason"]

    def test_the_restore_still_succeeds_when_a_secret_is_gone(self, graph, default_org):
        """A missing secret must not abort the restore — the rest of the graph is
        still worth recovering, and the validator will name the gap precisely."""
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)
        secret.delete()

        result = _restore(version=version, graph=graph)

        assert result["restored"] is True
        assert PythonNode.objects.filter(graph=graph).exists()

    def test_the_dropped_declaration_is_then_caught_by_the_validator(
        self, graph, default_org
    ):
        """Why fail-closed is safe: the gap surfaces as a precise, actionable error at
        session start rather than silently running unauthorised.

        Not a guard for the re-linking itself — it passes with or without it, since
        both leave the node undeclared. What it does guard is the alternative this
        design rejected: auto-declaring from parse_secret_names(code) on restore would
        drive violations to zero here, silently re-authorising a node from the very
        code the allow-list exists to police.
        """
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)
        secret.delete()

        _restore(version=version, graph=graph)

        violations = SecretDeclarationValidator().violations(graph_id=graph.pk)

        assert len(violations) == 1
        assert violations[0].undeclared == ["STRIPE_KEY"]

    def test_a_secret_from_another_org_does_not_relink(self, graph, default_org):
        """Names are only unique per org, so resolution must be org-scoped or a
        version could pull in a same-named credential from elsewhere."""
        other_org = Organization.objects.create(name="other-org")
        secret = _secret(org=default_org, name="SHARED_NAME")
        _python_node(graph=graph, name="SHARED_NAME", declared=[secret])
        version = _save(graph=graph)
        secret.delete()
        _secret(org=other_org, name="SHARED_NAME")

        result = _restore(version=version, graph=graph)

        assert _declared_names(graph=graph) == []
        assert [w["type"] for w in result["warnings"]] == ["secret_declaration_dropped"]


@pytest.mark.django_db
class TestBackwardCompatibility:
    def test_a_snapshot_without_the_block_restores_unchanged(self, graph):
        """Versions saved before this existed have no block. Restoring one must
        behave exactly as it did, not raise."""
        _python_node(graph=graph, name="STRIPE_KEY")
        version = _save(graph=graph)
        del version.snapshot["secret_declarations"]
        version.save(update_fields=["snapshot"])

        result = _restore(version=version, graph=graph)

        assert result["restored"] is True
        assert _declared_names(graph=graph) == []

    def test_an_explicit_none_block_is_tolerated(self, manager, graph):
        assert (
            manager.restore_secret_declarations(
                graph=graph, declarations=None, node_mapper=IDMapper()
            )
            == []
        )

    def test_an_unmapped_node_warns_rather_than_raising(
        self, manager, graph, default_org
    ):
        """filter_snapshot can drop a node whose dependency is missing, leaving its
        declaration with nowhere to attach. node_mapper.get() would raise here;
        get_or_none is what keeps it a warning."""
        _secret(org=default_org, name="STRIPE_KEY")

        warnings = manager.restore_secret_declarations(
            graph=graph,
            declarations={"nodes": {"999": {"python_code": ["STRIPE_KEY"]}}},
            node_mapper=IDMapper(),
        )

        assert [w["type"] for w in warnings] == ["secret_declaration_dropped"]
        assert "not restored" in warnings[0]["reason"]


@pytest.mark.django_db
class TestConditionalEdgeCorrelation:
    def test_a_single_edge_on_a_source_node_relinks(self, graph, default_org):
        secret = _secret(org=default_org, name="EDGE_KEY")
        source = StartNode.objects.create(graph=graph, variables={})
        python_code = PythonCode.objects.create(code=CODE.format(name="EDGE_KEY"))
        python_code.secrets.set([secret])
        ConditionalEdge.objects.create(
            graph=graph, source_node_id=source.pk, python_code=python_code
        )
        version = _save(graph=graph)

        result = _restore(version=version, graph=graph)

        edge = (
            ConditionalEdge.objects.filter(graph=graph)
            .select_related("python_code")
            .get()
        )
        assert list(edge.python_code.secrets.values_list("name", flat=True)) == [
            "EDGE_KEY"
        ]
        assert result["warnings"] == []

    def test_an_edge_with_no_source_node_warns_instead_of_guessing(
        self, manager, graph, default_org
    ):
        _secret(org=default_org, name="EDGE_KEY")

        warnings = manager.restore_secret_declarations(
            graph=graph,
            declarations={
                "conditional_edges": [{"source_node_id": None, "names": ["EDGE_KEY"]}]
            },
            node_mapper=IDMapper(),
        )

        assert [w["type"] for w in warnings] == ["secret_declaration_dropped"]
        assert "no source node" in warnings[0]["reason"]

    def test_two_recorded_edges_on_one_source_are_ambiguous_and_warn(
        self, manager, graph, default_org
    ):
        """Two edges branching off one node cannot be told apart after restore, so
        neither is linked — guessing would grant a declaration to an edge nobody
        declared it for."""
        _secret(org=default_org, name="EDGE_KEY")
        source = StartNode.objects.create(graph=graph, variables={})
        node_mapper = IDMapper()
        node_mapper.map(NODE_MAPPING_KEY, source.pk, source.pk)

        warnings = manager.restore_secret_declarations(
            graph=graph,
            declarations={
                "conditional_edges": [
                    {"source_node_id": source.pk, "names": ["EDGE_KEY"]},
                    {"source_node_id": source.pk, "names": ["EDGE_KEY"]},
                ]
            },
            node_mapper=node_mapper,
        )

        assert [w["type"] for w in warnings] == ["secret_declaration_dropped"]
        assert "ambiguous" in warnings[0]["reason"]


@pytest.mark.django_db
class TestCreateGraphFromVersion:
    def test_a_new_graph_from_a_version_keeps_the_declaration(
        self, service, graph, default_org
    ):
        """create-graph runs a different code path from restore and lost the
        declaration identically."""
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)

        result = service.create_graph_from_version(version)

        new_graph = Graph.objects.get(pk=result["graph_id"])
        assert new_graph.pk != graph.pk
        assert _declared_names(graph=new_graph) == ["STRIPE_KEY"]
        assert SecretDeclarationValidator().violations(graph_id=new_graph.pk) == []

    def test_a_deleted_secret_warns_on_the_create_graph_path_too(
        self, service, graph, default_org
    ):
        secret = _secret(org=default_org, name="STRIPE_KEY")
        _python_node(graph=graph, name="STRIPE_KEY", declared=[secret])
        version = _save(graph=graph)
        secret.delete()

        result = service.create_graph_from_version(version)

        assert [w["type"] for w in result["warnings"]] == ["secret_declaration_dropped"]
