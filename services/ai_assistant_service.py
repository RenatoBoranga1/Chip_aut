"""Read-only orchestration. No tools, arbitrary SQL, command callbacks or provider state."""

import json
import logging
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from services.ai_context_service import identify_intent, remember
from services.ai_guardrails import (
    INSUFFICIENT,
    NOT_CONFIGURED,
    READ_ONLY,
    UNAVAILABLE,
    blocked,
    redact,
    validate_order,
)
from services.ai_provider import configured_provider, load_config
from services.ai_query_service import AIQueryService

AUDIT = logging.getLogger("ai_assistant.audit")
AUDIT.propagate = False


def audit_event(metadata):
    """Fixed local metadata sink, outside the operational DB; bounded rotation, no responses."""
    if not AUDIT.handlers:
        directory = Path(__file__).parents[1] / "logs"
        directory.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            directory / "ai_assistant.jsonl", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        AUDIT.addHandler(handler)
        AUDIT.setLevel(logging.INFO)
    AUDIT.info(json.dumps(metadata, ensure_ascii=False))


class AIAssistantService:
    def __init__(self, database, partner="wr_motos", config=None, provider=None, clock=None, audit_sink=None):
        self.config = config or load_config()
        self._provider = provider if self.config.enabled and provider is not None else configured_provider(self.config)
        self._query = AIQueryService(database, partner, clock)
        self._scope = (str(Path(database).resolve()), partner)
        self._audit = audit_sink or audit_event

    @property
    def configured(self):
        return self._provider is not None

    def model_info(self):
        return self._provider.get_model_info() if self._provider else {"provider": None, "model": None}

    def ask(self, question, state):
        started = time.perf_counter()
        if state.get("scope") != self._scope:
            state.update(messages=[], selected_vehicle_id=None, selected_base_id=None, choices=[], scope=self._scope)
        answer = {
            "text": "",
            "facts": [],
            "sources": [],
            "choices": [],
            "route": None,
            "total": 0,
            "intent": "UNKNOWN",
            "success": False,
            "timings": {},
            "model": self.model_info(),
        }
        clean = redact(question)
        try:
            if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                answer["text"] = "Informe uma pergunta de até 2.000 caracteres."
            elif blocked(question):
                answer["text"] = READ_ONLY
                answer["intent"] = "BLOCKED"
            elif not self.configured:
                answer["text"] = NOT_CONFIGURED
            else:
                mark = time.perf_counter()
                intent = identify_intent(clean)
                answer["intent"] = intent
                answer["timings"]["intent"] = time.perf_counter() - mark
                mark = time.perf_counter()
                result = self._query.query(
                    intent, clean, state, min(self.config.max_context_records, self.config.max_response_rows)
                )
                answer["timings"]["query"] = time.perf_counter() - mark
                mark = time.perf_counter()
                facts = result["facts"][: self.config.max_context_records]
                # Bound serialized context as well as row count. Never include raw DB/paths/logs.
                while facts and len(json.dumps(facts, ensure_ascii=False).encode("utf-8")) > 24_000:
                    facts.pop()
                context = {
                    "question": clean,
                    "intent": intent,
                    "facts": facts,
                    "period": result.get("period"),
                    "history": [
                        {"role": "user", "text": m["text"]}
                        for m in state["messages"][-self.config.max_history_messages :]
                        if m["role"] == "user"
                    ],
                }
                answer["timings"]["context"] = time.perf_counter() - mark
                mark = time.perf_counter()
                ordered = validate_order(self._provider.generate(context), facts) if facts else []
                answer["timings"]["provider"] = time.perf_counter() - mark
                answer.update(
                    facts=ordered,
                    sources=[f["source"] for f in ordered],
                    choices=result["choices"],
                    route=result["route"],
                    total=result["total"],
                    period=result.get("period"),
                    text=result.get("message", "Consulta concluída com os dados registrados."),
                    count_label=result.get("count_label", "registros"),
                    displayed=sum(f["source"]["type"] == "scanner_application" for f in facts)
                    if result.get("count_label") == "aplicações"
                    else len(facts),
                    success=True,
                )
                if len(facts) < len(result["facts"]):
                    answer["text"] += " Contexto reduzido pelo limite de tamanho; consulte a tela de origem."
                    answer["displayed"] = min(answer["displayed"], len(facts))
                if intent == "UNKNOWN":
                    answer["text"] = INSUFFICIENT
        except Exception:
            # Never return provider errors, request headers, raw source data or local paths.
            answer.update(text=UNAVAILABLE, facts=[], sources=[], choices=[], route=None, success=False)
        answer["timings"]["total"] = time.perf_counter() - started
        if self.config.audit_enabled:
            try:
                self._audit(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "question": clean,
                        "intent": answer["intent"],
                        "source_types": sorted({s["type"] for s in answer["sources"]}),
                        "provider": redact(answer["model"].get("provider") or ""),
                        "model": redact(answer["model"].get("model") or ""),
                        "duration_seconds": answer["timings"]["total"],
                        "success": answer["success"],
                    }
                )
            except Exception:
                answer["audit_warning"] = "Não foi possível registrar os metadados de auditoria."
        remember(state, clean, answer, self.config)
        return answer
