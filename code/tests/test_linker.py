import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit.linker import link_observations  # noqa: E402
from audit.models import Identity, Observation  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402

T = datetime(2026, 9, 11, tzinfo=timezone.utc)


def _obs(resource_id, link_keys, **kw):
    defaults = dict(
        system_id="search_service",
        category="SEARCH_INDEX_ENTRY",
        store="s",
        source_id="s",
        manifest_time=T,
        observed_at=T,
        exists=True,
        identifiers_present=frozenset(),
        attrs={},
    )
    defaults.update(kw)
    return Observation(resource_id=resource_id, link_keys=frozenset(link_keys), **defaults)


def test_decoy_with_same_name_is_excluded():
    """Three near-identical names, three different emails/accounts. Only
    the one matching the target identity's own email must link; the
    other two (one with a near-identical name, one with an identical
    first+last name swap) must never link, since a name alone never
    links."""
    target = _obs("search_001", {"search_001", "jonas.berg@outlook.com"}, attrs={"display_name": "Jonas Berg"})
    decoy_similar_name = _obs(
        "search_8814", {"search_8814", "jonas.berglund@outlook.com"}, attrs={"display_name": "Jonas Berglund"}
    )
    decoy_swapped_name = _obs(
        "search_4203", {"search_4203", "joana.berg@outlook.com"}, attrs={"display_name": "Joana Berg"}
    )

    identity = Identity(
        user_id="user_006",
        current_name="Jonas Berg",
        current_email="jonas.berg@outlook.com",
        current_phone="",
        current_email_hash="",
        emails=frozenset({"jonas.berg@outlook.com"}),
        phones=frozenset(),
        hashes=frozenset(),
    )
    time_view = build_time_view(T)
    linked = link_observations([target, decoy_similar_name, decoy_swapped_name], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"search_001"}


def test_reference_closure_links_a_resource_that_points_at_an_already_linked_one():
    account_obs = _obs(
        "account_006", {"account_006", "jonas.berg@outlook.com"}, system_id="account_service", category="USER_PROFILE"
    )
    referencing_obs = _obs("search_999", {"search_999", "account_006"})  # no email of its own
    unrelated_obs = _obs("search_888", {"search_888", "account_999"})  # references someone else entirely

    identity = Identity(
        user_id="user_006",
        current_name="Jonas Berg",
        current_email="jonas.berg@outlook.com",
        current_phone="",
        current_email_hash="",
        emails=frozenset({"jonas.berg@outlook.com"}),
        phones=frozenset(),
        hashes=frozenset(),
    )
    time_view = build_time_view(T)
    linked = link_observations([account_obs, referencing_obs, unrelated_obs], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"account_006", "search_999"}
    rules = {l.observation.resource_id: l.rule for l in linked}
    assert rules["search_999"] == "reference_closure"


def test_phone_and_hash_also_link_without_matching_email():
    obs_by_phone = _obs("account_002", {"account_002", "+1-555-0100"})
    obs_by_hash = _obs("account_003", {"account_003", "deadbeef" * 8})

    identity = Identity(
        user_id="user_999",
        current_name="Someone",
        current_email="someone@example.com",
        current_phone="+1-555-0100",
        current_email_hash="deadbeef" * 8,
        emails=frozenset({"someone@example.com"}),
        phones=frozenset({"+1-555-0100"}),
        hashes=frozenset({"deadbeef" * 8}),
    )
    time_view = build_time_view(T)
    linked = link_observations([obs_by_phone, obs_by_hash], identity, time_view)
    assert {l.observation.resource_id for l in linked} == {"account_002", "account_003"}
