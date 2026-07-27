# JSON Schemas (generated)

Modules in BidFusion exchange typed contracts, not ad-hoc JSON
(schema first, ADR-0005). The **single source of truth** for all domain
contracts is the Pydantic package:

```
src/bidfusion/schemas/
```

JSON Schemas for non-Python consumers are **derived artifacts**, generated
on demand:

```bash
python scripts/export_schemas.py          # writes <Model>.json into this directory
```

Generated files are intentionally not committed to git. Never edit a
generated schema by hand — change the Pydantic model and re-export.
