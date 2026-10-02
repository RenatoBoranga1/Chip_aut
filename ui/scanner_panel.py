"""Scanner workflow presentation, with an explicit review/confirm step."""

import json

import streamlit as st

from services.scanner_service import ScannerService
from ui.navigation import request_navigation
from ui.scanner_applications import FIELDS
from ui.textos import value

STATUS = {
    "VALIDATED": "Validada — aguardando confirmação",
    "REJECTED": "Rejeitada",
    "PUBLISHED": "Publicada",
    "SUPERSEDED": "Substituída",
}
KINDS = {
    "APPLICATION_ADDED": "Aplicações adicionadas",
    "APPLICATION_REMOVED": "Aplicações removidas",
    "APPLICATION_CHANGED": "Atributos da aplicação alterados",
    "APPLICATION_CABLE_CHANGED": "Cabo da aplicação alterado",
    "ADDED": "Adicionadas",
    "REMOVED": "Removidas",
    "CHANGED": "Alteradas",
    "IDENTITY_REVIEW": "Identidades pendentes de revisão",
}
REASONS = {
    "VALID": "Correspondência preservada",
    "REVALIDATE": "Decisão vinculada à base anterior: revalidar",
    "TARGET_REMOVED": "Registro removido ou identidade alterada",
    "SUPPORT_CHANGED": "Identidade mantida; campos alterados precisam de conferência",
    "PENDING": "Dúvida mantida",
}


def display_table(rows):
    if rows:
        st.table(rows)
    else:
        st.caption("Nenhum registro nesta página.")


def motorcycle_label(moto):
    if not moto:
        return "Não consta"
    return f"{moto['manufacturer']} · {moto['model']} · {moto['year']} · {value(moto['status'])}"


def support_rows(items):
    labels = {
        **FIELDS,
        "system": "Sistema",
        "release": "Lançamento",
        "situation": "Situação",
        "date": "Data",
        "cable": "Cabo",
        "cable_location": "Localização do cabo",
    }
    return [
        {
            **{labels.get(k, k): v for k, v in json.loads(item)[0].items()},
            "Outros valores originais": ", ".join(json.loads(item)[1]),
        }
        for item in items
    ]


def application_label(items):
    if not items:
        return "Não consta"
    return " · ".join(f"{r['system']} / {r['cable'] or 'Cabo não informado'}" for r in items)


