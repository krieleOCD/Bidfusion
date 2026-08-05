# Level 1 Target Architecture — Authorized Upload and Human Review

This is a binding, narrow architecture contract for the path from "an
authorized internal user uploads an unknown RFP through the local UI" to
"a versioned Reviewed Working Package exists." It extends, and does not
replace, [engineering-architecture.md](./engineering-architecture.md),
[state-machine.md](./state-machine.md), and
[trust-boundaries.md](./trust-boundaries.md). Where this document and
those disagree, the existing documents win for anything below the
Security Gate; this document owns everything **above** and **around**
it — intake identity, upload trust, and the BidRun lifecycle that wraps
one bid attempt end to end.

## 1. Goal definition (Level 1)

An explicitly authorized internal user can, through the local UI:

1. upload an unknown PDF/XLSX/TXT RFP package,
2. have it pass through a clearly labeled, non-production security and
   processing lane,
3. review and correct requirements, deadlines, and formalities with
   sources, and
4. produce a versioned **Reviewed Working Package**.

Level 1 is reached incrementally across several slices (§13). This
document describes the target for all of them; each slice implements a
strict subset and says so explicitly.

## 2. Non-goals

- No production customer data. No production release gate. No malware
  signature scanning, no sandboxed/no-network parser container, no
  CPU/RAM/timeout enforcement, no SLA.
- No general workflow/graph runtime, no LangGraph, no Temporal, no
  microservices, no event bus, no graph database, no multi-agent
  architecture. "Graph engineering" here means a typed run state, an
  explicit transition allowlist, and a versioned workflow definition —
  nothing more, for now.
- No authentication/authorization system. The local UI has exactly one
  non-authenticated local identity (§10).
- No fachlicher Knowledge Graph. Data models get stable IDs and
  relationships so a later slice can build one without a schema break.
- No automatic security clearance of uploaded files. Validation at
  upload time is acceptance policy, not a security verdict.

## 3. Trust and security boundaries

Three trust zones, in order of increasing trust:

```text
BROWSER UPLOAD (fully untrusted)
   → UPLOAD VALIDATION (acceptance policy, not clearance)
      → QUARANTINE (untrusted bytes, contained, not parsed)
         → [later slice] SECURITY GATE (existing preflight + policy)
            → [existing] PROCESSING ZONE (Document Understanding → … → Working Package)
```

- **Browser upload**: the request body is attacker-controlled. Filenames,
  declared MIME types, and declared sizes are never trusted.
- **Upload validation**: server-side, bounded, fail-closed checks
  (extension allowlist, magic-byte/content-type cross-check, size caps,
  path/filename hardening). This is the same trust level as intake's
  existing bounded reader (`bidfusion.intake.register`) — it establishes
  *identity and admissibility*, not *safety*.
- **Quarantine**: validated bytes are persisted, hashed, and made
  inspectable, but are never opened by a parser, never handed to
  `run_package()`, and never marked cleared. This is a new trust zone
  between "browser upload" and the existing "Security Gate" boundary in
  [trust-boundaries.md](./trust-boundaries.md).
- **Security Gate and Processing Zone**: unchanged from the existing
  contract. A future slice is the only thing allowed to move bytes from
  Quarantine into this zone, and only through the existing
  `DeterministicPreflightScanner` / package-gate policy path — never
  around it.

Nothing in this slice or its immediate successors weakens
[trust-boundaries.md](./trust-boundaries.md); it adds one new zone in
front of it.

## 4. Product stages

| Stage | Description | Data |
| ----- | ----------- | ---- |
| **Level 0.4** | Current: local UI drives only the repository's own `fixtures/synthetic/` packages through the existing pipeline. | Synthetic only |
| **Level 1A** | This contract's target: authorized internal users upload their own test RFPs (real structure, no real customer content) through the same non-production lane. | Authorized internal test data only |
| **Level 1B** | Production customer data. Requires a production Security Gate, operational controls, retention/deletion policy, and a separate go decision. Explicitly out of scope until then. | Real customer data — not yet permitted |

