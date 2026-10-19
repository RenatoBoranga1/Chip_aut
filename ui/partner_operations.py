"""Partner operation controls stay inside Parceiros; no new sidebar pages."""

import hashlib

import streamlit as st

from database.inventory_repository import read_operations
from partners.integration import integration
from services.motonil_staging_service import MotonilStagingService
from services.partner_inventory_import import (
    FIELDS,
    PartnerInventoryImportService,
    default_mapping,
    read_file,
    template_csv,
)

NAMES = {
    "external_id": "Código de estoque",
    "manufacturer": "Marca",
    "model": "Modelo",
    "version": "Versão",
    "year": "Ano",
    "price": "Preço",
    "mileage": "Quilometragem",
    "detail_url": "URL do anúncio",
    "image_url": "URL da imagem",
}
STATUS = {
    "ATIVO_AUTOMATICO": "Ativo automático",
    "ATIVO_MANUAL": "Ativo manual",
    "ATIVO_COM_TRIAGEM": "Ativo com triagem",
}
MODE_NAMES = {
    "PUBLIC_COLLECTION": "Coleta pública",
    "AUTHENTICATED_COLLECTION": "Coleta autenticada",
    "FILE_IMPORT": "Importação de arquivo",
    "STAGED_COLLECTION": "Coleta para triagem",
}
CLASS_NAMES = {
    "PENDING_CLASSIFICATION": "Aguardando classificação",
    "MOTORCYCLE": "Moto",
    "KART": "Kart",
    "SERVICE": "Serviço",
    "OTHER": "Outro",
    "UNKNOWN": "Indefinido",
}
ALERT_NAMES = {
    "IMPORT_PENDING": "Aguardando primeiro arquivo",
    "IMPORT_FAILED": "Importação não concluída",
    "IMPORT_INVALID_ROWS": "Arquivo com linhas inválidas",
    "TRIAGE_PENDING": "Itens aguardando triagem",
    "AUTH_REQUIRED": "Aguardando credencial autorizada",
    "AUTH_FAILED": "Credencial inválida ou expirada",
    "SOURCE_UNAVAILABLE": "Fonte indisponível",
    "SOURCE_STRUCTURE_CHANGED": "Estrutura da fonte mudou",
}


def integration_presentation(partner):
    entry = integration(partner)
    return {
        "Operacional": "Sim" if entry.enabled else "Não",
        "Automação": "Semiautomática" if entry.requires_human_triage else "Sim" if entry.automation_enabled else "Não",
        "Integração": MODE_NAMES[entry.integration_mode],
    }


def operational_metrics(database):
    st.subheader("Integrações operacionais")
    values = read_operations(database)["metrics"]
    labels = {
        "operational": "Parceiros operacionais",
        "automatic": "Automáticos",
        "manual": "Manuais",
        "with_triage": "Com triagem",
        "imports": "Importações realizadas",
        "pending_triage": "Aguardando triagem",
        "accepted": "Confirmados como moto",
        "discarded": "Descartados como kart/serviço",
    }
    st.table([{"Indicador": labels[k], "Quantidade": v} for k, v in values.items()])


def operational_alerts(database):
    data = read_operations(database)
    rows = [
        {
            "Parceiro": integration(a["partner"]).display_name,
            "Aviso": ALERT_NAMES.get(a["code"], a["code"]),
            "Última ocorrência": a["last_seen"],
        }
        for a in data["alerts"]
    ]
    for p in data["partners"]:
        if p["supports_manual_import"] and not p["last_import"]:
            rows.append(
                {
                    "Parceiro": p["display_name"],
                    "Aviso": ALERT_NAMES["IMPORT_PENDING"],
                    "Última ocorrência": "Ainda não importado",
                }
            )
    if rows:
        st.subheader("Pendências das integrações")
        st.table(rows)


