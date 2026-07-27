# Local Deployment

The only supported runtime right now is a local developer machine:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See [docs/development/local-setup.md](../../docs/development/local-setup.md).
No containers, no orchestrators, no services — deliberately.
