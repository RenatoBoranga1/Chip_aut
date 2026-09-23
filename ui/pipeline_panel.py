"""Portuguese presentation of automatic updates; no SQL or orchestration rules."""

import os
import uuid
from pathlib import Path

import streamlit as st

from services.scheduler_config import DEFAULT_CONFIG, load_config
from services.scheduler_service import launch_manual, scheduler_status
from ui.textos import value


def automatic_updates(service, table):
    config_path = Path(os.environ.get("MOTO_SCHEDULER_CONFIG", str(DEFAULT_CONFIG)))
    config = load_config(config_path)
    page = st.number_input("Página das execuções", min_value=1, value=1, step=1)
    data = scheduler_status(service.config.database, config, page - 1)
    st.subheader("Atualização automática")
    st.write("Agendamento: " + value(data["schedule_status"]))
    st.caption("O agendamento funciona em um processo separado deste painel.")
    st.write("Próxima atualização prevista: " + (data["next_local"] or "Sem previsão ativa"))
    st.caption("Fuso horário: " + config.timezone)
    if "pipeline_request" not in st.session_state:
        st.session_state.pipeline_request = str(uuid.uuid4())
    if st.button(
        "Executar atualização agora", disabled=service.config.read_only or service.config.partner != "wr_motos"
    ):
        try:
            launch_manual(
                service.config.database,
                config_path,
                request_key=st.session_state.pipeline_request,
                read_only=service.config.read_only,
            )
        except Exception:
            st.error("Não foi possível solicitar a atualização. Confira a configuração e tente novamente.")
        else:
            st.info("Solicitação enviada. Acompanhe o resultado no histórico abaixo.")
    if st.button("Preparar nova solicitação"):
        st.session_state.pipeline_request = str(uuid.uuid4())
    if service.config.read_only:
        st.caption("Modo somente leitura: atualizações manuais estão desabilitadas.")
    st.subheader("Execuções automáticas")
    runs = data["runs"]
    related = st.session_state.pop("related_pipeline_id", None)
    if related:
        from database.pipeline_repository import read_pipeline

        if related not in {r["id"] for r in runs}:
            runs.extend(read_pipeline(service.config.database, run_id=related)["runs"])
    table(
        [
            {
                "pipeline_run_id": r["id"],
                "Quantidade de falhas": len(r["summary"].get("errors", [])),
                "Quantidade de avisos": sum(r["summary"].get("warnings", {}).values()),
                **{k: r[k] for k in ("started_at", "trigger_type", "status", "duration_seconds", "error_summary")},
                **{k: r["summary"].get(k) for k in ("ads_after", "new", "reappeared", "disappeared")},
            }
            for r in runs
        ],
        "pipeline_runs",
    )
    selected = st.selectbox(
        "Ver detalhes da execução",
        [None, *[r["id"] for r in runs]],
        index=([None, *[r["id"] for r in runs]].index(related) if related else 0),
        format_func=lambda v: f"Execução {v}" if v else "Selecione uma execução",
    )
    if selected:
        run = next(r for r in runs if r["id"] == selected)
        table(
            [
                {
                    k: run[k]
                    for k in ("started_at", "finished_at", "heartbeat_at", "duration_seconds", "trigger_type", "status")
                }
            ],
            "pipeline_detail",
        )
        summary = run["summary"]
        if summary.get("alert_error"):
            st.warning("Geração de alertas pendente. A coleta publicada permanece válida; consulte o registro local.")
        if "alerts" in summary:
            st.write(f"Alertas criados: {summary['alerts']['created']} · Atualizados: {summary['alerts']['updated']}")
        for field, title in (
            ("matching_counts", "Correspondências"),
            ("coverage_counts", "Cobertura"),
            ("warnings", "Avisos"),
        ):
            st.subheader(title)
            table([{"reason": k, "Ocorrências": v} for k, v in summary.get(field, {}).items()], "pipeline_" + field)
        st.write("Situação da fila")
        table(
            [{"state": k, "Itens": v} for k, v in summary.get("queue_counts", {}).get("states", {}).items()],
            "pipeline_queue",
        )
        st.subheader("Falhas registradas")
        table([{"code": e.get("code"), "page": e.get("page")} for e in summary.get("errors", [])], "pipeline_errors")
        if run["status"] == "SKIPPED_ALREADY_RUNNING":
            st.info("Atualização já em andamento. Esta solicitação não iniciou outra coleta.")
        elif run["error_summary"]:
            st.warning(
                "A execução falhou ou foi interrompida. A versão anterior dos dados foi preservada. Consulte o registro local para diagnóstico."
            )


@st.fragment(run_every=15)
def refresh_after_pipeline(service):
    from database.pipeline_repository import read_pipeline

    runs = read_pipeline(service.config.database, limit=1)["runs"]
    marker = (
        (runs[0]["id"], runs[0]["status"], runs[0]["summary"].get("alerts"), runs[0]["summary"].get("alert_error"))
        if runs
        else None
    )
    key = "pipeline_last_seen"
    if key in st.session_state and st.session_state[key] != marker:
        st.session_state[key] = marker
        st.rerun()
    st.session_state[key] = marker