def import_panel(service, partner, data):
    importer = PartnerInventoryImportService(service.config.database, read_only=service.config.read_only)
    st.download_button(
        "Baixar modelo de arquivo",
        template_csv(),
        file_name=f"modelo_{partner}.csv",
        mime="text/csv",
        key=f"template_{partner}",
    )
    st.caption(
        "Arquivo autorizado contendo somente motocicletas. Marca, modelo e ano obrigatórios. Prefira código de estoque; IDs de linha só são estáveis no mesmo arquivo."
    )
    uploaded = st.file_uploader("Selecionar arquivo CSV ou XLSX", type=["csv", "xlsx"], key=f"upload_{partner}")
    if uploaded is None:
        return
    content = uploaded.getvalue()
    try:
        headers, _ = read_file(content, uploaded.name)
        suggested = {**default_mapping(headers), **data["mappings"].get(partner, {})}
        mapping = {}
        with st.expander("Mapear colunas", expanded=True):
            for field in FIELDS:
                options = ["", *headers]
                default = suggested.get(field, "")
                mapping[field] = st.selectbox(
                    NAMES[field],
                    options,
                    index=options.index(default) if default in options else 0,
                    key=f"map_{partner}_{field}_{hashlib.sha256(content).hexdigest()[:12]}",
                )
        mode = st.selectbox(
            "Abrangência do arquivo",
            ["INCREMENTAL", "FULL_SNAPSHOT"],
            format_func=lambda x: (
                "Incremental — preservar anúncios ausentes"
                if x == "INCREMENTAL"
                else "Retrato completo — retirar anúncios ausentes"
            ),
            key=f"mode_{partner}",
        )
        stamp = (hashlib.sha256(content).hexdigest(), tuple(sorted(mapping.items())), mode)
        if st.button("Validar e pré-visualizar", key=f"preview_{partner}"):
            st.session_state[f"preview_{partner}_stamp"] = stamp
        if st.session_state.get(f"preview_{partner}_stamp") != stamp:
            return
        preview = importer.preview(partner, content, uploaded.name, mapping=mapping, mode=mode)
        labels = {
            "total_rows": "Total de linhas",
            "valid_rows": "Válidas",
            "invalid_rows": "Inválidas",
            "duplicates": "Duplicadas",
            "missing_id": "Sem código",
            "missing_year": "Sem ano válido",
            "missing_model": "Sem modelo",
        }
        st.table([{"Métrica": label, "Quantidade": preview[key]} for key, label in labels.items()])
        st.dataframe(
            [
                {"Linha": r["line"], **{NAMES[k]: v for k, v in r["data"].items()}, "Problemas": "; ".join(r["errors"])}
                for r in preview["preview"]
            ],
            hide_index=True,
        )
        reviewer = st.text_input("Responsável pela importação", key=f"reviewer_{partner}")
        authorized = st.checkbox(
            "Confirmo a origem autorizada e a unidade correta do parceiro", key=f"authorized_{partner}"
        )
        motorcycles = st.checkbox(
            "Conferi que as linhas válidas representam motocicletas", key=f"motorcycles_{partner}"
        )
        if mode == "FULL_SNAPSHOT":
            st.warning(
                "Confirmar este retrato completo retira do estoque os anúncios ausentes. Linhas inválidas impedem a operação."
            )
        if st.button(
            "Confirmar importação",
            key=f"confirm_{partner}",
            disabled=service.config.read_only or not authorized or not motorcycles or not reviewer.strip(),
        ):
            result = importer.confirm(
                partner,
                content,
                uploaded.name,
                mapping=mapping,
                mode=mode,
                reviewer=reviewer,
                confirmed=True,
                authorized=authorized,
                motorcycles_confirmed=motorcycles,
            )
            st.success(
                "Arquivo já importado; nenhuma duplicação."
                if result["reused"]
                else f"Importação #{result['id']} concluída com matching e revisão."
            )
    except (ValueError, OSError) as exc:
        st.error(str(exc))


def triage_panel(service, data):
    staging = MotonilStagingService(service.config.database, read_only=service.config.read_only)
    st.caption(
        "Coleta pública limitada até triagem. Tipo, marca, modelo e ano são confirmados por uma pessoa. Nenhum item indefinido segue automaticamente ao matching."
    )
    if st.button("Coletar Motonil para triagem", disabled=service.config.read_only):
        try:
            result = staging.collect()
            st.success(f"{result['staged']} itens observados em staging.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    rows = data["staging"]
    if not rows:
        st.info("Nenhum item em staging. Use a coleta permitida para iniciar.")
        return
    row = st.selectbox(
        "Item para classificar",
        rows,
        format_func=lambda r: f"{r['external_id']} · {r['payload']['title']} · {CLASS_NAMES[r['classification']]}",
    )
    payload = row["payload"]
    st.write("Título original: " + str(payload["title"]))
    st.write("Categoria original: " + str(payload["source_category"]))
    st.write(f"Primeira aparição: {row['first_seen']} · Última aparição: {row['last_seen']}")
    st.link_button("Abrir anúncio para conferir", payload["source_url"])
    with st.form("triage_" + row["external_id"] + "_" + str(row["revision"])):
        classification = st.selectbox(
            "Classificação humana",
            ["UNKNOWN", "MOTORCYCLE", "KART", "SERVICE", "OTHER"],
            format_func=lambda c: CLASS_NAMES[c],
        )
        identity = {
            k: st.text_input(NAMES[k], value=str(row["identity"].get(k) or ""))
            for k in ("manufacturer", "model", "year", "version")
        }
        reviewer = st.text_input("Responsável pela classificação")
        note = st.text_area("Justificativa da classificação")
        if st.form_submit_button("Confirmar classificação", disabled=service.config.read_only):
            try:
                staging.classify(
                    row["external_id"],
                    classification,
                    reviewer=reviewer,
                    note=note,
                    expected_revision=row["revision"],
                    identity=identity,
                )
                st.success("Classificação registrada. Somente Moto entra no matching.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def operations_page(service):
    data = read_operations(service.config.database)
    st.subheader("Operação dos parceiros — arquivos e triagem")
    st.table(
        [
            {
                "Parceiro": p["display_name"],
                "Situação": STATUS[p["status"]],
                "Modo": MODE_NAMES[p["integration_mode"]],
                "Automação": integration_presentation(p["partner_key"])["Automação"],
                "Anúncios ativos": p["active_ads"],
                "Última importação": p["last_import"] or "Nenhuma",
                "Triagem pendente": p["pending_triage"],
            }
            for p in data["partners"]
        ]
    )
    if service.config.read_only:
        st.info("Somente leitura: pré-visualização disponível; importação e triagem desabilitadas.")
    for partner in ("thomas_motos", "moto_marques"):
        with st.expander(integration(partner).display_name + " — Importar estoque"):
            if partner == "thomas_motos":
                st.caption(
                    "Sem credencial: importação manual disponível. Fonte AutoCerto autorizada pode ser configurada separadamente; nunca informe senha ou token nesta tela."
                )
            import_panel(service, partner, data)
    with st.expander("Triagem Motonil"):
        triage_panel(service, data)
    with st.expander("Histórico de importações e classificações"):
        st.dataframe(data["imports"], hide_index=True)
        st.dataframe(data["events"], hide_index=True)
    operational_alerts(service.config.database)
