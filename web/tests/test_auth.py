"""Login plumbing tests.

Both pieces here are small and pure, and both are the kind of thing that only
shows up when it is already wrong: a token that is not the character we think it
is, or a post-login redirect that leaves the site.
"""

import pytest


@pytest.mark.parametrize("subject", [
    "",                        # no subject at all
    "12345",                   # not an EVE token
    "CHARACTER:12345",         # not an EVE character token
    "CORPORATION:EVE:12345",   # a corporation token is not a character
    "ALLIANCE:EVE:12345",
    "CHARACTER:EVE:",          # no id
    "CHARACTER:EVE:not-a-number",
])
def test_only_eve_character_subjects_are_accepted(subject):
    from web.auth import SsoClient, SsoError
    from web.config import SsoConfig

    with pytest.raises(SsoError):
        SsoClient(SsoConfig()).character_from_claims({"sub": subject})


def test_character_subject_yields_id_and_name():
    from web.auth import SsoClient
    from web.config import SsoConfig

    client = SsoClient(SsoConfig())
    assert client.character_from_claims(
        {"sub": "CHARACTER:EVE:90000001", "name": "Dev Pilot"}) == (90000001, "Dev Pilot")
    # A token without a name is no reason to refuse the login
    assert client.character_from_claims({"sub": "CHARACTER:EVE:90000002"})[1] == "Unknown pilot"


@pytest.mark.parametrize("value", [
    "",
    "fits/1",
    "//evil.example.com",
    "https://evil.example.com/",
    "/\\evil.example.com",
    "/" + "x" * 600,
])
def test_unsafe_next_targets_fall_back_to_the_root(value):
    from web.api.auth import _safe_next

    assert _safe_next(value) == "/"


@pytest.mark.parametrize("value", ["/", "/fits/12", "/fits?q=rifter#top"])
def test_relative_next_targets_are_kept(value):
    from web.api.auth import _safe_next

    assert _safe_next(value) == value
