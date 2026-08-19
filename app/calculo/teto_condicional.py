"""Seleção determinística do teto em URS conforme condições normativas."""

from __future__ import annotations

from app.calculo.modelos import TetoURSCondicional


def selecionar_quantidade_urs(
    *,
    quantidade_urs_base: float | None,
    sessoes_utilizadas: int | None,
    tetos_condicionais: list[TetoURSCondicional],
) -> float | None:
    """Seleciona o teto aplicável usando parâmetros extraídos da KB."""

    if sessoes_utilizadas is None:
        return quantidade_urs_base

    correspondentes: list[TetoURSCondicional] = []

    for teto in tetos_condicionais:
        if (
            teto.sessoes_min_inclusivo is not None
            and sessoes_utilizadas
            < teto.sessoes_min_inclusivo
        ):
            continue

        if (
            teto.sessoes_max_inclusivo is not None
            and sessoes_utilizadas
            > teto.sessoes_max_inclusivo
        ):
            continue

        correspondentes.append(teto)

    if not correspondentes:
        return quantidade_urs_base

    if len(correspondentes) > 1:
        raise ValueError(
            "Mais de um teto condicional em URS "
            "é aplicável ao mesmo número de sessões."
        )

    return correspondentes[0].quantidade_urs
