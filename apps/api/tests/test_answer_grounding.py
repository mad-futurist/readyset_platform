"""An untrusted provider selects source passages; it cannot generate facts."""
import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.knowledge.answers import EvidenceAnswerer, source_passages
from app.knowledge.chunking import TokenCounter
from app.knowledge.contracts import AskRequest, RetrievedEvidence
from app.knowledge.providers import ChatResult, SupportedClaim


def answer(claims: list[SupportedClaim], sources: list[str], sufficient: bool = True):
    items = [RetrievedEvidence(organization_id=uuid.uuid4(), document_id=uuid.uuid4(),
             document_version_id=uuid.uuid4(), chunk_id=uuid.uuid4(), title="Public NIST guide",
             version_number=1, source_locator={"kind": "pdf", "page": index + 1},
             excerpt=text, score=0.01) for index, text in enumerate(sources)]
    retriever = MagicMock()
    retriever.retrieve.return_value = items
    retriever.still_authorized.return_value = True
    chat = MagicMock()
    chat.generate.return_value = ChatResult(sufficient, claims)
    response = EvidenceAnswerer(Settings(ai_enabled=True), retriever, chat).ask(
        MagicMock(), MagicMock(), AskRequest(query="What does this guide require?"))
    return response, chat


def test_only_source_used_by_claim_becomes_a_citation() -> None:
    result, _ = answer([SupportedClaim("P1", "S1")],
                       ["Keys rotate every 30 days. Request seven-day approval.", "Keys are issued by the broker."])
    assert not result.insufficient_evidence
    assert [c.label for c in result.citations] == ["S1"]
    assert result.answer == '“Keys rotate every 30 days.” [S1]'


@pytest.mark.parametrize("claim,sources", [
    (SupportedClaim("P2", "S2"), ["Keys rotate every 30 days. Request approval.", "Unrelated issuer data."]),
    (SupportedClaim("Preparation; detection and analysis; containment, eradication and recovery", "S1"),
     ["Computer Security Incident Handling Guide. NIST SP 800-61 Revision 2. August 2012."]),
    (SupportedClaim("NIST does not mandate an exact SIEM product or version.", "S1"),
     ["The organization should monitor networks. Tools can assist detection."]),
    (SupportedClaim("Supplemented uses only internal resources.", "S1"),
     ["Supplemented: Time to recovery is predictable with additional resources."]),
    (SupportedClaim("P1", ""), ["Keys rotate every 30 days."]),
    (SupportedClaim("P1", "S999"), ["Keys rotate every 30 days."]),
    (SupportedClaim("P999", "S1"), ["Keys rotate every 30 days."]),
])
def test_missing_support_memory_global_negative_and_forged_passages_fail_closed(claim, sources) -> None:
    result, _ = answer([claim], sources)
    assert result.insufficient_evidence and not result.citations


def test_explicit_source_negative_is_returned_from_original_source() -> None:
    result, _ = answer([SupportedClaim("P1", "S1")], ["This module does not support\nwriting TOML."])
    assert not result.insufficient_evidence and len(result.citations) == 1
    assert 'does not support writing TOML' in result.answer


def test_model_sufficiency_and_empty_claims_fail_closed() -> None:
    for sufficient, claims in [(False, [SupportedClaim("P1", "S1")]), (True, [])]:
        result, _ = answer(claims, ["Source fact"], sufficient)
        assert result.insufficient_evidence and not result.citations


def test_every_claim_checked_and_no_free_form_tail_can_escape() -> None:
    result, _ = answer([SupportedClaim("P1", "S1"), SupportedClaim("Unsupported tail", "S1")], ["Source fact"])
    assert result.insufficient_evidence and not result.citations


def test_claims_keep_distinct_server_mapped_sources_and_no_duplicate_citations() -> None:
    result, chat = answer([SupportedClaim("P1", "S1"), SupportedClaim("P1", "S2"), SupportedClaim("P1", "S2")],
                          ["Passwords: 90 days", "Keys: 30 days"])
    assert [c.label for c in result.citations] == ["S1", "S2"]
    assert result.answer.count("Keys: 30 days") == 1
    prompt = json.loads(chat.generate.call_args.args[1])
    assert prompt["evidence"][0]["passages"] == [{"id": "P1", "text": "Passwords: 90 days"}]
    assert 'text' not in prompt['evidence'][0]


def test_pdf_passage_selection_preserves_words_tables_and_locator_representation() -> None:
    text = 'Header\nTable 3-4\nSupplemented | predictable with additional resources\nExtended | outside help. Next body sentence.'
    tokens = TokenCounter()
    passages = source_passages(text, tokens)
    assert passages == source_passages(text, tokens)
    assert 'Supplemented | predictable' in passages['P1']
    assert all(p in text and tokens.count(p) <= 160 for p in passages.values())
    result, _ = answer([SupportedClaim('P1', 'S1')], [text])
    assert 'Supplemented | predictable' in result.answer
    assert result.citations[0].source_locator == {'kind': 'pdf', 'page': 1}


def test_long_passages_keep_exact_contiguous_unicode_source_slices() -> None:
    text = 'café 東京 whitespace cha rge ' * 100
    tokens = TokenCounter()
    passages = source_passages(text, tokens)
    assert len(passages) > 1
    assert all(p in text and tokens.count(p) <= 160 for p in passages.values())