Every UI surface touching free upload must visibly say which stage it
is. Level 1A is not, and must never silently become, Level 1B.

## 5. BidRun model

`BidRun` is a new, additive contract. It does not replace `Bid`
(business lifecycle) or `ProcessingRun` (technical pipeline-run
progress, [state-machine.md](./state-machine.md)); it wraps the part of
a bid's life neither of those covers today: the journey of an unknown
uploaded package from "received" to "the point where a `ProcessingRun`
can legitimately begin." A `ProcessingRun` still only ever exists for
data a `BidRun` has carried into a security-cleared state.

Fields (minimum, per the governing instructions):

| Field | Type | Notes |
| ----- | ---- | ----- |
| `bid_id` | `BidId` | Same format/allocator family as the rest of the system. |
| `run_id` | `RunId` | Allocated the same way as `run_id_for()`; identifies this BidRun attempt. |
| `workflow_name` | `str` | e.g. `"bidfusion-level1-bidrun"`. |
| `workflow_version` | `SemanticVersion` | Versions the *set of allowed transitions*, not the code. |
| `authorization` | `AuthorizationRecord` | Structured consent (§6). |
| `source_package_artifact` | `ArtifactReference \| None` | Set once the Upload Manifest exists (at `QUARANTINED`). |
| `current_state` | `BidRunState` | See §6. |
| `state_history` | `tuple[BidRunTransition, ...]` | Append-only, ordered, validated as a chain. |
| `artifact_refs` | `tuple[ArtifactReference, ...]` | Every artifact this BidRun owns (raw quarantined files + manifest). |
| `created_at` / `updated_at` | `datetime` | `updated_at` moves only via a validated transition. |
| `terminal_reason` | `str \| None` | Only set in a terminal state; unused in this slice. |
| `operator_message` | `str` | Static, allowlisted, safe-to-display text for the current state — never a raw exception. |

Modeled the same way as every other Foundation contract: Pydantic,
`extra="forbid"`, frozen, `model_validator(mode="after")` invariants
(history chain matches `current_state`, `artifact_refs` carry the same
`bid_id`/`run_id`, no duplicate `artifact_id` with a different hash,
authorization must be `accepted` before leaving `CREATED`). "Apply a
transition" means constructing a new validated `BidRun`, matching the
frozen-model pattern used everywhere else in this codebase — there is no
in-place mutation.

## 6. States and transitions

All ten states are named now, matching the governing instructions
exactly:

```text
CREATED → UPLOADED → QUARANTINED → SECURITY_REVIEW → CLEARED → PROCESSING
                                        ↓                ↓          ↓
                                     BLOCKED      REVIEW_REQUIRED  COMPLETED
                                                                    ↓
                                                                  FAILED
```

This slice implements **only**:

```text
CREATED → UPLOADED → QUARANTINED
```

as an explicit allowlist of `(from, to)` pairs — nothing else is
reachable, and nothing else is simulated by a placeholder function.
Every other edge above is descriptive target shape for later slices, not
executable code yet.

Transition rules (enforced structurally, not just by convention):

- Every transition is looked up in a single allowlist; anything else
  raises before any state changes.
- Every transition is timestamped and appended to `state_history`;
  history is never rewritten.
- Every transition carries a stable `reason_code` (a `StrEnum`) — no
  free-text reasons.
- `CREATED → UPLOADED` requires `authorization.accepted is True`.
  Structurally: a `BidRun` cannot validate in any state past `CREATED`
  with `authorization.accepted is False`.
- No UI parameter selects the target state directly. The UI calls one
  named operation ("submit authorized upload"); the operation decides
  the transition, not the request body.
- The upload path can only ever reach `QUARANTINED`. It can never
  produce `CLEARED`, `PROCESSING`, or `COMPLETED` — there is no code
  path in this slice that could, because those edges are not in the
  allowlist.

## 7. Ports and adapters

Target ports for the full Level 1 shape (ADR-0011 style — structural
protocols, domain code depends on the port, not a provider):

- `IntakePort` — turn a validated input (today: a package directory;
  later: also a cleared upload) into registered documents.
