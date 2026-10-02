# M2 baseline versus M2.1 quality comparison

**NOT READY — GROUNDING/RETRIEVAL REGRESSION**

TESTED: one complete 60-question primary real-provider run on another fresh API-uploaded corpus. Original M2 evidence remains immutable. Dataset SHA-256 `5acef85bd33f943145cf21c33a95e357fdf2d5666e86dadb416dba59f5ea6741`; ten unchanged source byte hashes; 10/10 READY, 260 fresh chunks, 68,000 embedding tokens. Same models, chunk bounds and whole-corpus question order. No answer repair, document filters, question relabeling or quality-based retry.

The candidate improves source containment, absent-question abstention and PDF retrieval, but does not establish reliable question-specific grounding. Q013 retrieves the right phase passage yet selects only its introduction. Q016 loses the waiting-period passage and answers from related initial-handling instructions. Q058 selects an Atlas owner instead of the explicitly requested warehouse owner. Valid source quotations are not proof of sufficient support for the question. These are acceptance-blocking findings even though aggregate citation measures improve.

## Primary metrics

| Measure | M2 baseline | M2.1 primary |
|---|---:|---:|
| Hit@1 | 71.2% (37/52) | 73.1% (38/52) |
| Hit@3 | 92.3% (48/52) | 94.2% (49/52) |
| Hit@5 | 96.2% (50/52) | 96.2% (50/52) |
| Hit@8 | 98.1% (51/52) | 98.1% (51/52) |
| Group Recall@1 | 64.4% | 66.3% |
| Group Recall@3 | 89.4% | 91.3% |
| Group Recall@5 | 94.2% | 94.2% |
| Group Recall@8 | 96.2% | 96.2% |
| MRR | 0.825 | 0.840 |
| Correctness /4 | 3.67 | 3.50 |
| Material citation precision | 88.5% (77/87) | 97.1% (66/68) |
| Claim coverage | 96.0% (166/173) | 97.4% (150/154) |
| Technical provenance | 100% (87/87) | 100% (68/68) |
| Correct absent-question abstention | 7/8 (87.5%) | 8/8 (100%) |
| Unsupported absent answers | 1/8 (12.5%) | 0/8 (0%) |
| False abstentions | 0/52 | 0/52 |

Hit means at least one frozen required group; Recall retains every original group, including the conservative Q017 second group. Citation materiality was manually judged against emitted claims and question scope; two wrong-scope citations (Q016, Q058) are not credited merely because their words come from real sources. All 52 answerable questions receive output; incompleteness and wrong scope are scored separately from abstention. The same-assessor second review is not an independent human inter-rater study. Small samples limit generalization; no significance or noninferiority claim is made.

## Format and document outcomes

| Format | Answerable N | Baseline Hit@5 / MRR / correctness | M2.1 Hit@5 / MRR / correctness |
|---|---:|---|---|
| PDF | 15 | 86.7% / 0.647 / 3.20 | 93.3% / 0.733 / 2.87 |
| DOCX | 10 | 100.0% / 0.900 / 3.90 | 100.0% / 0.950 / 3.80 |
| MD | 18 | 100.0% / 0.900 / 3.78 | 94.4% / 0.842 / 3.56 |
| TXT | 11 | 100.0% / 0.909 / 3.82 | 100.0% / 0.909 / 3.55 |

Formats/documents overlap on multi-source questions; denominators do not sum to 52.

| Source | N | Baseline Hit@5 | M2.1 Hit@5 |
|---|---:|---:|---:|
| DOC01 | 5 | 100.0% | 100.0% |
| DOC02 | 5 | 100.0% | 100.0% |
| DOC03 | 5 | 60.0% | 80.0% |
| DOC04 | 5 | 100.0% | 100.0% |
| DOC05 | 5 | 100.0% | 100.0% |
| DOC06 | 5 | 100.0% | 100.0% |
| DOC07 | 5 | 100.0% | 100.0% |
| DOC08 | 7 | 100.0% | 100.0% |
| DOC09 | 6 | 100.0% | 100.0% |
| DOC10 | 7 | 100.0% | 85.7% |

PDF Hit@5 is 13/15 → 14/15; NIST DOC03 is 3/5 → 4/5. Q016 now replaces Q013 as the PDF top-eight miss. The full primary does not reproduce the more favorable offline-screening 15/15 PDF and 5/5 NIST results. Fresh vector calls, database UUID tie-breaking and Python-versus-PostgreSQL numeric ordering may affect borderline rankings; the precise cause is not proven. Acceptance uses the actual production API capture, never the offline screen.

## Required failure-case comparison

Answer cells summarize unchanged full text available in the linked result captures. Citation cells identify the actual chosen source pages/sections; complete IDs, locators, scores and short source previews remain in machine-readable results.

