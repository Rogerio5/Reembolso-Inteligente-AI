"""Resolução normativa a partir dos trechos recuperados pelo RAG.

Este módulo não contém regras específicas hardcoded.
A decisão normativa deve ser baseada exclusivamente nos trechos
recuperados da kb/.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.llm import criar_llm
from app.agents.normas.citacoes import normalizar_dispositivos


class NormaAplicavel(BaseModel):
    """Resultado estruturado da análise normativa."""

    aplicavel: bool = False

    resumo_regra: str = ""

    fontes_principais: list[str] = Field(
        default_factory=list
    )

    dispositivos: list[str] = Field(
        default_factory=list
    )

    dispositivos_canonicos: list[str] = Field(
        default_factory=list
    )

    fontes_descartadas: list[str] = Field(
        default_factory=list
    )

    justificativa_vigencia: str = ""

    insuficiente: bool = False

    informacao_faltante: str | None = None

    trechos_aplicaveis: list[str] = Field(
        default_factory=list
    )


SISTEMA = """
Você é o agente responsável por análise normativa de reembolso.

Você receberá trechos recuperados de uma base normativa e uma data
de atendimento.

Sua tarefa é identificar quais normas são aplicáveis ao assunto.

Regras obrigatórias:

1. Use somente os trechos fornecidos.
2. Não invente artigo, circular, código TUSS ou regra.
3. Distinga norma principal de material de apoio.
4. Regulamento, anexos, notas técnicas e circulares podem fundamentar
   decisão conforme o conteúdo recuperado.
5. Manual e FAQ são materiais auxiliares. Se conflitarem com norma
   superior ou mais recente, não devem prevalecer.
6. Analise datas de publicação, início de vigência, alteração e revogação.
7. O número de uma circular não determina sozinho qual é mais recente.
8. Considere a norma vigente na data do atendimento quando os trechos
   indicarem essa regra temporal.
9. Se os trechos não forem suficientes para concluir, marque
   insuficiente=true em vez de adivinhar.
10. Em dispositivos, informe somente identificadores efetivamente
    sustentados pelos trechos recebidos.
11. Categoria, código TUSS, plano e data do atendimento fornecidos como
    FATOS DO CASO são dados autoritativos. Não os substitua, corrija,
    complete ou invente.
12. Se houver código TUSS informado como fato do caso, nunca mencione
    outro código TUSS como sendo o código do atendimento.
13. Considere conjuntamente todas as regras materiais aplicáveis ao caso
    presentes nos trechos, incluindo, quando sustentadas pelo contexto:
    teto do procedimento, método de apuração, coparticipação, limites
    acumulados, arredondamento, alçada e protocolo.
14. Não omita uma regra aplicável apenas porque ela está em outro trecho
    recuperado.
15. Diferencie documento exigido do beneficiário de documento normativo
    usado apenas como fonte da regra.
16. Em dispositivos, inclua SOMENTE normas diretamente aplicadas à
    análise deste caso concreto.
17. Não inclua artigo apenas porque ele aparece no mesmo trecho,
    capítulo ou documento recuperado.
18. Não inclua definições, regras de outras categorias, regras de
    exceções não acionadas ou dispositivos meramente contextuais.
19. Um dispositivo deve entrar somente se alterar, limitar, validar,
    calcular, suspender, negar, aprovar ou escalar este pedido.
20. Preserve o código TUSS fornecido nos FATOS DO CASO; não invente
    nem substitua por outro código.
21. Cada trecho recebido possui um TRECHO_ID.
22. Em trechos_aplicaveis, informe SOMENTE os TRECHO_ID que sustentam
    regras efetivamente aplicáveis ao caso concreto.
23. Não selecione um trecho apenas porque ele pertence ao mesmo arquivo
    de outra regra válida.
24. Se uma norma posterior alterar, substituir ou revogar uma redação
    anterior, NÃO selecione como aplicável o trecho que contém a regra
    superada para aquele ponto.
25. Não selecione trecho de categoria diferente apenas porque contém
    termos genéricos como teto, URS, sessão, coparticipação ou limite.