- `SecurityScannerPort` — today's `DeterministicPreflightScanner`,
  already implemented, not yet expressed as a formal port.
- `ParserRuntimePort` — today's `parser_for()` registry.
- `ExtractionPort` — today's rule-based extractors.
- `ReviewRepositoryPort` — persistence for human review decisions
  (§10). Not implemented until a review slice exists.
- `EvaluationPort` — eval hooks (§11). Not implemented until an eval
  slice exists.
- `ArtifactStorePort` — today's `secure_io` file-based writer, already
  implemented, not yet expressed as a formal port.

This slice implements **none** of these as new abstractions. Upload
validation and quarantine persistence are a concrete, in-process
service — they sit *before* `IntakePort` in the pipeline and are
deliberately not generalized into a port until a second, real
implementation (e.g., a non-local intake path) would actually need one.
Turning quarantine intake into part of `IntakePort` — or a distinct
`UploadPort` — is an explicit open question for the slice that
implements `SECURITY_REVIEW`/`CLEARED`, not this one.

## 8. Artifact chain

```text
Raw browser upload bytes (untrusted, in-memory/stream only)
   → validated per-file bytes (bounded read, extension+magic-byte check)
      → ArtifactReference per file (artifact_type=RAW_DOCUMENT, content_ref="files/<artifact_id>.<ext>")
         → UploadManifest (new sealed artifact, artifact_type=UPLOAD_MANIFEST)
            → source_package_artifact on BidRun
```

- `ArtifactType` gains one new member: `UPLOAD_MANIFEST`. Individual
  quarantined files reuse the existing `RAW_DOCUMENT` type — they are,
  factually, raw untouched documents; only their `content_ref` and the
  BidRun state around them mark them as pre-clearance.
- The manifest is sealed with the existing
  `bidfusion.shared.payloads.seal_artifact` / `HASH_CONVENTION`
  machinery — the same two-pass envelope-hash construction every other
  domain artifact uses. No new hash convention is invented.
- `content_hash` on every `ArtifactReference` is the SHA-256 of the
  exact bytes written to disk, computed the same bounded, TOCTOU-safe
  way `bidfusion.intake.register._read_bounded` already does — that
  reader is reused, not reimplemented.
- Whole-package integrity reuses
  `bidfusion.orchestration.verify_run_integrity` and its
  `integrity-manifest.json` convention unchanged; that function already
  only assumes "some directory with a digest manifest," so the
  quarantine package directory can be verified with it directly.
- `BidRun.artifact_refs` is the superset (manifest + every raw file);
  `BidRun.source_package_artifact` is specifically the manifest
  reference, so downstream code has one stable pointer to "the package"
  without re-deriving it from the list.

## 9. Upload and quarantine model

```text
Browser POST (multipart, multiple files + authorization checkbox)
   → server-side validation, per file, bounded (never loads an unbounded body)
   → BidRun created (CREATED)
   → BidRun → UPLOADED (authorization recorded and required)
   → new quarantine package directory (0700), outside any repository checkout
   → files written with random-looking internal names (artifact IDs), 0600, atomic
   → per-file SHA-256 computed from the bytes actually written
   → UploadManifest sealed and written
   → BidRun → QUARANTINED
   → UI shows quarantine status only
```

Hard constraints (fail closed):

- Accepted extensions: `pdf`, `xlsx`, `txt` — nothing else, this slice.
- Every numeric limit (files per package, bytes per file, bytes per
  package) lives in one versioned policy object, never as scattered
  literals.
- The original browser filename is **never** used as a path component.
  A normalized, length-bounded *display name* is stored as manifest
  metadata only.
- Symlinks, non-regular files, path traversal, absolute paths, and
  Windows separators are rejected before any write.
- The quarantine root and every package directory are `lstat`-checked,
  never followed if a symlink, and containment-checked against the
  resolved root after every join — the same discipline
  `bidfusion.shared.secure_io` and
  `bidfusion.shared.pathguards.is_inside_repository_checkout` already
  apply elsewhere, extended with a quarantine-specific root check.
