"""Normalização dos dados retornados pelo MCP da operadora."""

from __future__ import annotations

from typing import Any


def normalizar_beneficiario(
    dados: dict[str, Any],
) -> dict[str, Any]:
    """Normaliza diferenças entre esquemas v1 e v2."""

    sessoes = dados.get(
        "sessoes_terapia"
    )

    if isinstance(
        sessoes,
        dict,
    ):
        sessoes_ano = sessoes.get(
            "ano_corrente"
        )
    else:
        sessoes_ano = dados.get(
            "sessoes_terapia_ano"
        )

    return {
        "carteirinha": dados.get(
            "carteirinha"
        ),
        "cpf_mascarado": dados.get(
            "cpf_mascarado"
        ),
        "nome": dados.get(
            "nome"
        ),
        "plano": dados.get(
            "plano"
        ),
        "data_adesao": dados.get(
            "data_adesao"
        ),
        "status": dados.get(
            "status"
        ),
        "sessoes_terapia_ano": (
            sessoes_ano
        ),
    }


def normalizar_historico(
    dados: dict[str, Any],
) -> dict[str, Any]:
    pedidos = dados.get(
        "pedidos"
    )

    if not isinstance(
        pedidos,
        list,
    ):
        pedidos = []

    return {
        "carteirinha": dados.get(
            "carteirinha"
        ),
        "pedidos": pedidos,
        "quantidade_pedidos": len(
            pedidos
        ),
    }
