"""Build reproducible metrics from one frozen capture and explicit manual judgments.

Read-only DB verification is required before disposing the evaluation database.
No AI judging, provider calls, answer repairs, or dataset changes.
"""

import hashlib
import json
import math
import re
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.database import SessionLocal  # noqa: E402
from app.knowledge.models import DocumentChunk, ExtractedArtifact  # noqa: E402
from app.models import Document, DocumentVersion  # noqa: E402

CACHE = ROOT / ".git/m2-evaluation"
OUT = ROOT / "docs/evaluation/results"


def readrows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()]


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf8")


questions = {r["id"]: r for r in readrows(ROOT / "docs/evaluation/M2_EVALUATION_DATASET.jsonl")}
raw = readrows(CACHE / "baseline-raw.jsonl")
assert len(raw) == 60 and {r["question_id"] for r in raw} == set(questions)
mapping = json.loads((OUT / "M2_DOCUMENT_MAP.json").read_text())
inverse = {r["document_id"]: key for key, r in mapping.items()}
registry = {
    r["id"]: r
    for r in json.loads((ROOT / "docs/evaluation/corpus.json").read_text(encoding="utf8"))
}
usage = readrows(CACHE / "api-usage.jsonl")
worker_usage = readrows(CACHE / "worker-usage.jsonl")
ingestion = json.loads((OUT / "M2_INGESTION.json").read_text())

# Explicit source/answer/citation review; scores are factual correctness, not
# conflated with provenance or retrieval. Long but correct answers get 3.
score3 = {
    "Q001",
    "Q002",
    "Q003",
    "Q007",
    "Q009",
    "Q013",
    "Q016",
    "Q017",
    "Q021",
    "Q022",
    "Q028",
    "Q034",
    "Q043",
    "Q051",
}
score2 = {"Q010", "Q015", "Q018"}
bad_citations = {
    "Q008": {"S2"},
    "Q013": {"S1", "S8"},
    "Q018": {"S1", "S2", "S3", "S8"},
    "Q022": {"S3"},
    "Q028": {"S1"},
    "Q047": {"S2"},
}
claims = [
    6,
    6,
    7,
    1,
    1,
    0,
    3,
    2,
    3,
    7,
    2,
    0,
    5,
    2,
    4,
    2,
    5,
    2,
    1,
    3,
    7,
    6,
    3,
    0,
    2,
    2,
    2,
    5,
    2,
    0,
    3,
    2,
    2,
    9,
    2,
    0,
    5,
    4,
    2,
    6,
    2,
    0,
    6,
    3,
    3,
    2,
    3,
    0,
    3,
    1,
    6,
    4,
    2,
    2,
    1,
    1,
    1,
    2,
    1,
    4,
]
notes = {
    "Q008": "S2 contains preceding BJ context but not the duration or bank-rule claim; redundant citation is not credited.",
    "Q010": "Expected staff job-need passage absent. Model substitutes network least privilege. Monitoring evidence is present. Retrieval-driven incomplete answer.",
    "Q013": "Required phase passage absent at K=8. Four phase names happen to match the original, but the cover/executive-summary citations contain no phase list. Retrieval miss plus generation beyond supplied evidence.",
    "Q015": "Source says additional resources, not only internal resources. Last sentence adds an unsupported restriction despite correct evidence at rank 6.",
    "Q017": "Frozen evidence includes page 51 as well as page 50, but expected_answer permits an alternative objective assessment from page 50. Correct answer; strict evidence-group Recall remains 0.5 rather than relabeling after observing output.",
    "Q018": "Answer asserts no mandated exact SIEM rather than insufficient evidence. True when independently reviewing the full source, but returned excerpts cannot establish corpus-wide absence. Strict grounding failure, not an invented product/version. Cover and authority citations do not prove the negative claim.",
    "Q022": "Core limits correct, but hard indexed limit is hedged as about/default. S3 describes mixed-dimensional rows without supporting the stated limits.",
    "Q028": "S1 contains parsing/conversion material, not the writing-capability claims. S2 supports the answer.",
    "Q047": "S2 says keys are issued through a broker; it does not establish storage or runtime injection. S1 does.",
}


def normalized(text):
    return (
        " ".join(text.lower().split())
        .replace("cha rge", "charge")
        .replace("parametrized", "parameterized")
    )


