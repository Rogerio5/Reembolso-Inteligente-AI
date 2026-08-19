"""Motor determinístico de cálculo de reembolso."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.calculo.modelos import (
    ParametrosCalculo,
    ResultadoCalculo,
)
from app.schemas import Decisao


def calcular_reembolso(
    valor_solicitado_brl: float | None,
    parametros: ParametrosCalculo,
) -> ResultadoCalculo:
    if valor_solicitado_brl is None:
        return ResultadoCalculo(
            calculavel=False,
            motivo="Valor solicitado não informado.",
            pendencias=[
                "Valor solicitado necessário para cálculo."
            ],
        )

    if parametros.exige_analise_humana:
        return ResultadoCalculo(
            decisao=Decisao.ESCALADO_ANALISTA,
            valor_solicitado_brl=valor_solicitado_brl,
            valor_reembolso_brl=None,
            calculavel=False,
            motivo="Norma exige análise humana.",
        )

    parametros_utilizados: list[str] = []
    operacoes_utilizadas: list[str] = []

    teto: float | None = parametros.teto_brl

    if teto is not None:
        parametros_utilizados.append(
            "teto_brl"
        )

    elif (
        parametros.valor_urs_brl is not None
        and parametros.quantidade_urs is not None
    ):
        teto = (
            parametros.valor_urs_brl
            * parametros.quantidade_urs
        )

        parametros_utilizados.extend(
            [
                "valor_urs_brl",
                "quantidade_urs",
            ]
        )

    if teto is not None:
        operacoes_utilizadas.append(
            "determinar_teto_procedimento"
        )

    if teto is None:
        return ResultadoCalculo(
            valor_solicitado_brl=valor_solicitado_brl,
            calculavel=False,
            motivo=(
                "Teto normativo insuficiente "
                "para cálculo determinístico."
            ),
        )

    valor_apurado = min(
        valor_solicitado_brl,
        teto,
    )

    operacoes_utilizadas.append(
        "apurar_menor_valor"
    )

    percentual = (
        parametros.percentual_coparticipacao
    )

    if percentual is None:
        return ResultadoCalculo(
            valor_solicitado_brl=valor_solicitado_brl,
            calculavel=False,
            motivo=(
                "Percentual de coparticipação "
                "não informado."
            ),
        )

    parametros_utilizados.append(
        "percentual_coparticipacao"
    )

    valor_apos_coparticipacao = (
        valor_apurado
        * (1 - percentual / 100)
    )

    operacoes_utilizadas.append(
        "aplicar_coparticipacao"
    )

    limitado_por_saldo_anual = False

    valor_final = valor_apos_coparticipacao

    if parametros.saldo_anual_brl is not None:
        limitado_por_saldo_anual = (
            parametros.saldo_anual_brl
            < valor_apos_coparticipacao
        )

        valor_final = min(
            valor_apos_coparticipacao,
            parametros.saldo_anual_brl,
        )

        if limitado_por_saldo_anual:
            parametros_utilizados.extend(
                [
                    "limite_anual_urs",
                    "valor_urs_brl",
                ]
            )

            operacoes_utilizadas.append(
                "limitar_por_saldo_anual"
            )

    operacoes_utilizadas.append(
        "arredondar_valor_final"
    )

    valor_reembolso = float(
        Decimal(str(valor_final)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )

    if valor_reembolso <= 0:
        decisao = Decisao.NEGADO
    elif limitado_por_saldo_anual:
        decisao = Decisao.APROVADO_PARCIAL
    else:
        decisao = Decisao.APROVADO

    return ResultadoCalculo(
        decisao=decisao,
        valor_solicitado_brl=valor_solicitado_brl,
        valor_reembolso_brl=valor_reembolso,
        calculavel=True,
        motivo="Cálculo determinístico concluído.",
        parametros_utilizados=list(
            dict.fromkeys(
                parametros_utilizados
            )
        ),
        operacoes_utilizadas=list(
            dict.fromkeys(
                operacoes_utilizadas
            )
        ),
    )

