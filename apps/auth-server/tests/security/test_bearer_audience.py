"""A token is only accepted where its `aud` says it may go (ADR §11): a token for svc-impots alone never opens the IdP's own APIs."""

import pytest

from fastapi import HTTPException

from authentint.domain.scopes import IDP_AUDIENCE
from authentint.security.bearer import verify_access_token


async def test_a_service_only_token_is_refused_by_the_idp(s, make_user, access_token):
    token = await access_token(await make_user(), "svc:impots.read")

    with pytest.raises(HTTPException) as err:
        await verify_access_token(s, token, audience=IDP_AUDIENCE)
    assert err.value.status_code == 401

async def test_an_openid_token_names_the_idp(s, make_user, access_token):
    token = await access_token(await make_user(), "openid svc:impots.read")

    claims = await verify_access_token(s, token, audience=IDP_AUDIENCE)
    assert IDP_AUDIENCE in claims["aud"]
