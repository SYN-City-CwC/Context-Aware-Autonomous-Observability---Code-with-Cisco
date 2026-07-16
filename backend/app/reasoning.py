from __future__ import annotations

import json
import logging
import os

import httpx
from dotenv import load_dotenv

from app.models import RcaRecord


load_dotenv()
logger = logging.getLogger(__name__)


class ReasoningProvider:
    def narrate(self, rca: RcaRecord) -> tuple[str, str]:
        prompt = "Write a terse SRE incident narrative strictly from this evidence. Do not invent facts. " + json.dumps(rca.model_dump(mode="json"))
        for name, url, headers, payload, extractor in _providers(prompt):
            try:
                if not headers:
                    raise RuntimeError("missing key")
                response = httpx.post(url, headers=headers, json=payload, timeout=10.0)
                response.raise_for_status()
                text = extractor(response.json())
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("malformed response")
                return text.strip(), name
            except Exception as error:
                logger.info("reasoning fallback: %s unavailable (%s)", name, type(error).__name__)
        return " ".join(rca.evidence_chain), "rules"


def _providers(prompt: str):
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    return [
        ("groq", "https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"} if groq_key else {}, {"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": "Use only supplied evidence."}, {"role": "user", "content": prompt}]}, lambda body: body["choices"][0]["message"]["content"]),
        ("gemini", f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}", {"Content-Type": "application/json"} if gemini_key else {}, {"contents": [{"parts": [{"text": prompt}]}]}, lambda body: body["candidates"][0]["content"]["parts"][0]["text"]),
    ]


_CACHE: dict[str, tuple[str, str]] = {}


def narrate_records(records: list[RcaRecord]) -> list[RcaRecord]:
    provider = ReasoningProvider()
    for record in records:
        narrative, used = _CACHE.setdefault(record.incident_id, provider.narrate(record))
        record.narrative, record.narrative_provider = narrative, used
    return records
