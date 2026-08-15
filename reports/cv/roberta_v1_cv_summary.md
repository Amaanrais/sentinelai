# Cross-validation summary — roberta_v1

k = 5 folds

## Headline metrics (mean ± std, 95% CI)

| metric | mean | std | 95% CI |
|---|---:|---:|---|
| accuracy | 0.985 | 0.003 | [0.981, 0.989] |
| precision | 0.988 | 0.005 | [0.983, 0.994] |
| recall | 0.981 | 0.009 | [0.969, 0.993] |
| f1 | 0.985 | 0.003 | [0.980, 0.989] |
| roc_auc | 0.998 | 0.001 | [0.997, 1.000] |
| pr_auc | 0.998 | 0.001 | [0.997, 1.000] |

## Per-fold headline metrics

| fold | accuracy | precision | recall | f1 | roc_auc | pr_auc |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.987 | 0.994 | 0.979 | 0.987 | 0.998 | 0.998 |
| 1 | 0.985 | 0.988 | 0.982 | 0.985 | 1.000 | 1.000 |
| 2 | 0.979 | 0.991 | 0.968 | 0.979 | 0.997 | 0.997 |
| 3 | 0.988 | 0.983 | 0.994 | 0.988 | 0.999 | 0.999 |
| 4 | 0.984 | 0.985 | 0.982 | 0.984 | 0.998 | 0.998 |

## Per attack type (mean recall across folds with support)

| attack_type | folds w/ support | total support | mean recall (pos) | mean specificity (neg) |
|---|---:|---:|---:|---:|
| none | 5 | 1700 | — | 0.988 |
| persona_jailbreak | 5 | 175 | 1.000 | — |
| fictional_framing | 5 | 149 | 1.000 | — |
| authority_claim | 5 | 148 | 0.993 | — |
| indirect_rag_injection | 5 | 142 | 1.000 | — |
| goal_hijacking | 5 | 135 | 1.000 | — |
| direct_harmful_request | 5 | 132 | 0.992 | — |
| jailbreak_explicit | 5 | 122 | 0.975 | — |
| payload_splitting | 5 | 116 | 1.000 | — |
| obfuscated_payload | 5 | 110 | 1.000 | — |
| completion_hijack | 5 | 108 | 0.990 | — |
| camouflaged_harmful | 5 | 107 | 0.944 | — |
| hypothetical_framing | 5 | 107 | 0.990 | — |
| prompt_injection | 5 | 79 | 0.775 | — |
| injection | 5 | 70 | 0.986 | — |

## Per surface_benignity tier (mean recall across folds with support)

| tier | folds w/ support | total support | mean detection rate | mean specificity |
|---|---:|---:|---:|---:|
| 0 | 5 | 352 | 0.977 | — |
| 1 | 5 | 492 | 0.992 | — |
| 2 | 5 | 758 | 0.962 | 0.955 |
| 3 | 5 | 1798 | 1.000 | 0.993 |