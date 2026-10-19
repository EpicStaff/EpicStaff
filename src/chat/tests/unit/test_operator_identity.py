import pytest
from application.orchestrators.identity import OperatorIdentity
from application.ports import AbstractIdentityProvider, IntrospectedUser
from domain.errors import InvalidTokenError, NotFoundError, NotMemberError
from litestar.exceptions import ClientException


class StubProvider(AbstractIdentityProvider):
    def __init__(self):
        self.calls = 0

    async def introspect(self, jwt):
        self.calls += 1
        return IntrospectedUser(user_id=4, org_ids=[1, 2], is_superadmin=False) if jwt == "good" else None

    async def chats_actions(self, jwt, org_id):
        self.calls += 1
        if org_id == 1:
            return {"read", "use"}
        if org_id == 2:
            return set()
        raise NotMemberError(org_id)


async def test_resolve_and_cache():
    provider = StubProvider()
    identity = OperatorIdentity(provider, cache_seconds=60)
    operator = await identity.resolve("good", "1")
    assert (operator.user_id, operator.org_id, operator.actions) == (4, 1, {"read", "use"})
    assert operator.allows("read") and not operator.allows("create")
    await identity.resolve("good", "1")
    assert provider.calls == 2  # introspect + permissions, served from cache the second time


async def test_errors():
    identity = OperatorIdentity(StubProvider(), cache_seconds=60)
    with pytest.raises(InvalidTokenError):
        await identity.resolve("bad", "1")
    with pytest.raises(InvalidTokenError):
        await identity.resolve(None, "1")
    with pytest.raises(ClientException):
        await identity.resolve("good", None)
    with pytest.raises(ClientException):
        await identity.resolve("good", "abc")
    with pytest.raises(ClientException):
        await identity.resolve("good", "\u0661")   # Arabic-Indic digit one: isdigit() but not an org id
    with pytest.raises(NotFoundError):
        await identity.resolve("good", "3")   # not a member: looks like nothing exists


async def test_member_without_permissions_resolves_with_no_actions():
    operator = await OperatorIdentity(StubProvider(), cache_seconds=60).resolve("good", "2")
    assert operator.actions == set() and not operator.allows("read")


async def test_superadmin_may_use_any_org():
    class Admin(StubProvider):
        async def introspect(self, jwt):
            return IntrospectedUser(user_id=1, org_ids=[], is_superadmin=True)

        async def chats_actions(self, jwt, org_id):
            return {"create", "read", "update", "delete", "use"}

    operator = await OperatorIdentity(Admin(), cache_seconds=60).resolve("good", "77")
    assert operator.is_superadmin and operator.allows("delete")


async def test_the_operator_carries_the_introspected_display_name():
    class Named(StubProvider):
        async def introspect(self, jwt):
            return IntrospectedUser(user_id=4, org_ids=[1], is_superadmin=False, display_name="Ada Lovelace")

    assert (await OperatorIdentity(Named(), cache_seconds=60).resolve("good", "1")).display_name == "Ada Lovelace"
    assert (await OperatorIdentity(StubProvider(), cache_seconds=60).resolve("good", "1")).display_name is None
