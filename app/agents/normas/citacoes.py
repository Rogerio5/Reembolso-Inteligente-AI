"""Normalização de referências normativas para o contrato da API."""

from __future__ import annotations

import re


PADROES = (
    (
        re.compile(
            r"\b(?:art\.?|artigo)\s*(\d+)",
            re.IGNORECASE,
        ),
        lambda m: f"ART-{int(m.group(1))}",
    ),
    (
        re.compile(
            r"\bcircular(?:\s+normativa)?\s*"
            r"(\d+)/(\d{4})",
            re.IGNORECASE,
        ),
        lambda m: (
            f"CIRC-{int(m.group(1)):02d}-{m.group(2)}"
        ),
    ),
    (
        re.compile(
            r"\bTUSS[-\s:]*(\d{8})\b",
            re.IGNORECASE,
        ),
        lambda m: f"TUSS-{m.group(1)}",
    ),
)


def normalizar_dispositivos(
    textos: list[str],
) -> list[str]:
    """Extrai identificadores canônicos sem inventar referências."""

    encontrados: list[str] = []

    for texto in textos:
        bruto = str(texto or "")

        if re.search(
            r"\bANEXO\s*IV\b",
            bruto,
            re.IGNORECASE,
        ):
            encontrados.append("ANEXO-IV")

        if re.search(
            r"\b(?:NOTA\s+T[ÉE]CNICA|NT)[-\s]*02\b",
            bruto,
            re.IGNORECASE,
        ):
            encontrados.append("NT-02")

        for padrao, formatar in PADROES:
            for match in padrao.finditer(bruto):
                encontrados.append(
                    formatar(match)
                )

    return list(dict.fromkeys(encontrados))
