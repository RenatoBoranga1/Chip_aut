"""Assisted operations inside Parceiros; the assistant only navigates here."""

import hashlib

import streamlit as st

from database.inbox_repository import read_inbox, read_inbox_errors
from database.inventory_repository import read_operations
from partners.integration import integration
from services.partner_health_service import partner_health, refresh_health
from services.partner_inbox_service import PartnerInboxService
from services.partner_operations_config import INBOX_ENV
from ui.partner_operations import NAMES

STATUSES = {
    "DETECTED": "Detectado",
    "VALIDATING": "Validando",
    "READY_FOR_REVIEW": "Arquivo aguardando confirmação",
    "INVALID": "Inválido",
    "DUPLICATE": "Duplicado",
    "IMPORTED": "Importado",
    "REJECTED": "Rejeitado",
}
DIFF = {"new": "Novos", "changed": "Alterados", "kept": "Mantidos", "absent": "Ausentes", "invalid": "Inválidos"}


def health_panel(database):
    data = partner_health(database)
    st.subheader("Saúde dos parceiros")
    st.table(
        [
            {
                "Parceiro": r["name"],
                "Saúde": r["health"],
                "Última atualização": r["last_update"] or "Sem atualização registrada",
                "Dias desde atualização": r["days"],
                "Arquivos aguardando confirmação": r["waiting"],
                "Arquivos inválidos": r["invalid"],
                "Triagem pendente": r["pending_triage"],
            }
            for r in data["partners"]
        ]
    )
    e = data["efficiency"]
    st.caption(
        f"Triagens evitadas por memória: {e['reused']} de {e['observed']} observações · Taxa de reaproveitamento: {e['reuse_percent']}%. Decisões humanas anteriores, sem IA."
    )
    return data


def inbox_panel(dashboard):
    service = PartnerInboxService(dashboard.config.database, read_only=dashboard.config.read_only)
    st.subheader("Arquivos aguardando análise")
    st.caption(
        "A leitura prepara a revisão. A publicação exige confirmação humana. Pastas são configuradas pelo ambiente; arquivos do usuário são preservados."
    )
    if st.button("Verificar pastas de entrada", disabled=dashboard.config.read_only):
        try:
            result = service.scan()
            for key, row in result.items():
                st.info(
                    integration(key).display_name
                    + ": "
                    + (
                        "Pasta não configurada"
                        if row["status"] == "NOT_CONFIGURED"
                        else "Pasta indisponível"
                        if row["status"] == "UNAVAILABLE"
                        else f"{row['detected']} novos arquivos; {row['skipped']} já conhecidos; {row['unreadable']} indisponíveis."
                    )
                )
        except (ValueError, OSError, RuntimeError) as exc:
            st.error(str(exc))
    if st.button("Atualizar saúde e pendências", disabled=dashboard.config.read_only):
        refresh_health(dashboard.config.database)
        st.rerun()
    for partner in INBOX_ENV:
        with st.expander(integration(partner).display_name + " — Caixa de entrada"):
            errors = read_inbox_errors(dashboard.config.database, partner)
            if errors:
                st.warning("Arquivos que não puderam ser lidos:")
                st.table([{"Arquivo": e["filename"], "Problema": e["error"], "Data": e["updated_at"]} for e in errors])
            rows = read_inbox(dashboard.config.database, partner)
            if not rows:
                st.info("Nenhum arquivo detectado nesta inbox.")
                continue
            st.dataframe(
                [
                    {
                        "Referência": r["id"],
                        "Arquivo": r["filename"],
                        "Detectado em": r["detected_at"],
                        "Situação": STATUSES[r["status"]],
                        "Linhas": r["preview"].get("total_rows"),
                        "Alertas": len(r["preview"].get("anomalies", [])),
                    }
                    for r in rows
                ],
                hide_index=True,
            )
            identifier = st.selectbox(
                "Arquivo para revisão",
                [r["id"] for r in rows],
                format_func={r["id"]: f"#{r['id']} · {r['filename']} · {STATUSES[r['status']]}" for r in rows}.get,
                key="inbox_select_" + partner,
            )
            row = next(r for r in rows if r["id"] == identifier)
            review_file(dashboard, service, row)
    with st.expander("Histórico operacional assistido"):
        labels = {
            "FILE_DETECTED": "Arquivo detectado",
            "FILE_VALIDATED": "Arquivo validado",
            "FILE_CONFIRMED": "Importação confirmada",
            "FILE_REJECTED": "Arquivo rejeitado",
            "TRIAGE_CREATED": "Triagem criada",
            "TRIAGE_RESOLVED": "Triagem resolvida",
            "STALE_WARNING": "Aviso de desatualização",
            "STAGING_COLLECTED": "Coleta para triagem concluída",
        }
        st.dataframe(
            [
                {
                    "Parceiro": integration(e["partner"]).display_name,
                    "Evento": labels[e["action"]],
                    "Data": e["created_at"],
                    "Origem": "Preparação automática" if e["reviewer"] == "sistema" else "Confirmação humana",
                    "Responsável": e["reviewer"],
                    "Resultado": e["detail_json"],
                }
                for e in read_operations(dashboard.config.database)["events"]
                if e["action"] in labels
            ],
            hide_index=True,
        )


