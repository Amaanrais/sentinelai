# Cross-validation summary — distilbert_v1

k = 5 folds

## Headline metrics (mean ± std, 95% CI)

| metric | mean | std | 95% CI |
|---|---:|---:|---|
| accuracy | 0.974 | 0.004 | [0.970, 0.979] |
| precision | 0.977 | 0.009 | [0.966, 0.988] |
| recall | 0.972 | 0.012 | [0.956, 0.987] |
| f1 | 0.974 | 0.004 | [0.970, 0.979] |
| roc_auc | 0.997 | 0.002 | [0.995, 0.998] |
| pr_auc | 0.997 | 0.001 | [0.995, 0.999] |

## Per-fold headline metrics

| fold | accuracy | precision | recall | f1 | roc_auc | pr_auc |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.976 | 0.974 | 0.979 | 0.977 | 0.997 | 0.997 |
| 1 | 0.976 | 0.985 | 0.968 | 0.976 | 0.997 | 0.997 |
| 2 | 0.971 | 0.988 | 0.953 | 0.970 | 0.995 | 0.996 |
| 3 | 0.978 | 0.971 | 0.985 | 0.978 | 0.999 | 0.999 |
| 4 | 0.971 | 0.968 | 0.974 | 0.971 | 0.995 | 0.995 |

## Per attack type (mean recall across folds with support)

| attack_type | folds w/ support | total support | mean recall (pos) | mean specificity (neg) |
|---|---:|---:|---:|---:|
| none | 5 | 1700 | — | 0.977 |
| persona_jailbreak | 5 | 175 | 1.000 | — |
| fictional_framing | 5 | 149 | 1.000 | — |
| authority_claim | 5 | 148 | 1.000 | — |
| indirect_rag_injection | 5 | 142 | 1.000 | — |
| goal_hijacking | 5 | 135 | 0.993 | — |
| direct_harmful_request | 5 | 132 | 0.970 | — |
| jailbreak_explicit | 5 | 122 | 0.950 | — |
| payload_splitting | 5 | 116 | 1.000 | — |
| obfuscated_payload | 5 | 110 | 0.991 | — |
| completion_hijack | 5 | 108 | 0.981 | — |
| camouflaged_harmful | 5 | 107 | 0.916 | — |
| hypothetical_framing | 5 | 107 | 1.000 | — |
| prompt_injection | 5 | 79 | 0.685 | — |
| injection | 5 | 70 | 1.000 | — |

## Per surface_benignity tier (mean recall across folds with support)

| tier | folds w/ support | total support | mean detection rate | mean specificity |
|---|---:|---:|---:|---:|
| 0 | 5 | 352 | 0.960 | — |
| 1 | 5 | 492 | 0.984 | — |
| 2 | 5 | 758 | 0.951 | 0.920 |
| 3 | 5 | 1798 | 1.000 | 0.986 |