| Case | Baseline retrieval; answer; citations | M2.1 retrieval; answer; citations | Outcome |
|---|---|---|---|
| Q008 | Groups [1]; 30-day answer; one preceding citation did not support its stated facts; S1:DOC02/p5, S2:DOC02/p4 | Groups [2]; 30-day quote plus explicit BJ transaction-context quote; S2:DOC02/p5, S1:DOC02/p4 | IMPROVED material linkage; factual score stays 4 |
| Q010 | Groups [None, 2]; Staff/job-need group missing; substitutes segmentation; monitoring present; S1:DOC02/p10, S2:DOC02/p11 | Groups [None, 2]; Same required group missing; twelve network/monitoring quotations; no staff lesson; S1:DOC02/p10, S2:DOC02/p11 | UNCHANGED failure; score 2 |
| Q013 | Groups [None]; Phase group absent; four names from memory with cover/summary citations; S1:DOC03/p3, S8:DOC03/p11 | Groups [2]; Phase group rank 2; only generic phases/team setup selected, names omitted; S2:DOC03/p31 | REGRESSED correctness 3→1 despite better retrieval; source containment improved |
| Q015 | Groups [6]; Table rank 6; adds unsupported internal-only restriction; S6:DOC03/p43 | Groups [2]; Table rank 2; exact predictable/additional versus unpredictable/outside help; noisy extra rows; S2:DOC03/p43 | IMPROVED 2→3 |
| Q017 | Groups [1, None]; Counts/policy-review alternative answered; frozen second group missing; S1:DOC03/p50, S2:DOC03/p50 | Groups [1, None]; First group rank 1; counts reason correct; objective example omitted; S1:DOC03/p50 | REGRESSED 3→2; second frozen group remains missing |
| Q018 | Groups []; Confident global absence statement based on covers/authority; S1:DOC03/p3, S2:DOC03/p2, S3:DOC03/p5, S8:DOC03/p1 | Groups []; Explicit insufficient evidence, no citations; none | IMPROVED 2→4; correct abstention |
| Q019 | Groups [5]; Actual Installation rank 7; canonical loose-anchor group rank 5; correct 13; S7:DOC04/pgvector/Installation/Linux and Mac | Groups [5]; Actual Installation rank 6; canonical group rank 5; correct 13+, long commands; S6:DOC04/pgvector/Installation/Linux and Mac | Ranking slightly improved; factual 4→3 due noisy extractive output |
| Q022 | Groups [5, 1]; Correct 16000/2000 distinction with hedging and unrelated mixed-dimension citation; S1:DOC04/pgvector/Reference/Vector Type, S3:DOC04/pgvector/Frequently Asked Questions/How many vectors can be stored in a single table?/Can I store vectors with different dimensions in the same column?, S5:DOC04/pgvector/Frequently Asked Questions/How many vectors can be stored in a single table?/What if I want to index vectors with more than 2,000 dimensions? | Groups [3, 5]; Exact storage cap and HNSW vector-type limit with matching selected sources; S5:DOC04/pgvector/Reference/Vector Type, S3:DOC04/pgvector/HNSW | IMPROVED 3→4 |
| Q028 | Groups [2]; Correct read-only/writer answer plus unrelated parsing citation; S1:DOC05/, S2:DOC05/ | Groups [2]; Read-only/Tomli-W source passage only; accurate TOML Kit extra context; S2:DOC05/ | IMPROVED 3→4 |
| Q047 | Groups [1]; Correct broker/runtime answer plus unrelated issuance citation; S1:DOC08/Aster Works Machine Credential Standard/4. Storage and rollout, S2:DOC08/Aster Works Machine Credential Standard/1. Scope | Groups [1]; Storage/runtime clause only; one material source; S1:DOC08/Aster Works Machine Credential Standard/4. Storage and rollout | IMPROVED citation selection; factual score stays 4 |
| Q016 | Groups [1]; 15-minute example retrieved rank 1; answer misses repeat-contact qualifier; S1:DOC03/p43 | Groups [None]; Required group absent from top 8; selects initial handling on page 76 instead of abstaining; S1:DOC03/p76 | REGRESSED 3→1; retrieval + grounding failure |
| Q054 | Groups [1]; Escort and badge-return rules complete; S1:DOC09/ | Groups [1]; Escort only; return-before-leaving omitted; S1:DOC09/ | REGRESSED 4→2 |
| Q058 | Groups [2]; Warehouse coordinator correctly scoped; S1:DOC07/Scope and service ownership, S2:DOC10/Warehouse inventory note — fictional evaluation/Routine inventory facts, S3:DOC10/Warehouse inventory note — fictional evaluation/Ordinary operating instructions | Groups [8]; Warehouse evidence rank 8, but selects Atlas ownership at rank 5; S5:DOC07/Scope and service ownership | REGRESSED 4→0; wrong source scope |

Q019 baseline discrepancy is preserved, not repaired: loose frozen `13` anchor matches Docker context at rank five, while the actual Installation sentence is rank seven. Primary matching uses that same original rule; exact material-passage rank is disclosed separately.

## Cost and latency