def review_file(dashboard, service, row):
    st.write(f"Parceiro: {integration(row['partner']).display_name} · Arquivo: {row['filename']}")
    st.text("Hash: " + row["file_hash"])
    st.caption("Detectado em " + row["detected_at"])
    if row["error"]:
        st.error(row["error"])
    if row["status"] in {"IMPORTED", "REJECTED", "DUPLICATE"}:
        st.info(STATUSES[row["status"]] + ". Nenhuma publicação automática.")
        return
    token = f"inbox_{row['id']}_{row['revision']}"
    with st.form(token + "_review"):
        mode = st.selectbox(
            "Modo da revisão",
            ["INCREMENTAL", "FULL_SNAPSHOT"],
            index=int(row["mode"] == "FULL_SNAPSHOT"),
            format_func=lambda v: "Incremental" if v == "INCREMENTAL" else "Retrato completo",
            key=token + "mode",
        )
        with st.expander("Ajustar mapeamento", expanded=False):
            mapping = {k: st.text_input(label, row["mapping"].get(k, ""), key=token + k) for k, label in NAMES.items()}
        if st.form_submit_button("Validar arquivo e atualizar prévia", disabled=dashboard.config.read_only):
            try:
                service.validate(row["id"], mode=mode, mapping=mapping or None, expected_revision=row["revision"])
                st.rerun()
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(str(exc))
        preview = row["preview"]
        preview_current = mode == row["mode"] and all(mapping.get(k, "") == row["mapping"].get(k, "") for k in NAMES)
        if not preview_current:
            st.info("Modo ou mapeamento mudou. Valide novamente para habilitar a confirmação.")
        if preview:
            st.write("Prévia preparada · " + ("Incremental" if row["mode"] == "INCREMENTAL" else "Retrato completo"))
            st.table(
                [
                    {"Métrica": label, "Quantidade": preview.get(key, 0)}
                    for key, label in {
                        "total_rows": "Linhas",
                        "valid_rows": "Válidas",
                        "invalid_rows": "Inválidas",
                        "duplicates": "Duplicadas",
                        "missing_manufacturer": "Sem fabricante",
                        "missing_model": "Sem modelo",
                        "missing_year": "Sem ano",
                        "missing_id": "Sem ID",
                    }.items()
                ]
            )
            st.subheader("Comparação com estoque válido anterior")
            st.table(
                [
                    {"Situação": DIFF[k], "Quantidade": len(v) if isinstance(v, list) else v}
                    for k, v in preview["comparison"].items()
                ]
            )
            st.dataframe(
                [
                    {
                        "Linha": r["line"],
                        **{NAMES[k]: v for k, v in r["data"].items()},
                        "Problemas": "; ".join(r["errors"]),
                    }
                    for r in preview["preview"]
                ],
                hide_index=True,
            )
            for anomaly in preview["anomalies"]:
                (
                    st.error
                    if anomaly["level"] == "BLOQUEIO"
                    else st.warning
                    if anomaly["level"] == "ATENÇÃO"
                    else st.info
                )(anomaly["level"] + ": " + anomaly["message"])
        reviewer = st.text_input("Responsável pela revisão do arquivo", key=token + "reviewer")
        authorized = st.checkbox("Confirmo origem autorizada e unidade correta", key=token + "authorized")
        motorcycles = st.checkbox("Conferi as motocicletas e o modo de importação", key=token + "motorcycles")
        anomalies = st.checkbox("Conferi as anomalias e os possíveis ausentes", key=token + "anomalies")
        if row["mode"] == "FULL_SNAPSHOT":
            st.warning("A confirmação do retrato completo retira anúncios ausentes do estoque ativo.")
        if st.form_submit_button(
            "Confirmar importação da inbox",
            disabled=dashboard.config.read_only or not preview_current or row["status"] != "READY_FOR_REVIEW",
        ):
            try:
                service.confirm(
                    row["id"],
                    expected_revision=row["revision"],
                    preview_hash=row["preview_hash"],
                    reviewer=reviewer,
                    confirmed=True,
                    authorized=authorized,
                    motorcycles_confirmed=motorcycles,
                    accept_anomalies=anomalies,
                )
                st.success("Arquivo confirmado e importado com matching. Atualize a página para consultar o histórico.")
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(str(exc))
        reason = st.text_input("Motivo da rejeição", key=token + "reason")
        reject = st.checkbox("Confirmo a rejeição deste arquivo", key=token + "reject_ack")
        if st.form_submit_button(
            "Rejeitar arquivo",
            disabled=dashboard.config.read_only,
        ):
            try:
                service.reject(
                    row["id"], expected_revision=row["revision"], reviewer=reviewer, reason=reason, confirmed=reject
                )
                st.success("Rejeição registrada. Arquivo preservado na pasta.")
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(str(exc))


