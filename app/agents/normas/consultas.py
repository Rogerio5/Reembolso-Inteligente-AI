"""Construção e fusão de consultas normativas."""

from __future__ import annotations

from typing import Any


def construir_consultas_normativas(
    *,
    consulta: str,
    categoria: str | None,
    codigo_tuss: str | None,
    plano: str | None,
    data_atendimento: str | None,
) -> list[str]:
    """Monta consultas complementares sem codificar regras normativas."""

    contexto = " | ".join(
        parte
        for parte in (
            f"categoria={categoria}" if categoria else None,
            f"TUSS={codigo_tuss}" if codigo_tuss else None,
            f"plano={plano}" if plano else None,
            (
                f"data_atendimento={data_atendimento}"
                if data_atendimento
                else None
            ),
        )
        if parte
    )

    return [
        f"{consulta}\nContexto: {contexto}",
        (
            "Quais são as regras vigentes de cálculo de reembolso "
            "para este caso, incluindo teto, URS, ordem de cálculo "
            f"e coparticipação?\nContexto: {contexto}"
        ),
        (
            "Quais são os limites anuais, saldos, limites de sessões "
            "ou outras restrições acumuladas aplicáveis a este caso?"
            f"\nContexto: {contexto}"
        ),
        (
            "Quais são as regras de arredondamento, análise humana, "
            "escalonamento e abertura de protocolo aplicáveis?"
            f"\nContexto: {contexto}"
        ),
        (
            "Qual é o valor da URS vigente no exercício da data do "
            "atendimento e quais referências normativas sustentam esse "
            "valor?"
            f"\nContexto: {contexto}"
        ),
        (
            "Quais normas, circulares ou atos posteriores estavam vigentes "
            "na data do atendimento e alteraram, substituíram, revogaram "
            "ou deram nova redação às regras aplicáveis a este caso? "
            "Considere especialmente alterações de teto, cálculo, "
            "coparticipação, limites e requisitos, resolvendo conflitos "
            "pela vigência normativa e não pela numeração do ato."
            f"\nContexto: {contexto}"
        ),
        (
            "Quais são as exigências documentais aplicáveis a este caso, "
            "incluindo documentos complementares condicionais, campos "
            "obrigatórios, situações de pendência documental e condições "
            "que impedem a apuração do valor até a regularização?"
            f"\nContexto: {contexto}"
        ),
    ]


def fundir_resultados_rag(
    grupos: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Remove resultados repetidos preservando a ordem."""

    vistos: set[tuple[Any, Any, Any]] = set()
    resultado_final: list[dict[str, Any]] = []

    for grupo in grupos:
        for item in grupo:
            chave = (
                item.get("arquivo"),
                item.get("pagina"),
                item.get("texto"),
            )

            if chave in vistos:
                continue

            vistos.add(chave)
            resultado_final.append(item)

    return resultado_final
