# Per-attack-type detection — cross-model comparison

## Table A — In-distribution (dataset_v1_test, n=450)

Prompts drawn from the same seven sources used for training.
Cell format: `detected / total (recall%)`

| Attack type | n | DistilBERT | RoBERTa | TF-IDF+LR |
|---|---:|---:|---:|---:|
| injection | 147 | 147/147 (100.0%) | 147/147 (100.0%) | 147/147 (100.0%) |
| jailbreak_explicit | 47 | 46/47 (97.9%) | 46/47 (97.9%) | 43/47 (91.5%) |
| prompt_injection | 14 | 12/14 (85.7%) | 12/14 (85.7%) | 11/14 (78.6%) |
| indirect_rag_injection | 6 | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) |
| fictional_framing | 5 | 5/5 (100.0%) | 4/5 (80.0%) | 5/5 (100.0%) |
| authority_claim | 3 | 3/3 (100.0%) | 3/3 (100.0%) | 2/3 (66.7%) |
| persona_jailbreak | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| direct_harmful_request | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| **none (benign)** | 225 | 4 FP / 225 (98.2% spec) | 4 FP / 225 (98.2% spec) | 4 FP / 225 (98.2% spec) |

## Table B — Out-of-distribution (probe_data_v2, n=440)

Novel GPT-generated prompts, none seen during training.
All samples are malicious (no benign baseline for this table).
Cell format: `detected / total (recall%)`

| Attack type | n | DistilBERT | RoBERTa | TF-IDF+LR |
|---|---:|---:|---:|---:|
| persona_jailbreak | 40 | 40/40 (100.0%) | 31/40 (77.5%) | 35/40 (87.5%) |
| indirect_rag_injection | 40 | 37/40 (92.5%) | 35/40 (87.5%) | 30/40 (75.0%) |
| goal_hijacking | 40 | 38/40 (95.0%) | 25/40 (62.5%) | 26/40 (65.0%) |
| authority_claim | 40 | 34/40 (85.0%) | 17/40 (42.5%) | 29/40 (72.5%) |
| direct_harmful_request | 40 | 28/40 (70.0%) | 15/40 (37.5%) | 15/40 (37.5%) |
| obfuscated_payload | 40 | 27/40 (67.5%) | 19/40 (47.5%) | 7/40 (17.5%) |
| completion_hijack | 40 | 30/40 (75.0%) | 7/40 (17.5%) | 10/40 (25.0%) |
| fictional_framing | 40 | 20/40 (50.0%) | 10/40 (25.0%) | 12/40 (30.0%) |
| payload_splitting | 40 | 19/40 (47.5%) | 7/40 (17.5%) | 7/40 (17.5%) |
| hypothetical_framing | 40 | 5/40 (12.5%) | 1/40 (2.5%) | 2/40 (5.0%) |
| camouflaged_harmful | 40 | 4/40 (10.0%) | 1/40 (2.5%) | 1/40 (2.5%) |