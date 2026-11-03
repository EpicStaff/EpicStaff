import pytest

from tables.models import Secret
from rbac.models import Organization
from tables.services.secrets import (
    SecretResolutionError,
    secret_resolver,
    secret_service,
)
from src.shared.models import KnowledgeNodeData
from tables.services.secrets.secret_resolver import extract_secret_marker_names


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretResolver")


@pytest.mark.django_db
class TestResolveById:
    def test_none_id_returns_none(self, org):
        assert secret_resolver.resolve(secret_id=None, org_id=org.id) is None

    def test_returns_exact_plaintext(self, org):
        secret = secret_service.create(
            text="sk-resolver-plaintext-1234", org=org, name="resolver-happy"
        )
        assert (
            secret_resolver.resolve(secret_id=secret.pk, org_id=org.id)
            == "sk-resolver-plaintext-1234"
        )

    def test_missing_row_raises(self, org):
        secret = secret_service.create(text="sk-doomed", org=org, name="resolver-gone")
        secret_id = secret.pk
        secret.delete()

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve(secret_id=secret_id, org_id=org.id)

    def test_corrupt_ciphertext_raises_resolution_error_not_decryption_error(self, org):
        secret = secret_service.create(text="sk-fine", org=org, name="resolver-corrupt")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        # The caller sees one exception type regardless of the underlying cause.
        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve(secret_id=secret.pk, org_id=org.id)

    def test_error_message_names_context_and_never_the_value(self, org):
        secret = secret_service.create(
            text="sk-must-not-appear", org=org, name="resolver-msg"
        )
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve(
                secret_id=secret.pk, org_id=org.id, context="LLMConfigData.api_key"
            )

        message = str(exc.value)
        assert "LLMConfigData.api_key" in message
        assert str(secret.pk) in message
        assert "sk-must-not-appear" not in message


@pytest.mark.django_db
class TestResolveMany:
    """Batched counterpart to `resolve()` -- one `pk__in` query for N secret
    ids belonging to the same org, instead of N individual queries. No caller
    in this codebase yet; exists so a future batch-resolution need (e.g. a
    node type with multiple secret-backed fields) doesn't have to reinvent
    the org-scoped-batch-lookup pattern."""

    def test_empty_list_returns_empty_dict_with_no_query(
        self, org, django_assert_num_queries
    ):
        with django_assert_num_queries(0):
            assert secret_resolver.resolve_many(secret_ids=[], org_id=org.id) == {}

    def test_none_entries_are_ignored(self, org):
        secret = secret_service.create(text="sk-many-1", org=org, name="many-one")

        resolved = secret_resolver.resolve_many(
            secret_ids=[None, secret.pk, None], org_id=org.id
        )

        assert resolved == {secret.pk: "sk-many-1"}

    def test_resolves_every_id_in_a_single_query(self, org, django_assert_num_queries):
        secret_a = secret_service.create(text="sk-many-a", org=org, name="many-a")
        secret_b = secret_service.create(text="sk-many-b", org=org, name="many-b")
        secret_c = secret_service.create(text="sk-many-c", org=org, name="many-c")

        with django_assert_num_queries(1):
            resolved = secret_resolver.resolve_many(
                secret_ids=[secret_a.pk, secret_b.pk, secret_c.pk], org_id=org.id
            )

        assert resolved == {
            secret_a.pk: "sk-many-a",
            secret_b.pk: "sk-many-b",
            secret_c.pk: "sk-many-c",
        }

    def test_duplicate_ids_are_deduplicated_into_one_row(
        self, org, django_assert_num_queries
    ):
        secret = secret_service.create(text="sk-many-dup", org=org, name="many-dup")

        with django_assert_num_queries(1):
            resolved = secret_resolver.resolve_many(
                secret_ids=[secret.pk, secret.pk, secret.pk], org_id=org.id
            )

        assert resolved == {secret.pk: "sk-many-dup"}

    def test_missing_row_is_omitted_not_raised(self, org):
        """Unlike `resolve()`, a missing/unresolvable id must not raise --
        the whole point of batching is that one bad id in the list must not
        take the others down with it. Absence from the result IS the signal;
        callers that need fail-closed behavior treat a missing key as
        unresolvable themselves -- see the module docstring above."""
        secret = secret_service.create(text="sk-many-gone", org=org, name="many-gone")
        secret_id = secret.pk
        secret.delete()

        assert secret_resolver.resolve_many(secret_ids=[secret_id], org_id=org.id) == {}

    def test_foreign_org_id_is_omitted(self, org, other_org):
        foreign = secret_service.create(
            text="sk-many-foreign", org=other_org, name="many-foreign"
        )

        assert (
            secret_resolver.resolve_many(secret_ids=[foreign.pk], org_id=org.id) == {}
        )

    def test_corrupt_ciphertext_is_omitted_not_raised(self, org):
        """A row that exists but fails to decrypt is treated the same as a
        missing row for batching purposes -- omitted, not propagated -- so
        one corrupt secret cannot abort resolution for every other id in the
        same batch."""
        secret = secret_service.create(text="sk-many-ok", org=org, name="many-ok")
        good = secret_service.create(text="sk-many-good", org=org, name="many-good")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        resolved = secret_resolver.resolve_many(
            secret_ids=[secret.pk, good.pk], org_id=org.id
        )

        assert resolved == {good.pk: "sk-many-good"}



