# ADR-0010: APMP-aligned Bid Management Domain

**Status:** ACCEPTED

## Context

The original Foundation modeled RFP processing more strongly than
professional bid management. Delaying all commercial-domain boundaries
would make Opportunity, qualification, compliance management, ownership,
business approvals, and governed knowledge expensive to add after component
migration.

APMP is used as a vendor-neutral domain reference. BidFusion does not claim
to implement APMP, reproduce its Body of Knowledge, or make its software
architecture dependent on APMP. The research reference informs terminology
and redesign-critical boundaries only.

## Decision

Foundation 1.1 introduces only minimal contracts needed now:

- `Opportunity` and an explicit `OpportunityId` relationship on `Bid`;
- `BidDecision` for pending, GO, NO-GO, and conditional qualification;
- separate requirement modality and business category;
- first-class `ComplianceMatrix` and `ComplianceItem`;
- reusable `Actor` and `Assignment`;
- `BusinessReview`, `ReviewFinding`, and `Approval`, distinct from
  AI/extraction `HumanReview`;
- governed enterprise knowledge with owner, approval, version, validity,
  review cycle, classification, source, and evidence; and
- `ProcessingRun` separated from the minimal `BidBusinessState`.

The contracts reserve boundaries; they do not implement scoring, CRM,
Pink/Red/Gold workflows, proposal generation, submission automation,
handover, win/loss, or lessons-learned automation.

## Consequences

- Component migration has explicit targets for compliance, ownership,
  review, qualification, and knowledge instead of overloading technical
  processing models.
- Compliance status remains distinct from capability-match status.
- AI correction remains distinct from accountable business approval.
- APMP terminology can evolve without coupling the modular-monolith
  architecture to a methodology vendor.
- Workflow behavior and organizational policy remain open decisions.
