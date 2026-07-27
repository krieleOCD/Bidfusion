# Scripts

Repository-local development and maintenance scripts.

| Script | Purpose |
| ------ | ------- |
| `check_markdown_links.py` | Verify that all relative Markdown links in the repo resolve. |
| `export_schemas.py` | Export Pydantic domain contracts as JSON Schema (derived artifacts). |

Run from the repository root, e.g.:

```bash
python scripts/check_markdown_links.py
python scripts/export_schemas.py
```