from src.shared.models import (
    EmbedderConfigData,
    LLMConfigData,
    McpToolData,
    PythonCodeData,
    RealtimeAgentChatData,
)

CARRIERS = [
    (LLMConfigData, "api_key_secret_id", "api_key"),
    (EmbedderConfigData, "api_key_secret_id", "api_key"),
    (McpToolData, "auth_secret_id", "auth"),
    (RealtimeAgentChatData, "rt_api_key_secret_id", "rt_api_key"),
    (RealtimeAgentChatData, "transcript_api_key_secret_id", "transcript_api_key"),
]


class TestCarrierFields:
    """The carrier must be readable in-process but invisible in every dump: it is
    what keeps Secret row ids off the wire."""

    @pytest.mark.parametrize("model_cls,carrier,target", CARRIERS)
    def test_secret_id_is_readable_in_process_but_never_dumped(self, model_cls, carrier, target):
        payload = model_cls.model_construct(**{carrier: 42, target: None})

        assert getattr(payload, carrier) == 42
        assert carrier not in payload.model_dump(mode="json")
        assert carrier not in payload.model_dump_json()
        assert payload.model_dump(mode="json")[target] is None


from pydantic import BaseModel

from src.shared.models import EmbedderData, LLMData


@pytest.mark.django_db
class TestResolvePayload:
    def test_fills_nested_slots_across_lists_and_leaves_input_clean(self, org):
        llm_secret = secret_service.create(
            text="sk-llm-nested", org=org, name="payload-llm"
        )
        embed_secret = secret_service.create(
            text="sk-embed-nested", org=org, name="payload-embed"
        )

        class Holder(BaseModel):
            llms: list[LLMData] = []
            embedder: EmbedderData | None = None

        payload = Holder(
            llms=[
                LLMData(
                    provider="openai",
                    config=LLMConfigData(
                        model="gpt-4o", api_key_secret_id=llm_secret.pk
                    ),
                )
            ],
            embedder=EmbedderData(
                provider="openai",
                config=EmbedderConfigData(
                    model="text-embedding-3-small",
                    api_key_secret_id=embed_secret.pk,
                ),
            ),
        )

        resolved = secret_resolver.resolve_payload(payload=payload, org_id=org.id)

        assert resolved.llms[0].config.api_key == "sk-llm-nested"
        assert resolved.embedder.config.api_key == "sk-embed-nested"

        # Resolution happens on a copy: the caller's object must not have been touched.
        assert payload.llms[0].config.api_key is None
        assert payload.embedder.config.api_key is None

    def test_walks_into_dict_values(self, org):
        secret = secret_service.create(text="sk-in-dict", org=org, name="payload-dict")

        class Holder(BaseModel):
            by_name: dict[str, LLMConfigData] = {}

        resolved = secret_resolver.resolve_payload(
            payload=Holder(
                by_name={
                    "a": LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk)
                }
            ),
            org_id=org.id,
        )
        assert resolved.by_name["a"].api_key == "sk-in-dict"

    def test_null_carrier_leaves_slot_none(self, org):
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(model="gpt-4o"), org_id=org.id
        )
        assert resolved.api_key is None

    def test_non_secret_fields_untouched(self, org):
        secret = secret_service.create(text="sk-keep", org=org, name="payload-keep")
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(
                model="gpt-4o",
                temperature=0.25,
                base_url="https://example.test",
                api_key_secret_id=secret.pk,
            ),
            org_id=org.id,
        )
        assert resolved.model == "gpt-4o"
        assert resolved.temperature == 0.25
        assert resolved.base_url == "https://example.test"

    def test_unresolvable_carrier_raises_with_locating_context(self, org):
        secret = secret_service.create(text="sk-x", org=org, name="payload-doomed")
        secret_id = secret.pk
        secret.delete()

        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve_payload(
                payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret_id),
                org_id=org.id,
            )

        assert "LLMConfigData.api_key" in str(exc.value)

    def test_dump_of_resolved_payload_still_omits_the_carrier(self, org):
        secret = secret_service.create(text="sk-dump", org=org, name="payload-dump")
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk),
            org_id=org.id,
        )

        dumped = resolved.model_dump_json()
        assert "sk-dump" in dumped
        assert "api_key_secret_id" not in dumped


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org SecretResolver Other")


