"""Portuguese UI contracts: labels change, stored values do not."""

import copy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_dashboard import dashboard as dashboard_fixture

from ui.textos import ACTIONS, LABELS, cell, explanation, label, row_labels, validation_message, value


@pytest.fixture
def dashboard(tmp_path):
    return dashboard_fixture.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pending", "Pendente"),
        ("resolved", "Resolvido"),
        ("ignored", "Ignorado"),
        ("deferred", "Adiado"),
        ("invalidated", "Precisa de nova revisão"),
        ("reused", "Reaproveitado"),
        ("high", "Alta"),
        ("MEDIUM", "Média"),
        ("Low", "Baixa"),
        ("EXATO_NORMALIZADO", "Correspondência exata"),
        ("exact", "Correspondência exata"),
        ("CORRESPONDENCIA_PROVAVEL", "Correspondência provável"),
        ("review", "Revisar"),
        ("AMBIGUOUS", "Ambíguo"),
        ("NOT_FOUND", "Não encontrado na base"),
        ("CONFIRMADO_AUSENTE_NA_BASE", "Ausência confirmada na base atual"),
        ("EXATO_CONFIRMADO_HUMANAMENTE", "Correspondência confirmada pelo revisor"),
        ("SUPORTADO", "Suportado"),
        ("SEM_SUPORTE", "Sem suporte"),
        ("SUPORTE_PARCIAL", "Suporte parcial"),
        ("EM_ANALISE", "Em análise"),
        ("SEM_STATUS", "Situação não definida"),
        ("COMPLETE", "Concluída"),
        ("CACHED", "Dados temporários reutilizados"),
        ("FAILED", "Falhou"),
    ],
)
def test_labels_for_domain_values(raw, expected):
    assert value(raw) == expected


@pytest.mark.parametrize(
    "field",
    [
        "manufacturer",
        "state",
        "priority",
        "confidence",
        "reviewer",
        "before_state",
        "after_state",
        "first_seen",
        "last_seen",
        "external_id",
        "source_url",
        "scanner_key",
    ],
)
def test_known_headers(field):
    assert label(field) == LABELS[field] and label(field) != field


def test_unknown_translation_is_logged_and_safe(caplog):
    assert value("BRAND_NEW_STATUS") == "Informação ainda sem tradução"
    assert label("new_backend_field") == "Informação adicional"
    assert "BRAND_NEW_STATUS" in caplog.text and "new_backend_field" in caplog.text
    assert (
        validation_message("Internal failure")
        == "Não foi possível salvar. Atualize o item e confira os dados antes de tentar novamente."
    )


def test_presentation_does_not_change_source_or_identifiers():
    raw = {
        "state": "pending",
        "priority": "high",
        "model": "Street Triple",
        "scanner_key": "BMW|F900R|2025",
        "note": "original reviewer note",
        "components": {"token_sort": 93.5},
        "blockers": ["VERSAO_DIFERENTE_OU_INCOMPLETA"],
    }
    before = copy.deepcopy(raw)
    translated = row_labels(raw)
    assert raw == before
    assert translated["Modelo"] == "Street Triple"
    assert translated["Chave da base"] == "BMW|F900R|2025"
    assert translated["Justificativa"] == "original reviewer note"
    assert "token_sort" not in str(translated) and "VERSAO_DIFERENTE" not in str(translated)
    assert cell("year", 2025) == 2025


def test_generated_explanations_translate_technical_terms():
    result = explanation("Score final; token_sort; Tokens comuns; matching; VERSAO_DIFERENTE_OU_INCOMPLETA")
    for raw in ("Score", "token_sort", "Tokens", "matching", "VERSAO_DIFERENTE_OU_INCOMPLETA"):
        assert raw not in result
    assert "pontuação de similaridade" in result


def ui_for(service, monkeypatch):
    monkeypatch.setenv("MOTO_DB", str(service.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    return AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=20).run()


def visible(ui):
    texts = []
    for kind in ("title", "subheader", "caption", "markdown", "info", "warning", "error", "success"):
        texts.extend(str(e.value) for e in ui.get(kind))
    for kind in ("selectbox", "multiselect", "radio", "button", "text_input", "text_area"):
        for e in ui.get(kind):
            texts.append(e.label)
            if kind in ("selectbox", "multiselect", "radio"):
                texts.extend(e.options)
    for e in ui.table:
        texts.append(e.value.to_string(index=False))
    return "\n".join(texts)


def test_all_pages_display_portuguese_without_main_raw_enums(dashboard, monkeypatch):
    ui = ui_for(dashboard, monkeypatch)
    forbidden = (
        "pending",
        "resolved",
        "ignored",
        "deferred",
        "invalidated",
        "reused",
        "high",
        "medium",
        "EXATO_NORMALIZADO",
        "AMBIGUOUS",
        "SEM_STATUS",
        "SEM_SUPORTE",
        "SUPORTE_PARCIAL",
        "NAO_ENCONTRADA_NA_BASE",
        "CONFIRMAR_MATCH",
        "Reviewer",
        "Matching",
        "Score",
    )
    for page in ui.radio(key="navigation").options:
        ui.radio(key="navigation").set_value(page).run()
        if page == "Busca global":
            ui.text_input[0].set_value("BMW").run()
        if page == "Fila de revisão":
            ui.selectbox(key="review_selection").set_value(1).run()
        assert not ui.exception and not ui.error
        text = visible(ui)
        assert not [word for word in forbidden if word in text], (page, text)


def test_filters_show_portuguese_and_send_internal_values(dashboard, monkeypatch):
    ui = ui_for(dashboard, monkeypatch)
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    assert set(ui.multiselect(key="queue_priority").options) == {"Alta", "Média"}
    assert ui.multiselect(key="queue_state").options == ["Pendente"]
    ui.multiselect(key="queue_priority").set_value(["high"]).run()
    assert not ui.exception and not ui.error
    frame = ui.table[0].value
    assert "Prioridade" not in frame.columns  # Milestone 7.1: filter retained, main column hidden.
    high_ids = {str(r["id"]) for r in dashboard.snapshot()["queue"] if r["priority"] == "high"}
    assert set(frame["Revisão"]) == high_ids
    assert len(frame) == 3


@pytest.mark.parametrize("action", list(ACTIONS))
def test_translated_action_persists_original_contract(dashboard, monkeypatch, action):
    ui = ui_for(dashboard, monkeypatch)
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="review_selection").set_value(1).run()
    ui.selectbox(key="action_1").set_value(action)
    if ACTIONS[action] in {"CONFIRMAR_MATCH", "REJEITAR_CANDIDATO"}:
        ui.selectbox(key="candidate_1").set_value("BMW|F900R|2025")
    assert ui.text_input(key="reviewer_1").label == "Revisor"
    ui.text_input(key="reviewer_1").set_value("Revisor de teste")
    ui.text_area(key="note_1").set_value("Identidade conferida em base temporária")
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert not ui.exception and not ui.error and ui.success
    item = dashboard.detail(1)
    assert len(item["history"]) == 1
    assert item["history"][0]["action"] == ACTIONS[action]
    assert item["automatic"]["match_type"] == "AMBIGUOUS"
    assert "CONFIRMAR_MATCH" not in visible(ui)
    ui.run()
    assert len(dashboard.detail(1)["history"]) == 1


def test_validation_is_portuguese_and_does_not_save(dashboard, monkeypatch):
    ui = ui_for(dashboard, monkeypatch)
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="review_selection").set_value(1).run()
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert ui.error[0].value == "Informe a ação, o revisor e a justificativa."
    assert not dashboard.detail(1)["history"]
