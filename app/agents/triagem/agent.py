"""Subagente de triagem e consulta à operadora."""

from __future__ import annotations

from app.agents.state import AgentState
from app.agents.triagem.normalizacao import (
    normalizar_beneficiario,
    normalizar_historico,
)
from app.tools.operadora import (
    consultar_beneficiario,
    consultar_historico,
)


async def triagem_node(
    state: AgentState,
) -> AgentState:
    """Consulta beneficiário e histórico no MCP."""

    carteirinha = state.get(
        "carteirinha"
    )

    if not carteirinha:
        return {
            **state,
            "agente_atual": "triagem",
            "pendencias": [
                *state.get("pendencias", []),
                "Informe a carteirinha do beneficiário.",
            ],
            "proximo_agente": None,
            "handoff_reason": (
                "Carteirinha necessária para consultar o MCP."
            ),
            "concluido": True,
        }

    beneficiario_bruto = await consultar_beneficiario(
        carteirinha
    )

    historico_bruto = await consultar_historico(
        carteirinha
    )

    beneficiario = normalizar_beneficiario(
        beneficiario_bruto
    )

    historico = normalizar_historico(
        historico_bruto
    )

    return {
        **state,
        "agente_atual": "triagem",
        "beneficiario": beneficiario,
        "historico_reembolsos": historico,
        "proximo_agente": "documento",
        "handoff_reason": (
            "Beneficiário e histórico consultados no MCP."
        ),
    }