26. Selecione todos os trechos necessários para sustentar de forma
    completa cálculo, documentação, limites, vigência, escalonamento
    e decisão realmente aplicáveis ao caso.
27. Material auxiliar não deve substituir texto normativo superior
    quando houver conflito.
28. Uma norma posterior que altere apenas determinados dispositivos NÃO
    elimina as demais regras-base aplicáveis do Regulamento, tabela, nota
    técnica ou anexos que não tenham sido expressamente alteradas.
29. Ao selecionar trechos_aplicaveis, preserve conjuntamente:
    a) a norma posterior vigente para os dispositivos que ela modificou; e
    b) os trechos normativos anteriores ainda vigentes necessários para
       teto, método de apuração, ordem das operações, limites,
       arredondamento, documentação e decisão do caso concreto.
30. Não interprete a existência de uma circular posterior como revogação
    integral do Regulamento. Substitua somente a matéria que os trechos
    demonstrarem ter sido alterada, revogada ou substituída.

Não faça o cálculo do reembolso neste módulo.
Não produza diagnóstico clínico.
"""


def _formatar_trechos(
    resultados: list[dict[str, Any]],
) -> str:
    blocos: list[str] = []

    for indice, item in enumerate(
        resultados,
        start=1,
    ):
        arquivo = item.get("arquivo") or "desconhecido"
        pagina = item.get("pagina")
        texto = str(item.get("texto") or "").strip()

        trecho_id = f"T{indice:03d}"

        cabecalho = (
            f"TRECHO_ID: {trecho_id}\n"
            f"ARQUIVO: {arquivo}\n"
            f"PAGINA: {pagina}\n"
        )

        blocos.append(
            cabecalho + texto
        )

    return "\n\n--- TRECHO ---\n\n".join(
        blocos
    )


def filtrar_resultados_aplicaveis(
    resultados: list[dict[str, Any]],
    trechos_aplicaveis: list[str],
) -> list[dict[str, Any]]:
    """Mantém somente evidências selecionadas pela resolução normativa."""

    indices: list[int] = []

    for trecho_id in trechos_aplicaveis:
        texto = str(
            trecho_id
        ).strip().upper()

        if (
            len(texto) != 4
            or not texto.startswith("T")
            or not texto[1:].isdigit()
        ):
            continue

        indice = int(
            texto[1:]
        ) - 1

        if (
            indice < 0
            or indice >= len(resultados)
        ):
            continue

        if indice not in indices:
            indices.append(
                indice
            )

    return [
        resultados[indice]
        for indice in indices
    ]



_MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


_PADROES_VIGENCIA = (
    re.compile(
        r"in[ií]cio\s+de\s+vig[eê]ncia\s*:\s*"
        r"(\d{1,2})(?:º)?\s+de\s+"
        r"([a-záàâãéêíóôõúç]+)\s+de\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"entra\s+em\s+vigor[^.\n]{0,100}?"
        r"(\d{1,2})(?:º)?\s+de\s+"
        r"([a-záàâãéêíóôõúç]+)\s+de\s+(\d{4})",
        re.IGNORECASE,
    ),
)


def _normalizar_data_referencia(
    valor: date | str | None,
) -> date | None:
    """Converte a data do atendimento para comparação temporal."""

    if isinstance(
        valor,
        date,
    ):
        return valor

    if not valor:
        return None

    try:
        return date.fromisoformat(
            str(valor)
        )
    except ValueError:
        return None


def _extrair_data_vigencia(
    texto: str,
) -> date | None:
    """Extrai data de início de vigência explicitamente declarada."""

    for padrao in _PADROES_VIGENCIA:
        match = padrao.search(
            texto
        )

        if not match:
            continue

        dia = int(
            match.group(1)
        )

        mes_texto = (
            match.group(2)
            .casefold()
        )

        ano = int(
            match.group(3)
        )

        mes = _MESES_PT.get(
            mes_texto
        )

        if mes is None:
            continue

        try:
            return date(
                ano,
                mes,
                dia,
            )
        except ValueError:
            continue

    return None


def _trechos_circular_mais_recente(
    resultados: list[dict[str, Any]],
    data_atendimento: date | str | None,
) -> list[str]:
    """Preserva a circular recuperada de vigência mais recente aplicável.

    A função não conhece números de circulares, artigos, percentuais
    ou valores normativos. Ela trabalha somente com as evidências
    temporais presentes nos próprios trechos recuperados.
    """

    data_referencia = (
        _normalizar_data_referencia(
            data_atendimento
        )
    )

    if data_referencia is None:
        return []

    datas_por_arquivo: dict[
        str,
        date,
    ] = {}

    for item in resultados:
        arquivo = str(
            item.get("arquivo")
            or ""
        )

        if not arquivo.casefold().startswith(
            "circular_"
        ):
            continue

        texto = str(
            item.get("texto")
            or ""
        )

        data_vigencia = (
            _extrair_data_vigencia(
                texto
            )
        )

        if data_vigencia is None:
            continue

        if data_vigencia > data_referencia:
            continue

        atual = datas_por_arquivo.get(
            arquivo
        )

        if (
            atual is None
            or data_vigencia > atual
        ):
            datas_por_arquivo[
                arquivo
            ] = data_vigencia

    if not datas_por_arquivo:
        return []

    data_mais_recente = max(
        datas_por_arquivo.values()
    )

    arquivos_mais_recentes = {
        arquivo
        for arquivo, data_vigencia
        in datas_por_arquivo.items()
        if data_vigencia
        == data_mais_recente
    }

    return [
        f"T{indice:03d}"
        for indice, item in enumerate(
            resultados,
            start=1,
        )
        if str(
            item.get("arquivo")
            or ""
        )
        in arquivos_mais_recentes
    ]


def resolver_normas(
    consulta: str,
    data_atendimento: date | str | None,
    resultados_rag: list[dict[str, Any]],
    *,
    categoria: str | None = None,
    codigo_tuss: str | None = None,
    plano: str | None = None,
) -> NormaAplicavel:
    """Resolve vigência e precedência usando somente o contexto recuperado."""

    if not resultados_rag:
        return NormaAplicavel(
            insuficiente=True,
            informacao_faltante=(
                "Nenhum trecho normativo foi recuperado."
            ),
        )

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        NormaAplicavel
    )

    contexto = _formatar_trechos(
        resultados_rag
    )

    data_texto = (
        data_atendimento.isoformat()
        if isinstance(data_atendimento, date)
        else str(data_atendimento or "não informada")
    )

    usuario = f"""
