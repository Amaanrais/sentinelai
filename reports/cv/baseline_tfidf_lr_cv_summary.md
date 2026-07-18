# Cross-validation summary — baseline_tfidf_lr

k = 5 folds

## Headline metrics (mean ± std, 95% CI)

| metric | mean | std | 95% CI |
|---|---:|---:|---|
| accuracy | 0.956 | 0.004 | [0.952, 0.961] |
| precision | 0.968 | 0.007 | [0.959, 0.977] |
| recall | 0.944 | 0.013 | [0.928, 0.960] |
| f1 | 0.956 | 0.004 | [0.951, 0.961] |
| roc_auc | 0.990 | 0.003 | [0.987, 0.994] |
| pr_auc | 0.992 | 0.002 | [0.990, 0.994] |

## Per-fold headline metrics

| fold | accuracy | precision | recall | f1 | roc_auc | pr_auc |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.957 | 0.973 | 0.941 | 0.957 | 0.992 | 0.993 |
| 1 | 0.957 | 0.973 | 0.941 | 0.957 | 0.991 | 0.992 |
| 2 | 0.950 | 0.972 | 0.926 | 0.949 | 0.985 | 0.989 |
| 3 | 0.959 | 0.967 | 0.950 | 0.958 | 0.992 | 0.993 |
| 4 | 0.959 | 0.956 | 0.962 | 0.959 | 0.992 | 0.992 |

## Per attack type (mean recall across folds with support)

| attack_type | folds w/ support | total support | mean recall (pos) | mean specificity (neg) |
|---|---:|---:|---:|---:|
| none | 5 | 1700 | — | 0.969 |
| persona_jailbreak | 5 | 175 | 0.989 | — |
| fictional_framing | 5 | 149 | 0.993 | — |
| authority_claim | 5 | 148 | 1.000 | — |
| indirect_rag_injection | 5 | 142 | 0.986 | — |
| goal_hijacking | 5 | 135 | 0.985 | — |
| direct_harmful_request | 5 | 132 | 0.962 | — |
| jailbreak_explicit | 5 | 122 | 0.942 | — |
| payload_splitting | 5 | 116 | 1.000 | — |
| obfuscated_payload | 5 | 110 | 0.955 | — |
| completion_hijack | 5 | 108 | 0.925 | — |
| camouflaged_harmful | 5 | 107 | 0.806 | — |
| hypothetical_framing | 5 | 107 | 1.000 | — |
| prompt_injection | 5 | 79 | 0.471 | — |
| injection | 5 | 70 | 1.000 | — |

## Per surface_benignity tier (mean recall across folds with support)

| tier | folds w/ support | total support | mean detection rate | mean specificity |
|---|---:|---:|---:|---:|
| 0 | 5 | 352 | 0.898 | — |
| 1 | 5 | 492 | 0.967 | — |
| 2 | 5 | 758 | 0.919 | 0.930 |
| 3 | 5 | 1798 | 1.000 | 0.975 |