"""Explicit, paid retrieval-only experiment on an API-ingested disposable corpus.

No chat calls or database writes. Structural vectors are temporary experimental
data, never product indexes. Uses the production embedding abstraction.
"""
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean

import numpy as np
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.config import get_settings  # noqa: E402 - repository path setup
from app.database import SessionLocal  # noqa: E402 - repository path setup
from app.knowledge.lexical import significant_query  # noqa: E402 - repository path setup
from app.knowledge.models import ChunkEmbedding, DocumentChunk  # noqa: E402 - repository path setup
from app.knowledge.providers import (  # noqa: E402 - repository path setup
    OpenAIClient,
    OpenAIEmbeddingProvider,
)
from app.knowledge.retrieval import KnowledgeRetriever  # noqa: E402 - repository path setup
from app.models import (  # noqa: E402 - repository path setup
    Document,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
)
from app.policy import OrganizationContext  # noqa: E402 - repository path setup

CACHE = ROOT / ".git/m2-1-evaluation"
OUT = ROOT / "docs/evaluation/m2_1"
dataset = ROOT / "docs/evaluation/M2_EVALUATION_DATASET.jsonl"
assert hashlib.sha256(dataset.read_bytes()).hexdigest() == "5acef85bd33f943145cf21c33a95e357fdf2d5666e86dadb416dba59f5ea6741"
questions = [json.loads(line) for line in dataset.read_text(encoding="utf8").splitlines()]
mapping = json.loads((OUT / "M2_1_DOCUMENT_MAP.json").read_text())
inverse = {v["document_id"]: k for k, v in mapping.items()}
assert not (OUT / "M2_1_RETRIEVAL_CANDIDATES.json").exists(), "Do not rerun a frozen experiment"


class ObservedClient(OpenAIClient):
    def post(self, path, payload):
        result = super().post(path, payload)
        with (CACHE / "offline-usage.jsonl").open("a", encoding="utf8") as f:
            f.write(json.dumps({"stage": path, "model": payload["model"], "usage": result.get("usage", {})}) + "\n")
        return result


def norm(text):
    return " ".join(text.lower().split()).replace("cha rge", "charge").replace("parametrized", "parameterized")


def relevant(row, e):
    return (inverse[str(row["document_id"])] == e["document_id"]
            and (e["page"] is None or row["source_locator"].get("page") == e["page"])
            and all(a.lower() in norm(row["excerpt"]) for a in e["anchors"]))