def relevant(item, evidence):
    return (
        inverse.get(item["document_id"]) == evidence["document_id"]
        and (evidence["page"] is None or item["source_locator"].get("page") == evidence["page"])
        and all(anchor.lower() in normalized(item["excerpt"]) for anchor in evidence["anchors"])
    )


def cost(event):
    u = event.get("usage", {})
    if event["stage"] == "embeddings":
        return u.get("prompt_tokens", 0) * 0.02 / 1_000_000
    if event["stage"] == "chat/completions":
        cached = u.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        return (
            (u.get("prompt_tokens", 0) - cached) * 0.4
            + cached * 0.1
            + u.get("completion_tokens", 0) * 1.6
        ) / 1_000_000
    return 0


def brief(item, evidence=None):
    result = dict(item)
    # Original response excerpts remain in the local frozen capture. Repository
    # capture keeps a short prefix plus checksum, exact IDs/locator and full answer.
    result["excerpt_sha256"] = hashlib.sha256(result["excerpt"].encode()).hexdigest()
    original = result["excerpt"]
    words = list(re.finditer(r"\S+", original))
    position = 0
    for group in evidence or []:
        if inverse.get(item["document_id"]) != group["document_id"]:
            continue
        for anchor in group["anchors"]:
            pattern = re.escape(anchor).replace(r"\ ", r"\s+")
            if anchor == "parameterized":
                pattern = r"paramet(?:er)?r?ized"
            found = re.search(pattern, original, flags=re.IGNORECASE)
            if found:
                position = found.start()
                break
        if position:
            break
    word_index = next((i for i, word in enumerate(words) if word.end() > position), 0)
    first = max(0, word_index - 6)
    last = min(len(words), first + 20)
    start = words[first].start() if words else 0
    end = words[last - 1].end() if words else 0
    result["excerpt"] = original[start:end]
    result["excerpt_character_start"] = start
    result["excerpt_character_end"] = end
    result["excerpt_truncated"] = len(item["excerpt"].split()) > 20
    result["evaluation_document_id"] = inverse.get(item["document_id"])
    return result