def batch_triage(dashboard, rows):
    from services.motonil_staging_service import MotonilStagingService

    st.subheader("Triagem em lote")
    show_all = st.checkbox("Incluir itens já classificados para reclassificação", key="batch_triage_known")
    choices = {
        r["external_id"]: r for r in rows if show_all or r["classification"] in {"PENDING_CLASSIFICATION", "UNKNOWN"}
    }
    selected = st.multiselect(
        "Itens do lote Motonil", list(choices), format_func=lambda k: choices[k]["payload"]["title"], max_selections=100
    )
    if not selected:
        st.caption("Selecione itens pendentes para preparar um lote.")
        return
    key = hashlib.sha256(str([(i, choices[i]["revision"]) for i in selected]).encode()).hexdigest()[:16]
    with st.form("motonil_batch_" + key):
        classification = st.selectbox(
            "Classificação do lote",
            ["MOTORCYCLE", "KART", "SERVICE", "OTHER"],
            format_func=lambda c: {"MOTORCYCLE": "Moto", "KART": "Kart", "SERVICE": "Serviço", "OTHER": "Outro"}[c],
        )
        selections = []
        for identifier in selected:
            row = choices[identifier]
            st.write(row["payload"]["title"])
            identity = {
                field: st.text_input(NAMES[field] + " · " + identifier, str(row["identity"].get(field) or ""))
                for field in ("manufacturer", "model", "year", "version")
            }
            selections.append(
                {"partner": "motonil", "external_id": identifier, "revision": row["revision"], "identity": identity}
            )
        reviewer = st.text_input("Responsável pelo lote")
        note = st.text_input("Motivo do lote (opcional)")
        confirmed = st.checkbox("Conferi todos os itens e confirmo a classificação do lote")
        if st.form_submit_button("Aplicar classificação ao lote", disabled=dashboard.config.read_only):
            try:
                result = MotonilStagingService(
                    dashboard.config.database, read_only=dashboard.config.read_only
                ).classify_batch(selections, classification, reviewer=reviewer, note=note, confirmed=confirmed)
                st.success(
                    f"{result['classified']} itens classificados. Atualize para consultar as pendências restantes."
                )
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(str(exc))
