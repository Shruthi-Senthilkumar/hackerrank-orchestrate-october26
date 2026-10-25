import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit.linker import link_observations  # noqa: E402
from audit.models import Identity, Observation  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402

T = datetime(2026, 9, 11, tzinfo=timezone.utc)


def _obs(resource_id, link_keys, references=(), **kw):
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
    return Observation(
        resource_id=resource_id, link_keys=frozenset(link_keys), references=frozenset(references), **defaults
    )


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


def _identity(user_id, email, phone="", email_hash=""):
    return Identity(
        user_id=user_id,
        current_name="",
        current_email=email,
        current_phone=phone,
        current_email_hash=email_hash,
        emails=frozenset({email} if email else set()),
        phones=frozenset({phone} if phone else set()),
        hashes=frozenset({email_hash} if email_hash else set()),
    )


def test_reference_closure_links_a_resource_that_points_at_an_already_linked_one():
    """A directed, one-hop reference (the real search_documents_primary
    shape: a search document, linked via its OWN email, carrying a
    source_resource_id pointing at an account) links that target even
    though the target has no identity value of its own."""
    search_obs = _obs("search_999", {"search_999", "jonas.berg@outlook.com"}, references={"account_006"})
    account_obs = _obs(
        "account_006", {"account_006"}, system_id="account_service", category="USER_PROFILE"
    )  # no identity value of its own

    identity = _identity("user_006", "jonas.berg@outlook.com")
    time_view = build_time_view(T)
    linked = link_observations([search_obs, account_obs], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"account_006", "search_999"}
    rules = {l.observation.resource_id: l.rule for l in linked}
    assert rules["account_006"] == "reference_closure"


def test_reference_closure_never_traverses_a_shared_identity_value():
    """Phase 3b: a shared email/cohort/region/status-like value must
    never bridge resources, no matter how many people's records share
    it. 20 unrelated people's records plus the target person's own
    record all share one 'agent email', a cohort, and a region; none of
    the 20 others must link, only the target's own identity-matched
    record."""
    target = _obs(
        "account_006", {"account_006", "jonas.berg@outlook.com"},
        system_id="account_service", category="USER_PROFILE",
        attrs={"agent_email": "agent@support.example", "cohort": "home_lifestyle", "region": "eu-west"},
    )
    decoys = [
        _obs(
            f"account_{900 + i}", {f"account_{900 + i}", f"person{i}@example.com"},
            system_id="account_service", category="USER_PROFILE",
            attrs={"agent_email": "agent@support.example", "cohort": "home_lifestyle", "region": "eu-west"},
        )
        for i in range(20)
    ]

    identity = _identity("user_006", "jonas.berg@outlook.com")
    time_view = build_time_view(T)
    linked = link_observations([target, *decoys], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"account_006"}


def test_reference_closure_is_one_hop_only():
    """A two-hop chain (A links directly via its own email and
    references B; B has no identity of its own but references C) must
    link B but NOT C -- B's own references are never followed, since B
    was linked by reference_closure, not directly."""
    a = _obs("search_999", {"search_999", "jonas.berg@outlook.com"}, references={"account_006"})
    b = _obs("account_006", {"account_006"}, system_id="account_service", category="USER_PROFILE", references={"export_777"})
    c = _obs("export_777", {"export_777"}, system_id="export_service", category="USER_EXPORT")

    identity = _identity("user_006", "jonas.berg@outlook.com")
    time_view = build_time_view(T)
    linked = link_observations([a, b, c], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"search_999", "account_006"}
    assert "export_777" not in linked_ids


def test_reference_closure_hub_guard_blocks_target_referenced_by_many_identities():
    """Two different, unrelated people's own, directly-linked resources
    (each carrying its own real email) both reference the SAME target
    (a hub -- e.g. a shared status/queue value that happens to
    coincide). That target must never link to either of them, even
    though each referencing resource is itself validly, directly linked
    to its own person."""
    hub_target = _obs("backup_1", {"backup_1"}, system_id="backup_service", category="BACKUP_ARCHIVE")
    search_1 = _obs("search_1", {"search_1", "jonas.berg@outlook.com"}, references={"backup_1"})
    search_2 = _obs("search_2", {"search_2", "someone.else@example.com"}, references={"backup_1"})

    identity = _identity("user_006", "jonas.berg@outlook.com")
    time_view = build_time_view(T)
    linked = link_observations([hub_target, search_1, search_2], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    # search_1 still links directly (its own email matches); the hub
    # target does not, and search_2 (someone else's record) never did.
    assert linked_ids == {"search_1"}
    assert "backup_1" not in linked_ids


def test_reference_closure_refuses_a_target_that_belongs_to_someone_else():
    """The referenced record itself carries ANOTHER person's identifier
    (not a hub -- just one source, one target) -- it must never be
    linked to this person even though the reference is a clean,
    directed, one-hop pointer."""
    search_obs = _obs("search_999", {"search_999", "jonas.berg@outlook.com"}, references={"account_777"})
    someone_elses_target = _obs(
        "account_777", {"account_777", "someone.else@example.com"}, system_id="account_service", category="USER_PROFILE"
    )

    identity = _identity("user_006", "jonas.berg@outlook.com")
    time_view = build_time_view(T)
    linked = link_observations([search_obs, someone_elses_target], identity, time_view)

    linked_ids = {l.observation.resource_id for l in linked}
    assert linked_ids == {"search_999"}
    assert "account_777" not in linked_ids


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