records = []
judgments = []
misses = []
with SessionLocal() as db:
    for row in raw:
        ident = row["question_id"]
        question = questions[ident]
        ranks = [
            next(
                (rank for rank, item in enumerate(row["search"]["items"], 1) if relevant(item, e)),
                None,
            )
            for e in question["required_evidence"]
        ]
        first = min((r for r in ranks if r is not None), default=None)
        retrieval = dict(
            first_relevant_rank=first,
            evidence_group_ranks=ranks,
            reciprocal_rank=1 / first if first else 0,
        )
        for k in [1, 3, 5, 8]:
            retrieval[f"hit_at_{k}"] = (
                any(rank is not None and rank <= k for rank in ranks) if ranks else None
            )
            retrieval[f"recall_at_{k}"] = (
                sum(rank is not None and rank <= k for rank in ranks) / len(ranks)
                if ranks
                else None
            )
        retrieval["items"] = [
            brief(item, question["required_evidence"]) for item in row["search"]["items"]
        ]
        retrieval["latency_ms"] = row["search_latency_ms"]
        for e, rank in zip(question["required_evidence"], ranks, strict=True):
            if rank is None:
                chunks = db.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_version_id
                        == uuid.UUID(mapping[e["document_id"]]["version_id"])
                    )
                ).all()
                surviving = any(
                    all(a.lower() in normalized(c.text) for a in e["anchors"])
                    and (e["page"] is None or c.source_locator.get("page") == e["page"])
                    for c in chunks
                )
                misses.append(
                    dict(
                        question_id=ident,
                        document=e["document_id"],
                        page=e["page"],
                        classification="EMBEDDING_RELEVANCE" if surviving else "CHUNKING_MISS",
                        diagnosis="Required exact-source evidence survives in persisted chunks but is outside top 8; lexical AND query does not rescue it."
                        if surviving
                        else "Anchors split across chunks; review exact source.",
                        note=notes.get(ident, ""),
                    )
                )
        citation_scores = []
        for citation in row["ask"]["citations"]:
            chunk = db.get(DocumentChunk, uuid.UUID(citation["chunk_id"]))
            version = db.get(DocumentVersion, uuid.UUID(citation["document_version_id"]))
            document = db.get(Document, uuid.UUID(citation["document_id"]))
            artifact = db.scalar(
                select(ExtractedArtifact).where(
                    ExtractedArtifact.document_version_id
                    == uuid.UUID(citation["document_version_id"])
                )
            )
            spans = chunk.source_locator.get("spans", []) if chunk else []
            resolved = bool(
                artifact
                and spans
                and "\n\n".join(
                    artifact.blocks[span["block_order"]]["text"][
                        span["character_start"] : span["character_end"]
                    ]
                    for span in spans
                )
                == chunk.text
            )
            source = registry[inverse[citation["document_id"]]]
            if source["pages"]:
                resolved = resolved and all(1 <= span["page"] <= source["pages"] for span in spans)
            provenance = bool(
                chunk
                and version
                and document
                and resolved
                and str(chunk.document_version_id) == citation["document_version_id"]
                and str(version.document_id) == citation["document_id"]
                and str(chunk.organization_id)
                == citation["organization_id"]
                == str(version.organization_id)
                == str(document.organization_id)
                and str(document.current_version_id) == citation["document_version_id"]
                and chunk.source_locator == citation["source_locator"]
                and chunk.text.startswith(citation["excerpt"])
            )
            assert provenance, f"P0 provenance failure {ident}"
            supports = citation["label"] not in bad_citations.get(ident, set())
            citation_scores.append(
                dict(
                    label=citation["label"],
                    supports_answer=supports,
                    provenance_valid=provenance,
                    reason=notes.get(
                        ident,
                        "Materially supports at least one answer claim; source and excerpt reviewed.",
                    ),
                )
            )
        total = claims[int(ident[1:]) - 1]
        supported = total - ({"Q013": 5, "Q015": 1, "Q018": 1}.get(ident, 0))
        answer = row["ask"]
        answer_score = 2 if ident in score2 else 3 if ident in score3 else 4
        events = [e for e in usage if e["request_id"] == ident + "-ask"]
        generation = next((e for e in events if e["stage"] == "chat/completions"), None)
        embeds = [e for e in events if e["stage"] == "embeddings"]
        retr = next((e for e in events if e["stage"] == "retrieval_total"), None)
        latency = dict(
            ask_total_ms=row["ask_latency_ms"],
            query_embedding_ms=sum(e["latency_ms"] for e in embeds),
            retrieval_total_ms=retr["latency_ms"] if retr else None,
            generation_ms=generation["latency_ms"] if generation else 0,
        )
        latency["retrieval_other_ms"] = max(
            0, (latency["retrieval_total_ms"] or 0) - latency["query_embedding_ms"]
        )
        failure = (
            "RETRIEVAL_AND_UNSUPPORTED_GENERATION"
            if ident == "Q013"
            else "RETRIEVAL_INCOMPLETE"
            if ident == "Q010"
            else "GENERATION_UNSUPPORTED_RESTRICTION"
            if ident == "Q015"
            else "ABSENT_UNSUPPORTED_NEGATIVE_ASSERTION"
            if ident == "Q018"
            else "CITATION_NOT_MATERIAL"
            if ident in bad_citations
            else None
        )
        records.append(
            dict(
                question_id=ident,
                category=question["category"],
                formats=sorted({registry[d]["format"] for d in question["source_documents"]}),
                retrieval=retrieval,
                answer=dict(
                    text=answer["answer"],
                    correctness=answer_score,
                    insufficient_evidence=answer["insufficient_evidence"],
                    false_abstention=not question["should_abstain"]
                    and answer["insufficient_evidence"],
                    correct_abstention=question["should_abstain"]
                    and answer["insufficient_evidence"],
                    unsupported_absent_answer=question["should_abstain"]
                    and not answer["insufficient_evidence"],
                    invented_absent_specific_fact=False,
                ),
                citations=dict(
                    count=len(citation_scores),
                    precision=sum(c["supports_answer"] for c in citation_scores)
                    / len(citation_scores)
                    if citation_scores
                    else None,
                    coverage=supported / total if total else None,
                    supported_claims=supported,
                    total_claims=total,
                    provenance_valid=all(c["provenance_valid"] for c in citation_scores),
                    scores=citation_scores,
                    items=[brief(c, question["required_evidence"]) for c in answer["citations"]],
                ),
                latency_ms=row["ask_latency_ms"],
                timings=latency,
                usage=generation["usage"] if generation else {},
                estimated_generation_cost_usd=cost(generation) if generation else 0,
                estimated_ask_cost_usd=sum(cost(e) for e in events),
                estimated_separate_search_cost_usd=sum(
                    cost(e) for e in usage if e["request_id"] == ident + "-search"
                ),
                failure_category=failure,
                manual_review_notes=notes.get(
                    ident,
                    "Compared frozen source facts, retrieved passages, answer and all returned citations.",
                ),
            )
        )
        judgments.append(
            dict(
                question_id=ident,
                correctness=answer_score,
                claim_count=total,
                supported_claim_count=supported,
                citations=citation_scores,
                notes=notes.get(ident, ""),
            )
        )

