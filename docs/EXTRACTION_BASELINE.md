# Extraction Baseline — Phase 0.5 Results

Model: `gemma4:e2b`
Docs processed: 6

## JSON Validity: 100% (6/6)

## Aggregate Scores

| Type | Precision | Recall | Truth | Extracted | Matched |
|------|----------:|-------:|------:|----------:|--------:|
| persons | 1.00 | 0.78 | 9 | 7 | 7 |
| teams | 0.00 | 0.00 | 0 | 0 | 0 |
| projects | 0.00 | 0.00 | 2 | 0 | 0 |
| rules | 0.00 | 0.00 | 0 | 2 | 0 |
| events | 0.00 | 0.00 | 1 | 3 | 0 |

## Decision Gates

- JSON validity ≥ 80%: **PASS** (100%)
- Person+Team precision ≥ 70%: persons=100% teams=0%
- Person+Team recall ≥ 60%: persons=78% teams=0%

## Per-Document Results

### `Handbook (1).docx`
- JSON valid: True
- Latency: 11.4s
  - persons: P=1.00 R=1.00 (truth=1, extracted=1)

### `BE QARTMINA.pdf`
- JSON valid: True
- Latency: 16.8s
  - persons: P=1.00 R=1.00 (truth=2, extracted=2)

### `Procuration_sonia-hassas.pdf`
- JSON valid: True
- Latency: 22.9s
  - persons: P=1.00 R=1.00 (truth=2, extracted=2)
  - events: P=0.00 R=0.00 (truth=1, extracted=1)

### `additionality.pdf`
- JSON valid: True
- Latency: 16.1s
  - persons: P=0.00 R=0.00 (truth=1, extracted=0)
  - projects: P=0.00 R=0.00 (truth=1, extracted=0)

### `MITRA (1).xlsx`
- JSON valid: True
- Latency: 18.9s
  - persons: P=1.00 R=1.00 (truth=2, extracted=2)
  - projects: P=0.00 R=0.00 (truth=1, extracted=0)

### `RNE QARTMINA MARS 2026.pdf`
- JSON valid: True
- Latency: 24.5s
  - persons: P=0.00 R=0.00 (truth=1, extracted=0)
  - rules: P=0.00 R=0.00 (truth=0, extracted=2)
  - events: P=0.00 R=0.00 (truth=0, extracted=2)
