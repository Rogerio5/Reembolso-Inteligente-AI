"""Apuração determinística do limite anual de reembolso."""

from __future__ import annotations

from datetime import date
from typing import Any


def calcular_saldo_anual(
    historico: dict[str, Any],
    data_atendimento: date,
    valor_urs_brl: float,
    limite_anual_urs: float,
) -> float:
    """Calcula o saldo anual disponível em reais."""

    limite_anual_brl = (
        valor_urs_brl
        * limite_anual_urs
    )

    total_reembolsado = 0.0

    for pedido in historico.get(
        "pedidos",
        [],
    ):
        data_texto = pedido.get(
            "data_atendimento"
        )

        valor = pedido.get(
            "valor_reembolsado_brl"
        )

        if not data_texto:
            continue

        if not isinstance(
            valor,
            (int, float),
        ):
            continue

        try:
            data_pedido = date.fromisoformat(
                data_texto
            )
        except ValueError:
            continue

        if (
            data_pedido.year
            != data_atendimento.year
        ):
            continue

        if valor <= 0:
            continue

        total_reembolsado += float(
            valor
        )

    saldo = (
        limite_anual_brl
        - total_reembolsado
    )

    return round(
        max(saldo, 0.0),
        2,
    )