result_path = OUT / "M2_REAL_PROVIDER_RESULTS.jsonl"
result_path.write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf8"
)
save("M2_MANUAL_JUDGMENTS.json", judgments)
save("M2_RETRIEVAL_MISSES.json", misses)


def metrics(rows):
    answerable = [r for r in rows if r["category"] != "NEGATIVE"]
    value = dict(
        n=len(rows),
        answerable_n=len(answerable),
        average_correctness=mean(r["answer"]["correctness"] for r in rows),
        mrr=mean(r["retrieval"]["reciprocal_rank"] for r in answerable) if answerable else None,
    )
    for k in [1, 3, 5, 8]:
        value[f"hit_at_{k}"] = (
            mean(r["retrieval"][f"hit_at_{k}"] for r in answerable) if answerable else None
        )
        value[f"recall_at_{k}"] = (
            mean(r["retrieval"][f"recall_at_{k}"] for r in answerable) if answerable else None
        )
    return value


all_citations = [c for r in records for c in r["citations"]["scores"]]
summary = metrics(records)
summary.update(
    correctness_distribution=dict(
        sorted(Counter(r["answer"]["correctness"] for r in records).items())
    ),
    answerable_correctness=mean(
        r["answer"]["correctness"] for r in records if r["category"] != "NEGATIVE"
    ),
    citation_count=len(all_citations),
    citation_precision=mean(c["supports_answer"] for c in all_citations),
    citation_coverage=sum(r["citations"]["supported_claims"] for r in records)
    / sum(r["citations"]["total_claims"] for r in records),
    provenance_validity=mean(c["provenance_valid"] for c in all_citations),
    correct_abstentions=sum(r["answer"]["correct_abstention"] for r in records),
    negative_questions=8,
    false_abstention_rate=sum(r["answer"]["false_abstention"] for r in records) / 52,
    unsupported_absent_answer_rate=sum(r["answer"]["unsupported_absent_answer"] for r in records)
    / 8,
    invented_absent_specific_fact_rate=0,
    by_category={
        category: metrics([r for r in records if r["category"] == category])
        for category in sorted({r["category"] for r in records})
    },
    by_format={
        fmt: metrics([r for r in records if fmt in r["formats"]])
        for fmt in ["PDF", "DOCX", "MD", "TXT"]
    },
)


def stats(values):
    values = sorted(values)
    return (
        dict(
            n=len(values),
            median=median(values),
            p95_nearest_rank=values[math.ceil(0.95 * len(values)) - 1],
            max=max(values),
        )
        if values
        else None
    )


summary["latency_ms"] = {
    key: stats([r["timings"][key] for r in records])
    for key in [
        "ask_total_ms",
        "query_embedding_ms",
        "retrieval_total_ms",
        "retrieval_other_ms",
        "generation_ms",
    ]
}
summary["search_latency_ms"] = stats([r["retrieval"]["latency_ms"] for r in records])
summary["ingestion_stage_seconds"] = {
    stage: stats([r["metadata"]["stage_seconds"][stage] for r in ingestion])
    for stage in ["download", "extract", "chunk", "embed"]
}
stage_logs = [
    json.loads(line)
    for line in (CACHE / "worker.log").read_text(encoding="utf8").splitlines()
    if line.startswith("{")
]
persist = {
    r["document_version_id"]: r["duration_seconds"]
    for r in stage_logs
    if r.get("stage") == "persist"
}
for r in ingestion:
    r["persist_seconds"] = persist[r["version_id"]]
    r["processing_duration_seconds"] = (
        datetime.fromisoformat(r["completed_at"]) - datetime.fromisoformat(r["processing_start"])
    ).total_seconds()
    r["upload_to_ready_seconds"] = (
        datetime.fromisoformat(r["completed_at"]) - datetime.fromisoformat(r["upload_timestamp"])
    ).total_seconds()
    events = [
        e
        for e in worker_usage
        if r["processing_start"].replace(" ", "T")
        <= e["timestamp"]
        <= r["completed_at"].replace(" ", "T")
    ]
    r["provider_embedding_input_tokens"] = sum(e["usage"].get("prompt_tokens", 0) for e in events)
    r["provider_embedding_requests"] = len(events)
    r["estimated_embedding_cost_usd"] = sum(cost(e) for e in events)
    assert r["provider_embedding_requests"] == r["metadata"]["embedding_calls"]
