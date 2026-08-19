"""Supervisor responsável pela orquestração dos subagentes."""

from __future__ import annotations

from app.agents.state import AgentState


DESTINOS_VALIDOS = {
    "triagem",
    "documento",
    "normas",
}


def selecionar_proximo_agente(
    state: AgentState,
) -> tuple[str | None, str]:
    """Seleciona o próximo handoff com base no estado da sessão."""

    destino_explicito = state.get(
        "proximo_agente"
    )

    if destino_explicito in DESTINOS_VALIDOS:
        return (
            destino_explicito,
            state.get("handoff_reason")
            or "Handoff explícito solicitado pelo subagente.",
        )

    if state.get("concluido"):
        return (
            None,
            "Turno concluído; nenhum novo handoff necessário.",
        )

    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    if (
        state.get("anexo_base64")
        and not state.get("dados_documento")
    ):
        return (
            "documento",
            "Há um documento novo para análise antes das demais etapas.",
        )

    if not beneficiario:
        return (
            "triagem",
            "Dados do beneficiário ainda precisam ser validados.",
        )

    if (
        state.get("dados_documento")
        and not state.get("resolucao_normativa")
    ):
        return (
            "normas",
            "Documento disponível e análise normativa pendente.",
        )

    return (
        None,
        "Não há etapa adicional a executar neste turno.",
    )


def supervisor_node(
    state: AgentState,
) -> AgentState:
    """Orquestra os três subagentes e registra o handoff."""

    destino, motivo = selecionar_proximo_agente(
        state
    )

    return {
        **state,
        "agente_atual": "supervisor",
        "proximo_agente": destino,
        "handoff_reason": motivo,
    }
