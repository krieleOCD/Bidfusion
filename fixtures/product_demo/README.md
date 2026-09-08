# Product Demonstration Data

Curated demonstration data for the BidFusion product preview surfaces
(customer intelligence, qualification, compliance, capability fit,
competitive intelligence, win strategy, proposal factory, review and
approval).

These files exist so the intended information model can be argued with
before the systems behind it are built. They are **not** results, and no
page may present them as such — every surface that renders them declares
`CURATED DEMO` or `STATIC PREVIEW` in its status strip.

## Policy

The repository-wide fixture policy applies unchanged
([../README.md](../README.md)): **no real customer, competitor, or
personal data, ever.** For this directory specifically:

1. **Organizations are invented.** Customers and competitors carry names
   that belong to no real company. If a name here ever matches a real
   organization, that is a defect — replace it.
2. **No people.** Stakeholders are described by role only. No names, no
   contact details, no quotes attributed to an individual.
3. **No real figures.** Contract values, scores, and volumes are bands
   and invented numbers, never anything taken from an actual bid.
4. **No pasted content.** Nothing here may be copied out of a real RFP,
   a real proposal, an email, a CRM record, or a meeting.

Replacing this data with real internal content — real accounts, real
competitor intelligence, real bid history — is **not** a matter of
editing these files. That data does not belong in this repository at
all; it needs a governed store outside it and the decision recorded in
the `L1B` phase entry of the feature registry.

## Structure

| Path | Contents |
| ---- | -------- |
| `response_lifecycle.json` | The intended response lifecycle. Product structure, identical for every scenario, so it is held once. |
| `scenarios/<key>/scenario.json` | One complete opportunity: context, sources, compliance, capability fit, qualification, competitors, strategy, review. |

Every file declares a `schema_version` and is validated against
`src/bidfusion/local_ui/preview_schemas.py` before it reaches a
template. A file that does not satisfy the schema is not rendered
partially — the page reports that no preview data is available.

## Scenarios

| Key | What it demonstrates |
| --- | -------------------- |
| `clean-opportunity` | Good coverage, few risks, a go with conditions attached. |
| `high-risk-opportunity` | An exclusion-criterion risk, missing sizing, and a legal concern. Tends towards no-go. |
| `competitive-opportunity` | A crowded field: competitor context, relationship signals, and where the difference actually lies. |

## Changing them

1. Edit the JSON. Do not add logic to a template or a route for one
   scenario — if a page needs a new kind of fact, the schema gets a new
   field and every scenario gets a value for it.
2. Run `pytest tests/local_ui/test_preview_data.py`. It validates every
   file, checks the invented-name and no-person rules, and fails on any
   text that would read as a live connection.
