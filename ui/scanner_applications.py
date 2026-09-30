"""Compact per-vehicle technical application view, without inferred support."""

import streamlit as st

FIELDS = {
    "application_introduced_version": "Versão de introdução da aplicação",
    "test_type": "Tipo de teste",
    "new_system": "Novo sistema",
    "video": "Vídeo",
    "fipe": "FIPE",
    "immobilizer": "Imobilizador",
    "advanced_functions": "Funções avançadas",
    "scooter": "Scooter",
    "release": "Lançamento (legado)",
    "situation": "Situação declarada (legado)",
    "date": "Data (legado)",
    "cable_location": "Localização do cabo",
}


def technical_rows(items):
    return [
        {
            "Sistema": r["system"],
            "Cabo": r.get("cable") or "Não informado",
            **{
                FIELDS.get(k, k): v or "Não informado"
                for k, v in r.get("attributes", r.get("raw_fields", {})).items()
                if k in FIELDS
            },
        }
        for r in items
    ]


def applications_detail(service, key):
    items = service.scanner_applications(key)
    st.subheader("Aplicações do veículo")
    st.caption(
        "Valores declarados pela fonte. Versão de introdução pertence à aplicação e não à publicação. Valores diferentes de SIM/NÃO permanecem exibidos como fornecidos."
    )
    if not items:
        st.info("Nenhuma aplicação detalhada nesta versão.")
        return
    page = st.number_input(
        "Página de aplicações",
        min_value=1,
        max_value=max(1, (len(items) + 29) // 30),
        value=1,
        key="applications_" + key,
    )
    st.caption(f"{len(items)} registros preservados, incluindo repetições sinalizadas na importação.")
    st.dataframe(technical_rows(items[(page - 1) * 30 : page * 30]), hide_index=True, width="stretch")
