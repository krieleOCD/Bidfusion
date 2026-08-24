"""ANONYMIZED REAL RFP PILOT — Orange Proxy requirement normalization.

Controlled pilot slice: one anonymized, security-cleared RFP
requirement at a time is normalized through the Orange LLM Proxy as a
*challenger* to the existing deterministic normalizer. The deterministic
path (:func:`bidfusion.bid_intelligence.matching.adapter.adapt_requirement`)
and the golden matcher remain authoritative and unchanged; this package
only adds a second, clearly labeled machine-normalization candidate and
the comparison/evaluation contracts around it.

Governance labels that apply to everything produced here:

- ``ANONYMIZED REAL RFP PILOT`` — operator-asserted anonymized input only
- ``ORANGE PROXY`` — the only permitted model egress
- ``MACHINE NORMALIZATION`` — model output is a candidate, never truth
- ``HUMAN EVALUATION REQUIRED`` — no result is approved automatically
- ``NOT A COMPLIANCE DECISION`` — the model never decides deliverability,
  compliance, golden-claim truth, or bid outcomes
"""
