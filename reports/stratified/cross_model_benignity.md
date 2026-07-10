# Cross-model detection rate by surface_benignity tier

Detection rate = recall on malicious prompts within each tier.

| tier | disguise level | n | distilbert_v1 | roberta_v1 | baseline_tfidf |
|------|----------------|---|---|---|---|
| 0 | Obvious | 110 | 0.891 | 0.927 | 0.773 |
| 1 | Mild | 110 | 1.000 | 0.982 | 0.927 |
| 2 | Moderate | 110 | 1.000 | 0.991 | 0.982 |
| 3 | High | 110 | 1.000 | 0.982 | 0.991 |