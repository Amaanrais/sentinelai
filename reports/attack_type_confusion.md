# Per-attack-type detection — cross-model comparison

## Table A — In-distribution (dataset_v1_test, n=600)

Prompts drawn from the decoupled attack_type x surface_benignity grid plus capped real-world sources used for training.
Cell format: `detected / total (recall%)`

| Attack type | n | DistilBERT | RoBERTa | TF-IDF+LR |
|---|---:|---:|---:|---:|
| injection | 13 | 12/13 (92.3%) | 12/13 (92.3%) | 11/13 (84.6%) |
| jailbreak_explicit | 21 | 21/21 (100.0%) | 21/21 (100.0%) | 21/21 (100.0%) |
| prompt_injection | 14 | 8/14 (57.1%) | 8/14 (57.1%) | 7/14 (50.0%) |
| persona_jailbreak | 31 | 31/31 (100.0%) | 31/31 (100.0%) | 31/31 (100.0%) |
| indirect_rag_injection | 25 | 25/25 (100.0%) | 25/25 (100.0%) | 24/25 (96.0%) |
| goal_hijacking | 24 | 23/24 (95.8%) | 23/24 (95.8%) | 23/24 (95.8%) |
| authority_claim | 26 | 26/26 (100.0%) | 26/26 (100.0%) | 25/26 (96.2%) |
| direct_harmful_request | 23 | 23/23 (100.0%) | 23/23 (100.0%) | 22/23 (95.7%) |
| obfuscated_payload | 20 | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| completion_hijack | 19 | 19/19 (100.0%) | 18/19 (94.7%) | 17/19 (89.5%) |
| fictional_framing | 26 | 26/26 (100.0%) | 26/26 (100.0%) | 26/26 (100.0%) |
| payload_splitting | 20 | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| hypothetical_framing | 19 | 19/19 (100.0%) | 19/19 (100.0%) | 18/19 (94.7%) |
| camouflaged_harmful | 19 | 13/19 (68.4%) | 18/19 (94.7%) | 13/19 (68.4%) |
| **none (benign)** | 300 | 1 FP / 300 (99.7% spec) | 1 FP / 300 (99.7% spec) | 5 FP / 300 (98.3% spec) |

## Table B — Out-of-distribution (probe_data_v2, n=440)

Novel GPT-generated prompts, none seen during training.
All samples are malicious (no benign baseline for this table).
Cell format: `detected / total (recall%)`

| Attack type | n | DistilBERT | RoBERTa | TF-IDF+LR |
|---|---:|---:|---:|---:|
| persona_jailbreak | 40 | 40/40 (100.0%) | 40/40 (100.0%) | 40/40 (100.0%) |
| indirect_rag_injection | 40 | 40/40 (100.0%) | 40/40 (100.0%) | 40/40 (100.0%) |
| goal_hijacking | 40 | 40/40 (100.0%) | 40/40 (100.0%) | 40/40 (100.0%) |
| authority_claim | 40 | 40/40 (100.0%) | 38/40 (95.0%) | 40/40 (100.0%) |
| direct_harmful_request | 40 | 39/40 (97.5%) | 39/40 (97.5%) | 38/40 (95.0%) |
| obfuscated_payload | 40 | 38/40 (95.0%) | 40/40 (100.0%) | 28/40 (70.0%) |
| completion_hijack | 40 | 40/40 (100.0%) | 39/40 (97.5%) | 38/40 (95.0%) |
| fictional_framing | 40 | 40/40 (100.0%) | 37/40 (92.5%) | 37/40 (92.5%) |
| payload_splitting | 40 | 40/40 (100.0%) | 39/40 (97.5%) | 36/40 (90.0%) |
| hypothetical_framing | 40 | 39/40 (97.5%) | 39/40 (97.5%) | 39/40 (97.5%) |
| camouflaged_harmful | 40 | 32/40 (80.0%) | 36/40 (90.0%) | 28/40 (70.0%) |