settings = get_settings()
provider = OpenAIEmbeddingProvider(settings, ObservedClient(settings))
with SessionLocal() as db:
    org_id = db.scalar(select(Document.organization_id).where(Document.id.in_(list(mapping_value["document_id"] for mapping_value in mapping.values()))).limit(1))
    org = db.get(Organization, org_id)
    membership = db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == org_id, OrganizationMembership.role == OrganizationRole.OWNER))
    context = OrganizationContext(db.get(User, membership.user_id), org, membership)
    retriever = KnowledgeRetriever(settings, provider)
    authorized = retriever.eligible(context).add_columns(ChunkEmbedding.embedding, DocumentChunk.heading_path).join(
        ChunkEmbedding, (ChunkEmbedding.document_chunk_id == DocumentChunk.id) & (ChunkEmbedding.organization_id == DocumentChunk.organization_id)
    ).where(ChunkEmbedding.provider == provider.provider, ChunkEmbedding.model == provider.model,
            ChunkEmbedding.dimensions == provider.dimensions).cte("authorized").prefix_with("MATERIALIZED")
    rows = [dict(row) for row in db.execute(select(authorized)).mappings()]
    assert len(rows) == 260 and {str(r["document_id"]) for r in rows} == set(inverse)
    original = np.array([row["embedding"] for row in rows])
    db.commit()
    prefixes = [f"Document: {row['title']}\nSection: {' / '.join(row['heading_path'])}\n"
                + (f"Page: {row['source_locator']['page']}\n" if 'page' in row['source_locator'] else '')
                + "\n" + row['excerpt'] for row in rows]
    structural = []
    for i in range(0, len(prefixes), 32):
        structural.extend(provider.embed_texts(prefixes[i:i+32]))
    vectors = []
    for i in range(0, len(questions), 32):
        vectors.extend(provider.embed_texts([q["question"] for q in questions[i:i+32]]))
    structural = np.array(structural)
    # Keep separate experiment cache; no embedding rows are created/replaced.
    np.savez(CACHE / "offline-vectors.npz", original=original, structural=structural, queries=np.array(vectors))
    candidates = {key: [] for key in ["control", "A_structural", "B_lexical", "C_combined"]}
    lexical_counts = []
    for q, vector in zip(questions, vectors, strict=True):
        ranked = {}
        for name, matrix in [("original", original), ("structural", structural)]:
            similarities = matrix @ vector / np.linalg.norm(matrix, axis=1) / np.linalg.norm(vector)
            ranked[name] = sorted(range(len(rows)), key=lambda i: (-similarities[i], str(rows[i]["chunk_id"])))[:24]
        columns = [c for c in authorized.c if c.key not in {"embedding", "heading_path"}]
        lexical = {}
        for name, config, query in [
            ("plain", "simple", func.plainto_tsquery("simple", q["question"])),
            ("web_full", "english", func.websearch_to_tsquery("english", q["question"])),
            ("significant", "english", func.websearch_to_tsquery("english", significant_query(q["question"]))),
        ]:
            tsv = func.to_tsvector(config, authorized.c.excerpt)
            selected = db.execute(select(*columns).where(tsv.op("@@")(query)).order_by(
                func.ts_rank_cd(tsv, query, 32).desc(), authorized.c.chunk_id).limit(24)).mappings().all()
            lexical[name] = [next(i for i,r in enumerate(rows) if r["chunk_id"] == x["chunk_id"]) for x in selected]
        lexical_counts.append({"question_id": q["id"], **{name: len(value) for name,value in lexical.items()}})
        for name, semantic, lex in [("control", "original", "plain"), ("A_structural", "structural", "plain"),
                                    ("B_lexical", "original", "significant"), ("C_combined", "structural", "significant")]:
            scores = {}
            for selected in [ranked[semantic], lexical[lex]]:
                for rank, index in enumerate(selected, 1):
                    scores[index] = scores.get(index, 0) + 1/(60+rank)
            top = sorted(scores, key=lambda i: (-scores[i], str(rows[i]["chunk_id"])))[:8]
            ranks = [next((rank for rank,index in enumerate(top,1) if relevant(rows[index],e)), None) for e in q["required_evidence"]]
            candidates[name].append({"question_id": q["id"], "source_documents": q["source_documents"], "ranks": ranks,
                "items": [{"chunk_id": str(rows[i]["chunk_id"]), "document": inverse[str(rows[i]["document_id"])],
                           "locator": rows[i]["source_locator"], "score": scores[i]} for i in top]})
        print(q["id"], "retrieval-only captured", flush=True)
    def aggregate(records):
        positives = [r for r in records if r["ranks"]]
        result = {"answerable_n": len(positives)}
        for k in [1,3,5,8]:
            result[f"hit_at_{k}"] = mean(any(rank is not None and rank<=k for rank in r["ranks"]) for r in positives)
            result[f"recall_at_{k}"] = mean(sum(rank is not None and rank<=k for rank in r["ranks"])/len(r["ranks"]) for r in positives)
        result["mrr"] = mean(1/min((rank for rank in r["ranks"] if rank is not None), default=float('inf')) for r in positives)
        return result
    registry = json.loads((ROOT / "docs/evaluation/corpus.json").read_text())
    pdf_ids = {r["id"] for r in registry if r["format"] == "PDF"}
    summaries = {key: {"overall": aggregate(value), "pdf": aggregate([r for r in value if pdf_ids.intersection(r["source_documents"])]),
                       "nist": aggregate([r for r in value if "DOC03" in r["source_documents"]])} for key,value in candidates.items()}
    capture = {"dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(), "no_chat_calls": True,
               "no_derived_database_writes": True, "summaries": summaries, "lexical_candidate_counts": lexical_counts, "candidates": candidates}
    (OUT / "M2_1_RETRIEVAL_CANDIDATES.json").write_text(json.dumps(capture, indent=2), encoding="utf8")
    print(json.dumps(summaries,indent=2))
