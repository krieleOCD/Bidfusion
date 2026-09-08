"""BidRun contracts and the current slice's transition allowlist.

Covers: state-history coherence, artifact-ref lineage, authorization
gating, terminal-state coherence, and the CREATED -> UPLOADED ->
QUARANTINED allowlist (docs/architecture/level-1-target.md, §5-6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from bidfusion.bidrun import (
    ALLOWED_TRANSITIONS,
    WORKFLOW_NAME,
    WORKFLOW_VERSION,
    IllegalBidRunTransitionError,
    apply_transition,
    create_bid_run,
)
from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    AuthorizationRecord,
    AuthorizationType,
    BidRun,
    BidRunReasonCode,
    BidRunState,
    BidRunTransition,
)

BID_ID = "BID-2026-000123"
OTHER_BID_ID = "BID-2026-000999"
RUN_ID = "RUN-20260805-0001"
OTHER_RUN_ID = "RUN-20260805-0002"
MANIFEST_ARTIFACT_ID = "ART-20260805-000001"
FILE_ARTIFACT_ID = "ART-20260805-000002"
HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
POLICY_VERSION = "1.0.0"


def authorization(
    *,
    accepted: bool = True,
    accepted_at: datetime | None = NOW,
) -> AuthorizationRecord:
    return AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=accepted,
        accepted_at=accepted_at if accepted else None,
        scope="non-production-internal-test",
        policy_version=POLICY_VERSION,
    )


def unaccepted_authorization() -> AuthorizationRecord:
    return authorization(accepted=False, accepted_at=None)


def artifact_reference(
    *,
    artifact_id: str = MANIFEST_ARTIFACT_ID,
    bid_id: str = BID_ID,
    run_id: str = RUN_ID,
    artifact_type: ArtifactType = ArtifactType.RAW_DOCUMENT,
    content_hash: str = HASH_A,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=artifact_type,
        schema_version="1.0.0",
        content_ref=f"files/{artifact_id}.pdf",
        content_hash=content_hash,
    )


# --- AuthorizationRecord -----------------------------------------------


def test_authorization_requires_a_timestamp_when_accepted() -> None:
    with pytest.raises(ValidationError, match="must record when it was accepted"):
        AuthorizationRecord(
            authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
            accepted=True,
            accepted_at=None,
            scope="non-production-internal-test",
            policy_version=POLICY_VERSION,
        )


def test_authorization_rejects_a_timestamp_when_not_accepted() -> None:
    with pytest.raises(ValidationError, match="cannot carry an acceptance timestamp"):
        AuthorizationRecord(
            authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
            accepted=False,
            accepted_at=NOW,
            scope="non-production-internal-test",
            policy_version=POLICY_VERSION,
        )


# --- create_bid_run ------------------------------------------------------


def test_create_bid_run_starts_created_with_empty_history() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    assert run.current_state is BidRunState.CREATED
    assert run.state_history == ()
    assert run.artifact_refs == ()
    assert run.source_package_artifact is None
    assert run.terminal_reason is None
    assert run.workflow_name == WORKFLOW_NAME
    assert run.workflow_version == WORKFLOW_VERSION
    assert run.updated_at == run.created_at


def test_created_state_does_not_require_accepted_authorization() -> None:
    # CREATED is reachable before the operator has confirmed anything;
    # only leaving CREATED requires acceptance.
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    assert run.authorization.accepted is False


# --- apply_transition: the happy path ------------------------------------


def test_full_chain_created_to_uploaded_to_quarantined() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    uploaded_at = NOW + timedelta(seconds=1)
    run = apply_transition(
        run,
        to=BidRunState.UPLOADED,
        occurred_at=uploaded_at,
        authorization=authorization(accepted=True, accepted_at=uploaded_at),
    )
    assert run.current_state is BidRunState.UPLOADED
    assert run.authorization.accepted is True
    assert len(run.state_history) == 1
    assert run.state_history[0].reason_code is BidRunReasonCode.FILES_UPLOADED

    manifest = artifact_reference()
    files = (artifact_reference(artifact_id=FILE_ARTIFACT_ID, content_hash=HASH_B),)
    quarantined_at = uploaded_at + timedelta(seconds=1)
    run = apply_transition(
        run,
        to=BidRunState.QUARANTINED,
        occurred_at=quarantined_at,
        artifact_refs=(manifest, *files),
        source_package_artifact=manifest,
    )
    assert run.current_state is BidRunState.QUARANTINED
    assert run.source_package_artifact == manifest
    assert set(run.artifact_refs) == {manifest, *files}
    assert [transition.to_state for transition in run.state_history] == [
        BidRunState.UPLOADED,
        BidRunState.QUARANTINED,
    ]
    assert run.state_history[1].reason_code is BidRunReasonCode.PACKAGE_QUARANTINED
    assert "quarantined" in run.operator_message.lower()
    assert run.updated_at == quarantined_at
    # authorization/workflow identity survive an unrelated transition unchanged
    assert run.authorization.accepted is True


def test_quarantined_transition_requires_authorization_already_accepted() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="requires an accepted authorization"):
        apply_transition(run, to=BidRunState.UPLOADED, occurred_at=NOW)


# --- illegal transitions --------------------------------------------------


def test_direct_created_to_quarantined_is_rejected() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    with pytest.raises(IllegalBidRunTransitionError):
        apply_transition(run, to=BidRunState.QUARANTINED, occurred_at=NOW)


def test_quarantined_to_completed_is_rejected() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    run = apply_transition(
        run,
        to=BidRunState.UPLOADED,
        occurred_at=NOW,
        authorization=authorization(),
    )
    manifest = artifact_reference()
    run = apply_transition(
        run,
        to=BidRunState.QUARANTINED,
        occurred_at=NOW,
        artifact_refs=(manifest,),
        source_package_artifact=manifest,
    )
    with pytest.raises(IllegalBidRunTransitionError):
        apply_transition(run, to=BidRunState.COMPLETED, occurred_at=NOW)


def test_transition_cannot_move_backwards_in_time() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    with pytest.raises(IllegalBidRunTransitionError, match="before the run's last update"):
        apply_transition(
            run,
            to=BidRunState.UPLOADED,
            occurred_at=NOW - timedelta(seconds=1),
            authorization=authorization(),
        )


def test_allowed_transitions_are_exactly_the_current_slice_scope() -> None:
    # A regression guard: widening the allowlist must be a deliberate,
    # reviewed change to this test, never a silent side effect.
    assert ALLOWED_TRANSITIONS == frozenset(
        {
            (BidRunState.CREATED, BidRunState.UPLOADED),
            (BidRunState.UPLOADED, BidRunState.QUARANTINED),
        }
    )


def test_bidrun_state_names_match_the_documented_target_lifecycle() -> None:
    assert {state.value for state in BidRunState} == {
        "CREATED",
        "UPLOADED",
        "QUARANTINED",
        "SECURITY_REVIEW",
        "CLEARED",
        "BLOCKED",
        "PROCESSING",
        "REVIEW_REQUIRED",
        "COMPLETED",
        "FAILED",
    }


# --- BidRun structural invariants (construct directly, bypassing apply_transition) --


def _quarantined_run(**overrides: object) -> BidRun:
    manifest = artifact_reference()
    transition_upload = BidRunTransition(
        from_state=BidRunState.CREATED,
        to_state=BidRunState.UPLOADED,
        reason_code=BidRunReasonCode.FILES_UPLOADED,
        occurred_at=NOW,
    )
    transition_quarantine = BidRunTransition(
        from_state=BidRunState.UPLOADED,
        to_state=BidRunState.QUARANTINED,
        reason_code=BidRunReasonCode.PACKAGE_QUARANTINED,
        occurred_at=NOW,
    )
    fields: dict[str, object] = {
        "bid_id": BID_ID,
        "run_id": RUN_ID,
        "workflow_name": WORKFLOW_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "authorization": authorization(),
        "source_package_artifact": manifest,
        "current_state": BidRunState.QUARANTINED,
        "state_history": (transition_upload, transition_quarantine),
        "artifact_refs": (manifest,),
        "created_at": NOW,
        "updated_at": NOW,
        "terminal_reason": None,
        "operator_message": "Uploaded and quarantined.",
    }
    fields.update(overrides)
    return BidRun(**fields)  # type: ignore[arg-type]


def test_bidrun_without_history_must_be_created() -> None:
    with pytest.raises(ValidationError, match="must still be CREATED"):
        BidRun(
            bid_id=BID_ID,
            run_id=RUN_ID,
            workflow_name=WORKFLOW_NAME,
            workflow_version=WORKFLOW_VERSION,
            authorization=unaccepted_authorization(),
            source_package_artifact=None,
            current_state=BidRunState.UPLOADED,
            state_history=(),
            artifact_refs=(),
            created_at=NOW,
            updated_at=NOW,
            terminal_reason=None,
            operator_message="stale",
        )


def test_bidrun_rejects_a_history_gap() -> None:
    valid_start = BidRunTransition(
        from_state=BidRunState.CREATED,
        to_state=BidRunState.UPLOADED,
        reason_code=BidRunReasonCode.FILES_UPLOADED,
        occurred_at=NOW,
    )
    gap = BidRunTransition(
        from_state=BidRunState.QUARANTINED,  # should be UPLOADED to be contiguous
        to_state=BidRunState.SECURITY_REVIEW,
        reason_code=BidRunReasonCode.PACKAGE_QUARANTINED,
        occurred_at=NOW,
    )
    with pytest.raises(ValidationError, match="not a contiguous chain"):
        _quarantined_run(
            state_history=(valid_start, gap),
            current_state=BidRunState.SECURITY_REVIEW,
        )


def test_bidrun_rejects_history_ending_at_a_different_state() -> None:
    with pytest.raises(ValidationError, match="must end at current_state"):
        _quarantined_run(current_state=BidRunState.UPLOADED)


def test_bidrun_rejects_duplicate_artifact_ids_even_with_matching_hash() -> None:
    manifest = artifact_reference()
    with pytest.raises(ValidationError, match="duplicate artifact IDs"):
        _quarantined_run(artifact_refs=(manifest, manifest))


def test_bidrun_rejects_same_artifact_id_with_a_different_hash() -> None:
    manifest = artifact_reference(content_hash=HASH_A)
    tampered = artifact_reference(content_hash=HASH_B)
    with pytest.raises(ValidationError, match="duplicate artifact IDs"):
        _quarantined_run(artifact_refs=(manifest, tampered))


def test_bidrun_rejects_artifact_refs_from_another_bid_or_run() -> None:
    foreign = artifact_reference(artifact_id=FILE_ARTIFACT_ID, bid_id=OTHER_BID_ID)
    with pytest.raises(ValidationError, match="same bid_id and run_id"):
        _quarantined_run(artifact_refs=(artifact_reference(), foreign))

    foreign_run = artifact_reference(artifact_id=FILE_ARTIFACT_ID, run_id=OTHER_RUN_ID)
    with pytest.raises(ValidationError, match="same bid_id and run_id"):
        _quarantined_run(artifact_refs=(artifact_reference(), foreign_run))


def test_bidrun_requires_source_package_from_quarantined_onward() -> None:
    with pytest.raises(ValidationError, match="requires a source_package_artifact"):
        _quarantined_run(source_package_artifact=None)


def test_bidrun_source_package_must_be_listed_in_artifact_refs() -> None:
    manifest = artifact_reference()
    other = artifact_reference(artifact_id=FILE_ARTIFACT_ID)
    with pytest.raises(ValidationError, match="must also be listed in artifact_refs"):
        _quarantined_run(source_package_artifact=other, artifact_refs=(manifest,))


def test_bidrun_pre_package_states_allow_no_source_package() -> None:
    run = create_bid_run(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=unaccepted_authorization(),
        created_at=NOW,
    )
    assert run.source_package_artifact is None


def test_bidrun_terminal_state_requires_a_terminal_reason() -> None:
    with pytest.raises(ValidationError, match="requires a terminal_reason"):
        _quarantined_run(
            current_state=BidRunState.FAILED,
            state_history=(
                BidRunTransition(
                    from_state=BidRunState.CREATED,
                    to_state=BidRunState.UPLOADED,
                    reason_code=BidRunReasonCode.FILES_UPLOADED,
                    occurred_at=NOW,
                ),
                BidRunTransition(
                    from_state=BidRunState.UPLOADED,
                    to_state=BidRunState.FAILED,
                    reason_code=BidRunReasonCode.PACKAGE_QUARANTINED,
                    occurred_at=NOW,
                ),
            ),
        )


def test_bidrun_non_terminal_state_rejects_a_terminal_reason() -> None:
    with pytest.raises(ValidationError, match="only valid in a terminal state"):
        _quarantined_run(terminal_reason="blocked by policy")


def test_bidrun_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _quarantined_run(not_a_real_field="nope")


def test_bidrun_fields_are_frozen() -> None:
    run = _quarantined_run()
    with pytest.raises(ValidationError, match="frozen"):
        run.current_state = BidRunState.SECURITY_REVIEW
