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

    pendencia_carteirinha = (
        "Informe a carteirinha do beneficiário."
    )

    pendencias_atuais = list(
        dict.fromkeys(
            item
            for item in (
                state.get("pendencias")
                or []
            )
            if item
        )
    )

    if not carteirinha:
        if (
            pendencia_carteirinha
            not in pendencias_atuais
        ):
            pendencias_atuais.append(
                pendencia_carteirinha
            )

        return {
            **state,
            "agente_atual": "triagem",
            "pendencias": pendencias_atuais,
            "proximo_agente": None,
            "handoff_reason": (
                "Carteirinha necessária para consultar o MCP."
            ),
            "concluido": True,
        }

    pendencias_atuais = [
        item
        for item in pendencias_atuais
        if item != pendencia_carteirinha
    ]

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
        "pendencias": pendencias_atuais,
        "proximo_agente": (
            "normas"
            if state.get("dados_documento")
            else "documento"
        ),
        "handoff_reason": (
            "Beneficiário e histórico consultados no MCP; "
            + (
                "documento já disponível, seguir para normas."
                if state.get("dados_documento")
                else "documento ainda precisa ser analisado."
            )
        ),
    }
