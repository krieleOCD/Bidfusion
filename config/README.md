# Configuration

Non-secret example configurations live here (e.g. `default.yaml`).

Rules:

- These files document the **shape** of the configuration; they are
  examples, not active runtime config.
- Secrets never belong in `config/`. They come from the environment
  (see `.env.example`) or a secret store.
- Anything environment-specific or machine-specific stays local.
