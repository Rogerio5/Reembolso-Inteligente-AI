"""Avaliação determinística de requisitos documentais condicionais."""

from __future__ import annotations

from dataclasses import dataclass

from app.calculo.modelos import RequisitoDocumentoCondicional


@dataclass(frozen=True)
class AvaliacaoRequisitoDocumental:
    """Detalha por que um requisito documental foi acionado."""

    acionado: bool
    criterios_avaliados: tuple[str, ...]
    criterios_acionados: tuple[str, ...]
    operador: str


def _normalizar_percentual(
    percentual: float,
) -> float:
    if 0 <= percentual <= 1:
        return percentual * 100

    return percentual


def avaliar_requisito_documental(
    *,
    requisito: RequisitoDocumentoCondicional,
    sessoes_utilizadas: int | None,
    valor_pago_brl: float | None,
    teto_aplicavel_brl: float | None,
) -> AvaliacaoRequisitoDocumental:
    """Avalia o requisito e preserva os critérios satisfeitos."""

    resultados: list[
        tuple[str, bool]
    ] = []

    if requisito.sessoes_min_inclusivo is not None:
        resultados.append(
            (
                "sessoes_min_inclusivo",
                (
                    sessoes_utilizadas is not None
                    and sessoes_utilizadas
                    >= requisito.sessoes_min_inclusivo
                ),
            )
        )

    if requisito.excedente_teto_percentual is not None:
        percentual = _normalizar_percentual(
            requisito.excedente_teto_percentual
        )

        if (
            valor_pago_brl is None
            or teto_aplicavel_brl is None
            or teto_aplicavel_brl <= 0
        ):
            excedeu = False

        else:
            excedente = (
                (
                    valor_pago_brl
                    - teto_aplicavel_brl
                )
                / teto_aplicavel_brl
            ) * 100

            excedeu = (
                excedente > percentual
            )

        resultados.append(
            (
                "excedente_teto_percentual",
                excedeu,
            )
        )

    operador = requisito.operador.upper()

    if not resultados:
        return AvaliacaoRequisitoDocumental(
            acionado=False,
            criterios_avaliados=(),
            criterios_acionados=(),
            operador=operador,
        )

    valores = [
        resultado
        for _, resultado in resultados
    ]

    if operador == "AND":
        acionado = all(valores)

    elif operador == "OR":
        acionado = any(valores)

    else:
        raise ValueError(
            "Operador documental não suportado: "
            f"{requisito.operador}"
        )

    return AvaliacaoRequisitoDocumental(
        acionado=acionado,
        criterios_avaliados=tuple(
            criterio
            for criterio, _ in resultados
        ),
        criterios_acionados=tuple(
            criterio
            for criterio, resultado in resultados
            if resultado
        ),
        operador=operador,
    )


def requisito_documental_acionado(
    *,
    requisito: RequisitoDocumentoCondicional,
    sessoes_utilizadas: int | None,
    valor_pago_brl: float | None,
    teto_aplicavel_brl: float | None,
) -> bool:
    """Mantém compatibilidade com o fluxo atual."""

    return avaliar_requisito_documental(
        requisito=requisito,
        sessoes_utilizadas=sessoes_utilizadas,
        valor_pago_brl=valor_pago_brl,
        teto_aplicavel_brl=teto_aplicavel_brl,
    ).acionado