ASSUNTO A ANALISAR:
{consulta}

FATOS DO CASO — NÃO ALTERAR:
CATEGORIA: {categoria or "não informada"}
CODIGO_TUSS: {codigo_tuss or "não informado"}
PLANO: {plano or "não informado"}
DATA_ATENDIMENTO: {data_texto}

TRECHOS RECUPERADOS:
{contexto}

Determine o conjunto completo de regras normativas aplicáveis ao caso,
considerando todos os trechos recuperados e preservando exatamente os
fatos do caso acima.
Explique brevemente a precedência/vigência utilizada.
"""

    resultado = modelo.invoke(
        [
            ("system", SISTEMA),
            ("human", usuario),
        ]
    )

    if not isinstance(
        resultado,
        NormaAplicavel,
    ):
        raise TypeError(
            "Structured output não retornou NormaAplicavel."
        )

    ids_validos = {
        f"T{indice:03d}"
        for indice in range(
            1,
            len(resultados_rag) + 1,
        )
    }

    resultado.trechos_aplicaveis = list(
        dict.fromkeys(
            trecho_id.strip().upper()
            for trecho_id in (
                resultado.trechos_aplicaveis
                or []
            )
            if (
                trecho_id
                and trecho_id.strip().upper()
                in ids_validos
            )
        )
    )

    trechos_vigencia = (
        _trechos_circular_mais_recente(
            resultados_rag,
            data_atendimento,
        )
    )

    resultado.trechos_aplicaveis = list(
        dict.fromkeys(
            [
                *resultado.trechos_aplicaveis,
                *trechos_vigencia,
            ]
        )
    )

    resultado.dispositivos_canonicos = (
        normalizar_dispositivos(
            resultado.dispositivos
        )
    )

    return resultado