@pytest.mark.django_db
class TestOrgScopedResolution:
    """Resolution is where plaintext is produced. Before this, it applied no
    tenant check at all — every org guarantee lived at write time in the
    serializers, which two live paths bypass entirely."""

    def test_foreign_org_secret_is_not_resolvable(self, org, other_org):
        secret = secret_service.create(
            text="sk-belongs-to-other", org=other_org, name="foreign"
        )

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve(secret_id=secret.pk, org_id=org.id)

    def test_own_org_secret_still_resolves(self, org, other_org):
        # The inverse matters as much: an org filter that denies everything
        # would also pass the test above.
        secret = secret_service.create(text="sk-mine", org=org, name="own")

        assert secret_resolver.resolve(secret_id=secret.pk, org_id=org.id) == "sk-mine"

    def test_foreign_org_message_is_identical_to_a_missing_row(self, org, other_org):
        """A foreign secret and a nonexistent one must be indistinguishable, so
        existence in another org never leaks."""
        foreign = secret_service.create(
            text="sk-foreign", org=other_org, name="foreign-msg"
        )
        foreign_id = foreign.pk

        with pytest.raises(SecretResolutionError) as foreign_exc:
            secret_resolver.resolve(
                secret_id=foreign_id, org_id=org.id, context="LLMConfigData.api_key"
            )

        foreign.delete()
        with pytest.raises(SecretResolutionError) as missing_exc:
            secret_resolver.resolve(
                secret_id=foreign_id, org_id=org.id, context="LLMConfigData.api_key"
            )

        assert str(foreign_exc.value) == str(missing_exc.value)

    def test_resolve_payload_rejects_a_foreign_org_carrier(self, org, other_org):
        secret = secret_service.create(
            text="sk-foreign-payload", org=other_org, name="foreign-payload"
        )

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve_payload(
                payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk),
                org_id=org.id,
            )

    @pytest.mark.parametrize(
        "call",
        [
            lambda secret: secret_resolver.resolve(secret_id=secret.pk),
            lambda secret: secret_resolver.resolve_many(secret_ids=[secret.pk]),
            lambda secret: secret_resolver.resolve_payload(
                payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk)
            ),
            lambda secret: secret_resolver.resolve_named(names=[secret.name]),
        ],
        ids=["resolve", "resolve_many", "resolve_payload", "resolve_named"],
    )
    def test_every_lookup_requires_an_org(self, org, call):
        """No caller may opt out of scoping. A default of None meaning 'skip the
        check' is exactly how the unscoped lookup survived this long."""
        secret = secret_service.create(text="sk-req", org=org, name="requires-org")

        with pytest.raises(TypeError):
            call(secret)


