# Cross-model detection rate by surface_benignity tier

Detection rate = recall on malicious prompts within each tier.

| tier | disguise level | n | distilbert_v1 | roberta_v1 | baseline_tfidf |
|------|----------------|---|---|---|---|
| 0 | Obvious | 110 | 0.609 | 0.518 | 0.373 |
| 1 | Mild | 110 | 0.636 | 0.518 | 0.355 |
| 2 | Moderate | 110 | 0.682 | 0.309 | 0.455 |
| 3 | High | 110 | 0.636 | 0.182 | 0.400 |