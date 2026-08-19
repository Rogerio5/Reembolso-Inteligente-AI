"""Seleção determinística da coparticipação recuperada da KB."""

from __future__ import annotations

from datetime import date

from app.calculo.modelos import FaixaCoparticipacao


def meses_completos(
    data_adesao: date,
    data_atendimento: date,
) -> int:
    """Calcula meses completos entre adesão e atendimento."""

    meses = (
        (data_atendimento.year - data_adesao.year) * 12
        + data_atendimento.month
        - data_adesao.month
    )

    if data_atendimento.day < data_adesao.day:
        meses -= 1

    return max(
        meses,
        0,
    )


def _normalizar_percentual(
    valor: float,
) -> float:
    """Normaliza percentual representado como fração ou porcentagem."""

    if 0 <= valor <= 1:
        return valor * 100

    return valor


def selecionar_percentual_coparticipacao(
    *,
    plano: str,
    data_adesao: date,
    data_atendimento: date,
    faixas: list[FaixaCoparticipacao],
) -> float:
    """Seleciona a faixa normativa aplicável sem valores hardcoded."""

    meses = meses_completos(
        data_adesao,
        data_atendimento,
    )

    plano_normalizado = plano.strip().casefold()

    for faixa in faixas:
        if faixa.plano.strip().casefold() != plano_normalizado:
            continue

        if (
            faixa.meses_min_exclusivo is not None
            and meses <= faixa.meses_min_exclusivo
        ):
            continue

        if (
            faixa.meses_max_inclusivo is not None
            and meses > faixa.meses_max_inclusivo
        ):
            continue

        return _normalizar_percentual(
            faixa.percentual
        )

    raise ValueError(
        "Nenhuma faixa normativa de coparticipação "
        f"encontrada para plano={plano!r}, meses={meses}."
    )