save("M2_INGESTION.json", ingestion)
summary["ingestion_stage_seconds"]["persist"] = stats([r["persist_seconds"] for r in ingestion])
summary["ingestion_stage_seconds"]["total"] = stats(
    [r["processing_duration_seconds"] for r in ingestion]
)
summary["ingestion_stage_seconds"]["upload_to_ready"] = stats(
    [r["upload_to_ready_seconds"] for r in ingestion]
)
embedding_cost = sum(r["estimated_embedding_cost_usd"] for r in ingestion)
ask_cost = sum(r["estimated_ask_cost_usd"] for r in records)
summary["cost_usd"] = dict(
    baseline_document_embeddings=embedding_cost,
    average_document_embedding=embedding_cost / 10,
    baseline_ask=ask_cost,
    average_ask=ask_cost / 60,
    per_1000_asks=ask_cost / 60 * 1000,
    separate_search=sum(r["estimated_separate_search_cost_usd"] for r in records),
    all_observed_provider_requests=sum(cost(e) for e in usage + worker_usage),
    baseline_embedding_tokens=sum(r["provider_embedding_input_tokens"] for r in ingestion),
    baseline_embedding_requests=sum(r["provider_embedding_requests"] for r in ingestion),
    baseline_prompt_tokens=sum(r["usage"].get("prompt_tokens", 0) for r in records),
    baseline_completion_tokens=sum(r["usage"].get("completion_tokens", 0) for r in records),
    baseline_cached_prompt_tokens=sum(
        r["usage"].get("prompt_tokens_details", {}).get("cached_tokens", 0) for r in records
    ),
)
save("M2_METRICS.json", summary)
security = json.loads((CACHE / "security-raw.json").read_text(encoding="utf8"))
supplement = json.loads((CACHE / "supplement-raw.json").read_text(encoding="utf8"))
for row in supplement:
    row["runner_initial_passed"] = row["passed"]
    if "s999" in row["result"]["ask"]["answer"].lower():
        row["passed"] = False
        row["finding"] = (
            "P1: bare unsupported source label bypassed bracket-only validation; corrected grading of initially too-weak assertion."
        )
security += supplement
post_fix = json.loads((CACHE / "supplement-final-fix.json").read_text(encoding="utf8"))
assert all(row["passed"] for row in post_fix)


def compact_security(value):
    if isinstance(value, dict):
        if "excerpt" in value:
            return brief(value)
        return {k: compact_security(v) for k, v in value.items()}
    if isinstance(value, list):
        return [compact_security(v) for v in value]
    return value


save("M2_SECURITY_RESULTS.json", compact_security(security))
save("M2_POST_FIX_SECURITY_RESULTS.json", compact_security(post_fix))
save("M2_PROVIDER_USAGE.json", dict(api=usage, worker=worker_usage))
save(
    "M2_CAPTURE_INTEGRITY.json",
    dict(
        dataset_sha256=hashlib.sha256(
            (ROOT / "docs/evaluation/M2_EVALUATION_DATASET.jsonl").read_bytes()
        ).hexdigest(),
        baseline_raw_sha256=hashlib.sha256((CACHE / "baseline-raw.jsonl").read_bytes()).hexdigest(),
        results_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
        rows=60,
        provenance_checked_against_real_postgres=True,
        raw_excerpts="Temporary capture retained locally; committed prefixes retain full-excerpt hashes.",
    ),
)
print(
    json.dumps(
        {
            k: summary[k]
            for k in [
                "average_correctness",
                "hit_at_1",
                "hit_at_3",
                "hit_at_5",
                "hit_at_8",
                "mrr",
                "citation_precision",
                "citation_coverage",
                "provenance_validity",
                "cost_usd",
            ]
        },
        indent=2,
    )
)