| Measure | Baseline | M2.1 |
|---|---:|---:|
| Average Ask USD | 0.001638323 | 0.002061496 |
| Embedding/document USD | 0.000136000 | 0.000136000 |
| Corpus embedding tokens | 68,000 | 68,000 (delta 0) |
| Ask median / p95 ms | 1458.6 / 2652.0 | 1316.3 / 2270.3 |
| Query embedding median / p95 ms | 216.5 / 310.7 | 232.6 / 336.6 |
| Retrieval median / p95 ms | 297.0 / 384.0 | 355.2 / 472.6 |
| SQL/policy/Python remainder median / p95 ms | 73.6 / 132.5 | 113.4 / 170.6 |
| Generation median / p95 ms | 1079.4 / 2313.8 | 907.4 / 1542.4 |
| Search median / p95 ms | 339.2 / 442.3 | 378.1 / 558.8 |
| Ingestion download median / p95 s | 0.022 / 0.215 | 0.009 / 0.039 |
| Ingestion extract median / p95 s | 0.028 / 7.817 | 0.017 / 4.347 |
| Ingestion chunk median / p95 s | 0.007 / 0.261 | 0.004 / 0.287 |
| Ingestion embed median / p95 s | 0.388 / 3.408 | 0.444 / 2.507 |
| Ingestion persist median / p95 s | 0.238 / 1.219 | unavailable (collector log overwritten) |
| Ingestion total median / p95 s | 0.860 / 11.982 | 0.528 / 7.153 |
| Ingestion upload_to_ready median / p95 s | 2.778 / 13.856 | 0.593 / 7.400 |

Average Ask cost delta +25.8%; median Ask -9.8%; median retrieval +19.6%. Neither the +30% Ask nor +50% retrieval latency flag fires. A 21.1-second maximum Ask is retained; p95 remains 2.27 seconds. These are sequential local samples, not load/isolated-host or production SLAs.

All observed M2.1 experiments/trials/probes/security/source/query calls cost approximately USD 0.2495, itemized in `M2_1_EXPERIMENTAL_COST.json`. Primary 60 Ask cost USD 0.123690; final source embedding cost USD 0.001360. No discarded trial is hidden in the primary average. Pricing rechecked 2026-10-02: [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small) USD 0.02/M input; [chat model](https://developers.openai.com/api/docs/models/gpt-4.1-mini) USD 0.40/M input, 0.10/M cached input, 1.60/M output.

KNOWN LIMITATION: persistence-only primary timing was lost when the security worker restarted into the same log path. It is unavailable, not inferred from total. DB job totals and persisted download/extract/chunk/embed timings remain measured; the collector now keeps distinct security logs. Original public download timings remain unavailable; exact cached public bytes were reused.

## Security, review and disposition

TESTED: fifteen repeated live tenant/ACL/current-version scenarios passed, including CERULEAN cross-tenant denial, restricted no-grant/grant/revoke/team/membership revocation, two leased PROCESSING→READY replacements, source injection and unknown labels. Four stronger restricted/full-injection/S999 scenarios passed. Two additional real-product constrained-evidence tests passed: known public NIST phases with only the cover supplied, and exact SIEM product/version with partial body context. Supplements are outside the 60-question denominator. Unit tests enforce source-reference/unknown-label/quote-construction bounds; they do not establish semantic rejection of every valid-but-irrelevant passage.

TESTED review: all sixty new answers manually inspected; second pass reread all sixty, including every original failure/changed score and fifteen deterministically sampled passes. One factual-score disagreement (Q008 3→4) and a Q016 source-audit cause correction are explicit in `M2_1_SECOND_REVIEW.json`. This is a single assessor working in separate passes, not independent human agreement. Manual factual scores, citation materiality and claim coverage remain inspectable independently of metric code.

The lexical change has independent PDF value but introduces the Q016 ranking loss and worsens warehouse-question ranking (Q058). Overall Hit@5 remains 50/52, not the 51/52 offline estimate. The source-selection contract eliminates free-form unsupported words, yet cannot establish question relevance or completeness; it is rejected as the production answer contract on this evidence. Keep both changes reviewable in the draft, with no quality acceptance. A further measured grounding design must preserve the safety boundary while answering all requested facts and abstaining on unsupported scope. No extra model/provider, reranker, external database or M3 work was introduced.

OPERATIONAL REQUIREMENTS remain provider/data approval, environment-only secret management, maintained private storage and malware scanning, release migration/backup/load rehearsal. CI passing proves engineering/security gates; it does not overrule the quality rejection.

## Artifacts

- [Preserved M2 report](../M2_REAL_PROVIDER_EVALUATION.md)
- [Failure analysis before implementation](M2_1_FAILURE_ANALYSIS.md)
- [Selected config and rejected trials](M2_1_CONFIG.md)
- [Primary full results](M2_1_RESULTS.jsonl)
- [Metrics](M2_1_METRICS.json)
- [Manual judgments](M2_1_MANUAL_JUDGMENTS.json)
- [Second review](M2_1_SECOND_REVIEW.json)
- [Security capture](M2_1_SECURITY_RESULTS.json)
- [Grounding supplements](M2_1_GROUNDING_SUPPLEMENT.json)
- [Capture integrity](M2_1_CAPTURE_INTEGRITY.json)
- [Secret audit](M2_1_SECRET_AUDIT.json)