@pytest.mark.django_db
class TestResolveNamed:
    """Resolution is by NAME, because the declaration is a string literal in the
    node's own code. There is no id involved, so nothing can dangle across
    installations and there is no foreign pk to reject."""

    def test_returns_name_to_plaintext(self, org):
        secret_service.create(text="sk-one", org=org, name="STRIPE_KEY")
        secret_service.create(text="sk-two", org=org, name="SLACK_TOKEN")

        resolved = secret_resolver.resolve_named(
            names=["STRIPE_KEY", "SLACK_TOKEN"], org_id=org.id
        )

        assert resolved == {"STRIPE_KEY": "sk-one", "SLACK_TOKEN": "sk-two"}

    def test_empty_list_returns_empty_dict(self, org):
        assert secret_resolver.resolve_named(names=[], org_id=org.id) == {}

    def test_unknown_name_is_omitted_not_raised(self, org):
        """The name comes from a string literal in user code, so a typo must not
        stop the whole flow from starting. The sandbox raises
        SecretNotAvailableError at the get_secret() call and lists what WAS
        injected — the informative place to fail, and still fail-closed."""
        secret_service.create(text="sk-real", org=org, name="REAL")

        resolved = secret_resolver.resolve_named(
            names=["REAL", "TYPOED"], org_id=org.id
        )

        assert resolved == {"REAL": "sk-real"}

    def test_deleted_row_is_omitted(self, org):
        secret = secret_service.create(text="sk-gone", org=org, name="NAMED_GONE")
        secret.delete()

        assert secret_resolver.resolve_named(names=["NAMED_GONE"], org_id=org.id) == {}

    def test_corrupt_ciphertext_still_raises(self, org):
        """A row that exists but will not decrypt is an infrastructure fault, not
        a user typo, so it fails loudly rather than being silently omitted."""
        secret = secret_service.create(text="sk-fine", org=org, name="NAMED_CORRUPT")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve_named(names=["NAMED_CORRUPT"], org_id=org.id)

    def test_another_orgs_name_is_not_resolvable(self, org, other_org):
        secret_service.create(
            text="sk-foreign-named", org=other_org, name="SHARED_NAME"
        )

        assert secret_resolver.resolve_named(names=["SHARED_NAME"], org_id=org.id) == {}

    def test_same_name_in_two_orgs_resolves_to_each_own_value(self, org, other_org):
        """Secret has UniqueConstraint(org, name), so a name is unique per org but
        may repeat across them. Each org must get its own value."""
        secret_service.create(text="sk-mine", org=org, name="SHARED_NAME")
        secret_service.create(text="sk-theirs", org=other_org, name="SHARED_NAME")

        assert secret_resolver.resolve_named(names=["SHARED_NAME"], org_id=org.id) == {
            "SHARED_NAME": "sk-mine"
        }
        assert secret_resolver.resolve_named(
            names=["SHARED_NAME"], org_id=other_org.id
        ) == {"SHARED_NAME": "sk-theirs"}

    def test_resolve_payload_fills_the_reserved_pair(self, org):
        secret_service.create(text="sk-node", org=org, name="NODE_KEY")
        payload = PythonCodeData(
            venv_name="default",
            code='def main(): return get_secret("NODE_KEY")',
            entrypoint="main",
            secret_names=["NODE_KEY"],
        )

        resolved = secret_resolver.resolve_payload(payload=payload, org_id=org.id)

        assert resolved.secrets == {"NODE_KEY": "sk-node"}
        # The input object is what gets persisted — it must not have been touched.
        assert payload.secrets == {}

    def test_unpaired_secret_names_field_is_a_configuration_error(self, org):
        class Broken(BaseModel):
            secret_names: list[str] = []

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve_payload(
                payload=Broken(secret_names=["ANY"]), org_id=org.id
            )


