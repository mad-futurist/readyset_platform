"""Explicit real-provider grounding probes; never ordinary CI or primary scoring."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.knowledge.answers import EvidenceAnswerer  # noqa: E402
from app.knowledge.contracts import AskRequest  # noqa: E402
from app.knowledge.models import DocumentChunk  # noqa: E402
from app.knowledge.providers import (  # noqa: E402
    OpenAIChatProvider,
    OpenAIClient,
    OpenAIEmbeddingProvider,
)
from app.knowledge.retrieval import KnowledgeRetriever  # noqa: E402
from app.models import (  # noqa: E402
    Document,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
)
from app.policy import OrganizationContext  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["probe", "supplement"])
mode = parser.parse_args().mode
CACHE = ROOT / ".git/m2-1-evaluation"
output = CACHE / f"grounding-{mode}.json"
assert not output.exists(), "Never overwrite a measured capture"
mapping = json.loads((ROOT / "docs/evaluation/m2_1/M2_1_DOCUMENT_MAP.json").read_text())
settings = get_settings()


class ObservedClient(OpenAIClient):
    def post(self, path, payload):
        started = time.perf_counter()
        result = super().post(path, payload)
        with (CACHE / "grounding-usage.jsonl").open("a", encoding="utf8") as stream:
            stream.write(json.dumps({"mode": mode, "stage": path, "model": payload["model"],
                "usage": result.get("usage", {}), "latency_ms": (time.perf_counter()-started)*1000})+"\n")
        return result


class PartialRetriever(KnowledgeRetriever):
    def __init__(self, page, *args):
        super().__init__(*args)
        self.page = page
        self.supplied = []

    def retrieve(self, db, context, query, top_k=None, document_ids=None):
        rows = db.execute(self.eligible(context).where(
            Document.id == uuid.UUID(mapping["DOC03"]["document_id"]),
            DocumentChunk.source_locator["page"].as_integer() == self.page,
        ).order_by(DocumentChunk.ordinal)).mappings().all()
        self.supplied = [self._evidence(context, dict(row), 0.0) for row in rows]
        assert self.supplied
        return self.supplied


records = []
with SessionLocal() as db:
    org_id = db.get(Document, uuid.UUID(mapping["DOC03"]["document_id"])).organization_id
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org_id, OrganizationMembership.role == OrganizationRole.OWNER))
    context = OrganizationContext(db.get(User, membership.user_id), db.get(Organization, org_id), membership)
    client = ObservedClient(settings)
    embedding = OpenAIEmbeddingProvider(settings, client)
    chat = OpenAIChatProvider(settings, client)
    cases = []
    if mode == "probe":
        dataset = [json.loads(line) for line in (ROOT / "docs/evaluation/M2_EVALUATION_DATASET.jsonl").read_text(encoding="utf8").splitlines()]
        for q in dataset:
            if q["id"] in {"Q001", "Q008", "Q013"}:
                cases.append((q["id"], q["question"], KnowledgeRetriever(settings, embedding), False))
    cases.extend([
        ("public-known-phases-evidence-excluded", "What are the major incident response phases in NIST SP 800-61 Revision 2?", PartialRetriever(3, settings, embedding), True),
        ("exact-siem-global-negative-partial-evidence", "Which exact SIEM product and version does NIST SP 800-61 Revision 2 mandate buying?", PartialRetriever(37, settings, embedding), True),
    ])
    for name, question, retriever, should_abstain in cases:
        response = EvidenceAnswerer(settings, retriever, chat).ask(db, context, AskRequest(query=question))
        row = {"scenario": name, "timestamp": datetime.now(UTC).isoformat(), "question": question,
               "expected_abstention": should_abstain, "passed": response.insufficient_evidence == should_abstain,
               "answer": response.answer, "insufficient_evidence": response.insufficient_evidence,
               "citations": [{"label": c.label, "chunk_id": str(c.chunk_id), "document_version_id": str(c.document_version_id),
                               "source_locator": c.source_locator} for c in response.citations]}
        if isinstance(retriever, PartialRetriever):
            row["supplied_evidence"] = [{"chunk_id": str(c.chunk_id), "source_locator": c.source_locator,
                "excerpt_sha256": hashlib.sha256(c.excerpt.encode()).hexdigest(),
                "preview": " ".join(c.excerpt.split()[:20])} for c in retriever.supplied]
        records.append(row)
        print(name, "PASS" if row["passed"] else "FAIL", flush=True)
    output.write_text(json.dumps(records, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    assert all(row["passed"] for row in records), "Grounding probe failure; preserve capture"
