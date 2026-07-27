# Evaluation Metrics (catalog)

Perspectivistic metrics for BidFusion LLM components. Definitions get
pinned down when the first eval runner is implemented.

| Metric | What it measures |
| ------ | ---------------- |
| Requirement Recall | Share of real requirements found by extraction |
| Requirement Precision | Share of extracted items that are real requirements |
| Classification Accuracy | Correctness of requirement types/categories |
| Deadline Accuracy | Correctness of extracted dates and deadline kinds |
| Metadata Accuracy | Correctness of extracted document/bid metadata |
| Citation Accuracy | Share of claims with correct source references |
| Table Extraction Accuracy | Structural correctness of extracted tables |
| Cross Reference Accuracy | Correctness of resolved cross references |
| Hallucination Rate | Share of produced claims without evidence |
| Capability Matching Accuracy | Correctness of match status vs. human judgement |