- Nothing under quarantine is ever passed to `run_package()`, a parser,
  or an extractor in this slice. There is no code path that could do
  so — the quarantine service has no dependency on
  `bidfusion.orchestration`, `bidfusion.document_understanding`, or
  `bidfusion.extraction` at all.

## 10. Human review model (later slices)

Not implemented in this slice. Target shape: a `ReviewRepositoryPort`
persists reviewer decisions (accept/correct/reject) against extracted
requirements, deadlines, and formalities, each decision keeping the
original extraction plus the human correction and its source — never
silently overwriting extraction output. The local, non-authenticated
identity introduced in §6/§10 authorization (`local-operator`) is
reused as the default reviewer identity until real authentication
exists; this is documented, not hidden.

## 11. Eval hooks (later slices)

Not implemented in this slice. Target shape: an `EvaluationPort` that
can score a completed run's extraction/requirements against a labeled
fixture, reusing the existing `evals/` scaffolding and golden-dataset
separation (ADR-0009). BidRun's `workflow_version` and `state_history`
are designed to already carry what an eval harness will need
(exact allowlisted policy version, exact transition timestamps)
without a schema change later.

## 12. Relationship to Workflow Graph and Knowledge Graph

- **Workflow graph, now**: `BidRunState` + the transition allowlist +
  `workflow_name`/`workflow_version` on `BidRun`. That is the entire
  "graph engineering" surface of this slice — a typed state, explicit
  edges, and a version number. No runtime graph engine.
- **Workflow graph, later**: more states/edges get implemented
  (`SECURITY_REVIEW` onward) the same way — allowlist first, no
  simulated transitions.
- **Knowledge graph**: not implemented. `BidRun`, `ArtifactReference`,
  and the manifest already carry stable IDs and explicit references
  (`bid_id`, `run_id`, `artifact_id`, lineage via `input_artifacts`), so
  a later fachlicher Knowledge Graph can be built over existing IDs
  instead of inventing new ones retroactively.

## 13. Planned Level 1 slices

1. **This slice** — architecture contract, `BidRun` contracts and
   transition allowlist, upload validation policy, quarantine service,
   UI upload surface. Terminates at `QUARANTINED`.
2. **Security Review slice** — `QUARANTINED → SECURITY_REVIEW`, wiring
   the existing `DeterministicPreflightScanner` and package-gate policy
   onto quarantined packages; introduces `SecurityScannerPort`
   formally.
3. **Cleared-to-Processing slice** — `SECURITY_REVIEW → CLEARED →
   PROCESSING`, the first point where quarantine hands validated,
   cleared bytes to the existing `run_package()` path.
4. **Human Review slice** — `ReviewRepositoryPort`, reviewer UI over
   requirements/deadlines/formalities with sources, `REVIEW_REQUIRED`
   handling.
5. **Reviewed Working Package slice** — versioned output that combines
   extraction with recorded human review decisions; `COMPLETED`/
   `FAILED` become reachable.
6. **Eval slice** — `EvaluationPort` wired to the golden dataset.

## 14. Explicit production boundaries

Even after every slice above lands, none of the following exist unless
a separate, explicit decision adds them:

- Production Security Gate policy, malware signatures, sandboxed/
  no-network parser execution, or resource limits.
- Multi-user authentication, authorization, or audit identity beyond
  the documented local, non-authenticated `local-operator` identity.
- Retention, deletion, or backup policy for quarantined or processed
  data.
- Any network, API, LLM, OCR, SharePoint, or external provider call
  from the upload/quarantine path.
- Any relaxation of the `fixtures/synthetic/`-only full-processing lock
  in `bidfusion.orchestration.local_pipeline` — Level 1A authorized
  uploads still require the same
  `--authorized-non-production-test`-equivalent explicit confirmation
  this contract defines in `AuthorizationRecord`, and Level 1B
  (production customer data) remains categorically out of scope.

Until Phase 2/3 in [component-migration.md](../development/component-migration.md)
formally supersede it, this document is the target for the upload/
quarantine surface specifically; the rest of the existing architecture
documents remain authoritative unchanged.