def scanner_page(dashboard):
    service = ScannerService(dashboard.config.database, dashboard.config.read_only)
    listing = service.list()
    current = listing["current"]
    st.caption("Prepare, compare e confirme. Enviar um arquivo não altera a base operacional.")
    st.info(f"Base operacional: importação {listing['active_import'] or 'não disponível'}")
    if current:
        st.caption("Identificador SHA-256 da base: " + current.get("sha256", current.get("source_sha256", "")))
    if listing["active_import"]:
        st.button("Consultar veículos da base ativa", on_click=request_navigation, args=("Base do scanner",))
    if not service.settings["enabled"]:
        st.warning("Atualização da base desabilitada pela configuração")
    disabled = dashboard.config.read_only or not service.settings["enabled"]
    with st.form("scanner_upload"):
        upload = st.file_uploader(
            "Nova planilha do scanner (.xlsx)",
            type=["xlsx"],
            disabled=disabled,
            max_upload_size=max(1, int(service.settings["max_upload_mb"])),
        )
        author = st.text_input("Responsável pela importação", max_chars=120)
        notes = st.text_area("Observações da importação", max_chars=4000)
        prepare = st.form_submit_button("Validar e comparar arquivo", disabled=disabled)
    if prepare:
        if upload is None:
            st.error("Selecione uma planilha .xlsx")
        else:
            try:
                with st.spinner("Validando a estrutura e comparando versões…"):
                    outcome = service.prepare(upload.getvalue(), upload.name, author, notes)
                st.session_state.scanner_selection = outcome["id"]
                st.session_state.scanner_message = (
                    "Arquivo já registrado; consulte a versão existente."
                    if outcome["duplicate"]
                    else "Arquivo validado e comparação preparada. A base operacional permanece a mesma."
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Não foi possível preparar o arquivo. Confira a estrutura e consulte o registro local.")
    if st.session_state.get("scanner_message"):
        st.success(st.session_state.scanner_message)
    st.subheader("Histórico de importações")
    page = st.number_input("Página do histórico de versões", min_value=1, value=1, step=1)
    if page > 1:
        listing = service.list(page - 1)
    display_table(
        [
            {
                "Versão": r["id"],
                "Arquivo": r["original_filename"],
                "Situação": STATUS[r["status"]],
                "Data": r["imported_at"],
                "Responsável": r["imported_by"],
                "Motos": r["unique_vehicles"],
            }
            for r in listing["versions"]
        ]
    )
    choices = [None, *[r["id"] for r in listing["versions"]]]
    requested = st.session_state.pop("scanner_selection", None)
    if requested and requested not in choices:
        choices.append(requested)
    if requested:
        st.session_state.scanner_version_choice = requested
    if st.session_state.get("scanner_version_choice") not in choices:
        st.session_state.scanner_version_choice = None
    selected = st.selectbox(
        "Consultar versão",
        choices,
        key="scanner_version_choice",
        format_func=lambda v: f"Versão {v}" if v else "Selecione uma versão",
    )
    if not selected:
        return
    item = service.detail(selected)
    st.subheader(f"Versão {selected} — {STATUS[item['status']]}")
    st.write("Arquivo: " + item["original_filename"])
    st.caption("SHA-256: " + item["sha256"])
    st.write("Responsável: " + item["imported_by"])
    st.write("Observações: " + (item["notes"] or "Não informadas"))
    report = item["report"]
    report = {"support_conflicts": report.get("conflicts", 0), **report}
    comparison = report.get("comparison", {})
    if item.get("diagnostics_recomputed"):
        st.caption(
            "Contadores de conflitos conferidos a partir dos avisos preservados; relatório histórico original mantido."
        )
    st.info("Formato detectado: " + report.get("format_label", "Formato legado — RESUMO MDL"))
    display_table(
        [
            {
                "Veículos identificados": report.get("unique_vehicles", item["unique_vehicles"]),
                "Linhas de aplicações": report.get("applications", item["valid_records"]),
                "Aplicações sem repetição exata": report.get("unique_applications", "Não apurado"),
                "Sistemas distintos": report.get("unique_systems", "Não apurado"),
            }
        ]
    )
    if report.get("format") == "APPLICATION_GENERAL":
        st.caption(
            "VERS. pertence à aplicação. A versão oficial é esta publicação; aplicações listadas não recebem suporte inferido. Linhas repetidas e variantes ficam preservadas."
        )
    technical = report.get("technical_comparison", {})
    if technical:
        apps = technical["applications"]
        display_table(
            [
                {"Aplicações (chaves veículo/sistema/cabo)": label, "Quantidade": apps[key]}
                for key, label in [
                    ("previous", "Base anterior"),
                    ("new", "Nova base"),
                    ("added", "Novas"),
                    ("removed", "Removidas"),
                    ("changed", "Alteradas"),
                    ("cable_changed", "Com troca de cabo"),
                    ("attributes_changed", "Com alteração de atributos"),
                    ("unchanged", "Mantidas"),
                ]
            ]
        )
        systems = technical["systems"]
        display_table(
            [
                {
                    "Sistemas anteriores": systems["previous"],
                    "Sistemas novos": systems["new"],
                    "Nomes adicionados": len(systems["added"]),
                    "Nomes removidos": len(systems["removed"]),
                }
            ]
        )
        with st.expander("Sistemas adicionados e removidos"):
            display_table(
                [
                    {"Alteração": kind, "Sistema": name}
                    for kind, names in (("Adicionado", systems["added"]), ("Removido", systems["removed"]))
                    for name in names
                ]
            )
    display_table(
        [
            {"Indicador": label, "Quantidade": report.get(key, item.get(key, 0))}
            for key, label in [
                ("total_records", "Registros identificados"),
                ("valid_records", "Registros válidos"),
                ("invalid_records", "Registros inválidos"),
                ("duplicates", "Duplicidades"),
                ("conflicts", "Conflitos"),
                ("application_conflicts", "Conflitos de atributos (chaves de aplicação)"),
                ("support_conflicts", "Conflitos de suporte"),
                ("invalid_dates", "Datas inválidas"),
            ]
        ]
    )
    if comparison:
        display_table(
            [
                {"Indicador": label, "Quantidade": comparison[key]}
                for key, label in [
                    ("previous", "Motos na versão anterior"),
                    ("new", "Motos na nova versão"),
                    ("added", "Adicionadas"),
                    ("removed", "Removidas"),
                    ("changed", "Alteradas"),
                    ("unchanged", "Sem alteração"),
                    ("identity_review", "Comparação pendente de revisão"),
                ]
            ]
        )
        st.caption(
            "Presença na base não confirma suporte. Códigos sem documentação não recebem significado novo. Versões permanecem no modelo completo conforme as regras atuais."
        )
    if report.get("conflicts"):
        st.warning(
            "Existem conflitos entre registros. Eles permanecem sinalizados; confira as diferenças e os registros antes de publicar."
        )
    if item["status"] == "REJECTED":
        st.error(
            "Corrija os registros inválidos ou datas inválidas e envie outro arquivo. Esta preparação não pode ser publicada."
        )
    detail_page = st.number_input("Página das diferenças e impactos", min_value=1, value=1, step=1)
    kind = st.selectbox("Tipo de diferença", [None, *KINDS], format_func=lambda k: KINDS[k] if k else "Todas")
    data = service.detail(selected, detail_page - 1, kind)
    st.caption(f"{data['differences_total']} diferenças; até 30 por página")
    display_table(
        [
            {
                "Tipo": KINDS[r["kind"]],
                "Identidade": r["identity_key"],
                "Antes": application_label(r["payload"].get("before_applications"))
                if r["kind"].startswith("APPLICATION_")
                else motorcycle_label(r["payload"].get("before")),
                "Depois": application_label(r["payload"].get("after_applications"))
                if r["kind"].startswith("APPLICATION_")
                else r["payload"].get("message") or motorcycle_label(r["payload"].get("after")),
            }
            for r in data["differences"]
        ]
    )
    chosen = st.selectbox(
        "Abrir detalhe da diferença",
        [None, *range(len(data["differences"]))],
        format_func=lambda n: (
            "Selecione uma diferença"
            if n is None
            else KINDS[data["differences"][n]["kind"]] + " · " + data["differences"][n]["identity_key"]
        ),
    )
    if chosen is not None:
        difference = data["differences"][chosen]["payload"]
        if "before_applications" in difference:
            from ui.scanner_applications import technical_rows

            st.write("Aplicações anteriores")
            display_table(technical_rows(difference["before_applications"]))
            st.write("Aplicações novas")
            display_table(technical_rows(difference["after_applications"]))
        st.write("Campos de suporte anteriores")
        display_table(support_rows(difference.get("support_before", [])))
        st.write("Campos de suporte novos")
        display_table(support_rows(difference.get("support_after", [])))
    with st.expander("Avisos de validação — até 30 por página"):
        issues = {
            "APPLICATION_VARIANT": "Aplicação com atributos diferentes",
            "UNRECOGNIZED_ATTRIBUTE": "Atributo sem valor SIM/NÃO reconhecido",
            "SUMMARY_TOTAL_DIFFERS": "Resumo histórico diverge do consolidado",
            "HISTORICAL_SUMMARY_NOT_AUTHORITATIVE": "Resumo histórico informativo",
            "COMPLEMENTARY_RELEASE_WARNING": "Aba complementar exige conferência",
            "INVALID_DATE": "Data inválida",
            "REJECTED_ROW": "Registro rejeitado",
            "DUPLICATE_ROW": "Registro duplicado",
            "CONFLICTING_SYSTEM": "Conflito entre sistemas",
            "UNRESOLVED_STATUS": "Situação não definida",
            "OUTSIDE_TABLE": "Linha fora da tabela",
            "IGNORED_SHEET": "Aba sem tabela reconhecida",
            "REPEATED_HEADER": "Cabeçalho repetido",
        }
        display_table(
            [
                {
                    "Aba": r.get("sheet", ""),
                    "Linha": str(r.get("row", r.get("rows", ""))),
                    "Aviso": issues.get(r["code"], "Aviso de leitura"),
                    "Detalhe": r.get("detail", r.get("raw_value", r.get("key", ""))),
                }
                for r in data["validation_issues"]
            ]
        )
    st.subheader("Impacto nas decisões humanas e no desenvolvimento")
    st.caption(f"{data['impacts_total']} impactos registrados; até 30 por página")
    display_table(
        [
            {
                "Origem": "Revisão humana" if r["kind"] == "REVIEW" else "Desenvolvimento",
                "Registro": r["entity_id"],
                "Impacto": REASONS.get(r["payload"].get("reason"), r["payload"].get("message", "")),
            }
            for r in data["impacts"]
        ]
    )
    with st.expander("Histórico desta versão"):
        display_table(
            [
                {
                    "Data": r["created_at"],
                    "Responsável": r["actor"],
                    "Evento": {
                        "PREPARED": "Preparação",
                        "COMPARED": "Comparação atualizada",
                        "PUBLISHED": "Publicação",
                        "PUBLICATION_FAILED": "Falha na publicação",
                        "DERIVED_UPDATED": "Avaliações derivadas atualizadas",
                        "LEGACY_IMPORT": "Importação administrativa",
                    }.get(r["action"], "Operação registrada"),
                    "Observações": r["notes"],
                }
                for r in data["events"]
            ]
        )
    if item["status"] == "VALIDATED":
        st.subheader("Confirmação da publicação")
        display_table(
            [
                {
                    "Arquivo": item["original_filename"],
                    "Veículos": report.get("unique_vehicles", item["unique_vehicles"]),
                    "Aplicações (linhas)": report.get("applications", item["valid_records"]),
                    "Sistemas distintos": report.get("unique_systems", "Não apurado"),
                    "Duplicidades exatas": report.get("duplicates", 0),
                    "Conflitos": report.get("conflicts", 0),
                    "Veículos adicionados": comparison.get("added", 0),
                    "Veículos removidos": comparison.get("removed", 0),
                    "Veículos alterados": comparison.get("changed", 0),
                    "Decisões a revalidar": report.get("review_affected", 0),
                }
            ]
        )
        st.write(
            f"Publicar versão {selected}? A comparação usa a importação {item['parent_import_id']}. {report.get('review_affected', 0)} decisões podem exigir revisão; {report.get('development_affected', 0)} itens de desenvolvimento precisam de conferência."
        )
        with st.form(f"scanner_publish_{selected}"):
            actor = st.text_input("Responsável pela publicação", max_chars=120)
            justification = st.text_area("Justificativa da publicação", max_chars=4000)
            confirmed = st.checkbox("Conferi as diferenças e confirmo a publicação desta versão")
            publish = st.form_submit_button("Confirmar publicação", disabled=disabled)
            compare = st.form_submit_button("Atualizar comparação", disabled=disabled)
            cancel = st.form_submit_button("Cancelar")
        if cancel:
            st.info("Publicação cancelada. A preparação permanece no histórico.")
        if publish or compare:
            try:
                if compare:
                    service.compare(selected, actor)
                else:
                    result = service.publish(
                        selected, actor, justification, confirmed, item["parent_import_id"], item["impact_token"]
                    )
                    st.session_state.scanner_message = "Nova versão publicada." + (
                        " Atualização derivada pendente; use Retomar atualização."
                        if result["derived"] == "PENDING"
                        else " Matching e revisão atualizados."
                    )
                st.session_state.scanner_selection = selected
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Publicação não confirmada. Consulte o histórico antes de tentar novamente.")
    if item["job"] and item["job"]["status"] == "PENDING":
        st.warning("A versão foi publicada; a atualização derivada está pendente e pode ser retomada.")
        if st.button("Retomar atualização", disabled=disabled):
            service.resume(selected)
            st.session_state.scanner_selection = selected
            st.rerun()