@pytest.mark.django_db
class TestResolveHeaderMarkers:
    """`epicstaff_secret(<name>)` markers inside the extra_headers dict resolve to
    plaintext on the payload copy only; the caller's original keeps the markers,
    so no raw credential ever reaches it."""

    def test_marker_replaced_with_plaintext(self, org):
        secret_service.create(text="sk-hdr", org=org, name="AZURE_KEY")

        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(
                model="gpt-4o", extra_headers={"api-key": "epicstaff_secret(AZURE_KEY)"}
            ),
            org_id=org.id,
        )

        assert resolved.extra_headers == {"api-key": "sk-hdr"}

    def test_marker_in_a_template_keeps_surrounding_text(self, org):
        secret_service.create(text="tok-123", org=org, name="BEARER")

        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(
                model="gpt-4o",
                extra_headers={"Authorization": "Bearer epicstaff_secret(BEARER)"},
            ),
            org_id=org.id,
        )

        assert resolved.extra_headers == {"Authorization": "Bearer tok-123"}

    def test_many_headers_and_markers_resolve_in_a_single_query(
        self, org, django_assert_num_queries
    ):
        secret_service.create(text="v1", org=org, name="H1")
        secret_service.create(text="v2", org=org, name="H2")

        with django_assert_num_queries(1):
            resolved = secret_resolver.resolve_payload(
                payload=LLMConfigData(
                    model="gpt-4o",
                    extra_headers={
                        "A": "epicstaff_secret(H1)",
                        "B": "x epicstaff_secret(H2) epicstaff_secret(H1)",
                    },
                ),
                org_id=org.id,
            )

        assert resolved.extra_headers == {"A": "v1", "B": "x v2 v1"}

    def test_value_without_marker_is_untouched(self, org):
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(
                model="gpt-4o", extra_headers={"X-Trace": "plain-value"}
            ),
            org_id=org.id,
        )

        assert resolved.extra_headers == {"X-Trace": "plain-value"}

    def test_empty_headers_issues_no_query(self, org, django_assert_num_queries):
        with django_assert_num_queries(0):
            resolved = secret_resolver.resolve_payload(
                payload=LLMConfigData(model="gpt-4o", extra_headers={}), org_id=org.id
            )

        assert resolved.extra_headers == {}

    def test_unknown_name_raises_with_locating_context(self, org):
        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve_payload(
                payload=LLMConfigData(
                    model="gpt-4o", extra_headers={"api-key": "epicstaff_secret(NOPE)"}
                ),
                org_id=org.id,
            )

        message = str(exc.value)
        assert "LLMConfigData.extra_headers" in message
        assert "NOPE" in message

    def test_input_payload_keeps_the_marker(self, org):
        secret_service.create(text="sk-orig", org=org, name="ORIG")
        payload = LLMConfigData(
            model="gpt-4o", extra_headers={"api-key": "epicstaff_secret(ORIG)"}
        )

        secret_resolver.resolve_payload(payload=payload, org_id=org.id)

        # Resolution happens on a copy: the caller's object must keep the marker.
        assert payload.extra_headers == {"api-key": "epicstaff_secret(ORIG)"}

    def test_foreign_org_name_is_not_resolvable(self, org, other_org):
        secret_service.create(text="sk-foreign", org=other_org, name="FOREIGN_HDR")

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve_payload(
                payload=LLMConfigData(
                    model="gpt-4o",
                    extra_headers={"api-key": "epicstaff_secret(FOREIGN_HDR)"},
                ),
                org_id=org.id,
            )



