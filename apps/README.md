# apps

Deployable application entry points (CLI, API, workers) will live here.

The repository currently contains the **target architecture and
engineering foundation only** — there is deliberately nothing to run yet.
BidFusion starts as a modular monolith: domain packages live in
`src/bidfusion/`, and `apps/` stays thin (wiring and entry points only).
Splitting into separately deployed services is a later, conscious decision
that requires a real need (see `docs/adr/`).