@pytest.mark.django_db
class TestResolveSuffixedHeaderFields:
    """Every field whose name ends with `extra_headers` resolves its markers, so
    the RAG header carriers next to the RAG api keys need no registration."""

    def test_knowledge_node_embedder_and_llm_headers_resolve(self, org):
        secret_service.create(text="emb-plain", org=org, name="EMB_HDR")
        secret_service.create(text="llm-plain", org=org, name="LLM_HDR")
        payload = KnowledgeNodeData(
            node_name="knowledge",
            query="q",
            input_map={},
            embedder_extra_headers={"X-Emb": "epicstaff_secret(EMB_HDR)"},
            llm_extra_headers={"X-Llm": "Bearer epicstaff_secret(LLM_HDR)"},
        )

        resolved = secret_resolver.resolve_payload(payload=payload, org_id=org.id)

        assert resolved.embedder_extra_headers == {"X-Emb": "emb-plain"}
        assert resolved.llm_extra_headers == {"X-Llm": "Bearer llm-plain"}
        assert payload.embedder_extra_headers == {"X-Emb": "epicstaff_secret(EMB_HDR)"}

    def test_embedder_config_headers_resolve(self, org):
        secret_service.create(text="emb-cfg-plain", org=org, name="EMB_CFG_HDR")

        resolved = secret_resolver.resolve_payload(
            payload=EmbedderConfigData(
                model="text-embedding-3-small",
                extra_headers={"api-key": "epicstaff_secret(EMB_CFG_HDR)"},
            ),
            org_id=org.id,
        )

        assert resolved.extra_headers == {"api-key": "emb-cfg-plain"}

    def test_realtime_rag_headers_resolve(self, org):
        secret_service.create(text="rt-emb-plain", org=org, name="RT_EMB_HDR")
        payload = RealtimeAgentChatData(
            role="r",
            goal="g",
            backstory="b",
            org_id=org.id,
            knowledge_collection_id=None,
            rt_model_name="m",
            temperature=None,
            memory=False,
            connection_key="k",
            wake_word=None,
            stop_prompt=None,
            language=None,
            voice_recognition_prompt=None,
            voice="alloy",
            rag_embedder_extra_headers={"X-Emb": "epicstaff_secret(RT_EMB_HDR)"},
        )

        resolved = secret_resolver.resolve_payload(payload=payload, org_id=org.id)

        assert resolved.rag_embedder_extra_headers == {"X-Emb": "rt-emb-plain"}

    def test_foreign_org_marker_in_a_suffixed_field_is_rejected(self, org, other_org):
        secret_service.create(text="sk-foreign", org=other_org, name="FOREIGN_EMB_HDR")

        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve_payload(
                payload=KnowledgeNodeData(
                    node_name="knowledge",
                    query="q",
                    input_map={},
                    embedder_extra_headers={"X-Emb": "epicstaff_secret(FOREIGN_EMB_HDR)"},
                ),
                org_id=org.id,
            )

        assert "KnowledgeNodeData.embedder_extra_headers" in str(exc.value)


@pytest.mark.django_db
class TestResolveHeaderMarkersDirectly:
    """The public entry point used where there is no payload model to walk."""

    def test_returns_a_resolved_copy_and_leaves_the_input_alone(self, org):
        secret_service.create(text="direct-plain", org=org, name="DIRECT_HDR")
        headers = {"X-Key": "epicstaff_secret(DIRECT_HDR)", "X-Trace": "t"}

        resolved = secret_resolver.resolve_header_markers(headers=headers, org_id=org.id)

        assert resolved == {"X-Key": "direct-plain", "X-Trace": "t"}
        assert headers == {"X-Key": "epicstaff_secret(DIRECT_HDR)", "X-Trace": "t"}

    @pytest.mark.parametrize("headers", [None, {}])
    def test_empty_input_is_returned_without_a_query(
        self, org, headers, django_assert_num_queries
    ):
        with django_assert_num_queries(0):
            assert (
                secret_resolver.resolve_header_markers(headers=headers, org_id=org.id)
                == headers
            )

    def test_unknown_name_raises_with_the_given_context(self, org):
        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve_header_markers(
                headers={"X-Key": "epicstaff_secret(MISSING)"},
                org_id=org.id,
                context="EmbeddingConfig.extra_headers",
            )

        assert "EmbeddingConfig.extra_headers" in str(exc.value)
        assert "MISSING" in str(exc.value)

    def test_foreign_org_name_is_not_resolvable(self, org, other_org):
        secret_service.create(text="sk-other", org=other_org, name="OTHER_DIRECT")

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve_header_markers(
                headers={"X-Key": "epicstaff_secret(OTHER_DIRECT)"}, org_id=org.id
            )



@pytest.mark.parametrize(
    "headers, expected",
    [
        (None, set()),
        ({}, set()),
        ({"X-Trace": "plain"}, set()),
        ({"A": "epicstaff_secret( ONE )", "B": "x epicstaff_secret(TWO) epicstaff_secret(ONE)"}, {"ONE", "TWO"}),
        ({"A": 1}, set()),
        (["epicstaff_secret(ONE)"], set()),
        ("epicstaff_secret(ONE)", set()),
    ],
    ids=["none", "empty", "no-marker", "several", "non-string", "list", "string"],
)
def test_extract_secret_marker_names(headers, expected):
    assert extract_secret_marker_names(headers) == expected
