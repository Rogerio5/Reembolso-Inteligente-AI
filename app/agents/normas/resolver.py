"""Resolução normativa a partir dos trechos recuperados pelo RAG.

Este módulo não contém regras específicas hardcoded.
A decisão normativa deve ser baseada exclusivamente nos trechos
recuperados da kb/.
"""

from __future__ import annotations

import re
import unicodedata
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
28. Diferencie limites quantitativos de utilização ou sessões de limites
    financeiros acumulados de reembolso. Se ambos forem aplicáveis,
    trate-os como regras independentes e preserve os dispositivos que
    sustentam cada um.
29. Se um trecho normativo estabelecer parâmetro que possa limitar
    diretamente o valor final, como limite acumulado ou regra de saldo,
    inclua o dispositivo correspondente e o TRECHO_ID que o sustenta.
30. Não omita um limite financeiro acumulado apenas porque a categoria
    também possui limite quantitativo de sessões, atendimentos ou
    utilizações.
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


def _trechos_valor_urs_explicito(
    resultados: list[dict[str, Any]],
    trechos_aplicaveis: list[str],
) -> list[str]:
    """Preserva a definição monetária da URS quando o caso usa URS."""

    indices_aplicaveis: set[int] = set()

    for trecho_id in trechos_aplicaveis:
        texto_id = str(trecho_id).strip().upper()

        if (
            len(texto_id) != 4
            or not texto_id.startswith("T")
            or not texto_id[1:].isdigit()
        ):
            continue

        indice = int(texto_id[1:]) - 1

        if 0 <= indice < len(resultados):
            indices_aplicaveis.add(indice)

    usa_urs = any(
        "urs" in str(
            resultados[indice].get("texto")
            or ""
        ).casefold()
        for indice in indices_aplicaveis
    )

    if not usa_urs:
        return []

    padrao_valor_urs = re.compile(
        r"\b1\s*URS\s*=\s*R\$\s*\d",
        flags=re.IGNORECASE,
    )

    return [
        f"T{indice:03d}"
        for indice, item in enumerate(
            resultados,
            start=1,
        )
        if padrao_valor_urs.search(
            str(item.get("texto") or "")
        )
    ]



def _normalizar_texto_estrutural(
    texto: str,
) -> str:
    """Normaliza texto normativo para buscas estruturais."""

    return "".join(
        caractere
        for caractere in unicodedata.normalize(
            "NFD",
            texto,
        )
        if unicodedata.category(
            caractere
        ) != "Mn"
    ).casefold()


def _dispositivo_circular_estrutural(
    arquivo: str,
) -> str | None:
    """Obtém identificador canônico a partir do próprio nome do ato."""

    match = re.search(
        r"circular[_\-\s]*(\d+)"
        r"[_\-\s]*(\d{4})",
        arquivo,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return (
        f"CIRC-{int(match.group(1)):02d}-"
        f"{match.group(2)}"
    )


def _dispositivos_alterados_circular_vigente(
    resultados: list[dict[str, Any]],
    trechos_circular: list[str],
) -> list[str]:
    """
    Identifica dispositivos efetivamente alterados pela circular
    vigente usando a estrutura textual do próprio ato.
    """

    artigos: set[str] = set()
    dispositivos: list[str] = []

    for trecho_id in trechos_circular:
        texto_id = str(
            trecho_id
        ).strip().upper()

        if (
            len(texto_id) != 4
            or not texto_id.startswith("T")
            or not texto_id[1:].isdigit()
        ):
            continue

        indice = int(
            texto_id[1:]
        ) - 1

        if not (
            0 <= indice < len(resultados)
        ):
            continue

        item = resultados[indice]

        arquivo = str(
            item.get("arquivo")
            or ""
        )

        texto = str(
            item.get("texto")
            or ""
        )

        dispositivo_circular = (
            _dispositivo_circular_estrutural(
                arquivo
            )
        )

        if (
            dispositivo_circular
            and dispositivo_circular
            not in dispositivos
        ):
            dispositivos.append(
                dispositivo_circular
            )

        # Exemplo estrutural:
        # "dá nova redação aos arts. X e Y"
        for match in re.finditer(
            r"d[aá]\s+nova\s+reda[cç][aã]o\s+"
            r"aos?\s+arts?\.?\s+"
            r"([0-9,\se]+)",
            texto,
            flags=re.IGNORECASE,
        ):
            artigos.update(
                re.findall(
                    r"\d+",
                    match.group(1),
                )
            )

        # Em uma construção "art. X ... passa a vigorar",
        # o dispositivo alterado é a última referência
        # de artigo imediatamente anterior ao verbo.
        for vigorar in re.finditer(
            r"passam?\s+a\s+vigorar",
            texto,
            flags=re.IGNORECASE,
        ):
            inicio = max(
                0,
                vigorar.start() - 220,
            )

            janela = texto[
                inicio:vigorar.start()
            ]

            referencias = re.findall(
                r"\bart\.\s*(\d+)",
                janela,
                flags=re.IGNORECASE,
            )

            if referencias:
                artigos.add(
                    referencias[-1]
                )

    for artigo in sorted(
        artigos,
        key=int,
    ):
        dispositivo = (
            f"ART-{artigo}"
        )

        if dispositivo not in dispositivos:
            dispositivos.append(
                dispositivo
            )

    return dispositivos


def _regras_limite_sessoes_estrutural(
    resultados: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """
    Preserva trechos do Regulamento que contenham um limite
    quantitativo explícito de sessões.

    O artigo e o valor são lidos do próprio texto normativo.
    """

    trechos: list[str] = []
    dispositivos: list[str] = []

    for indice_resultado, item in enumerate(
        resultados,
        start=1,
    ):
        arquivo = str(
            item.get("arquivo")
            or ""
        )

        if (
            "regulamento"
            not in arquivo.casefold()
        ):
            continue

        texto = str(
            item.get("texto")
            or ""
        )

        artigos = list(
            re.finditer(
                r"\bArt\.\s*(\d+)\.",
                texto,
            )
        )

        for posicao, artigo in enumerate(
            artigos
        ):
            inicio = artigo.start()

            fim = (
                artigos[posicao + 1].start()
                if posicao + 1
                < len(artigos)
                else len(texto)
            )

            bloco = texto[
                inicio:fim
            ]

            bloco_normalizado = (
                _normalizar_texto_estrutural(
                    bloco
                )
            )

            limite = re.search(
                r"numero\s+de\s+sessoes"
                r".{0,160}?"
                r"limitad[oa]\s+a\s+"
                r"\d+",
                bloco_normalizado,
                flags=re.DOTALL,
            )

            if not limite:
                continue

            trecho_id = (
                f"T{indice_resultado:03d}"
            )

            dispositivo = (
                f"ART-{artigo.group(1)}"
            )

            if trecho_id not in trechos:
                trechos.append(
                    trecho_id
                )

            if (
                dispositivo
                not in dispositivos
            ):
                dispositivos.append(
                    dispositivo
                )

    return (
        trechos,
        dispositivos,
    )





def _regras_limite_anual_estrutural(
    resultados: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Preserva regra explícita de limite financeiro anual."""

    trechos: list[str] = []
    dispositivos: list[str] = []

    for indice_resultado, item in enumerate(
        resultados,
        start=1,
    ):
        arquivo = str(
            item.get("arquivo")
            or ""
        )

        if (
            "regulamento"
            not in arquivo.casefold()
        ):
            continue

        texto = str(
            item.get("texto")
            or ""
        )

        artigos = list(
            re.finditer(
                r"\bArt\.\s*(\d+)\.",
                texto,
            )
        )

        for posicao, artigo in enumerate(
            artigos
        ):
            inicio = artigo.start()

            fim = (
                artigos[posicao + 1].start()
                if posicao + 1
                < len(artigos)
                else len(texto)
            )

            bloco = texto[inicio:fim]

            bloco_normalizado = (
                _normalizar_texto_estrutural(
                    bloco
                )
            )

            limite = re.search(
                r"somatorio\s+dos\s+reembolsos"
                r".{0,220}?"
                r"(?:nao\s+podera\s+exceder|"
                r"limitad[oa]\s+a)"
                r"\s+\d+"
                r"(?:\s*\([^)]*\))?"
                r"\s+urs",
                bloco_normalizado,
                flags=re.DOTALL,
            )

            if not limite:
                continue

            trecho_id = (
                f"T{indice_resultado:03d}"
            )

            dispositivo = (
                f"ART-{artigo.group(1)}"
            )

            if trecho_id not in trechos:
                trechos.append(
                    trecho_id
                )

            if (
                dispositivo
                not in dispositivos
            ):
                dispositivos.append(
                    dispositivo
                )

    return (
        trechos,
        dispositivos,
    )


def _regras_opme_analise_estrutural(
    resultados: list[dict[str, Any]],
    *,
    categoria: str | None = None,
) -> tuple[list[str], list[str]]:
    """
    Preserva dispositivo normativo de itens Material / OPME
    explicitamente marcados como sob análise e sem teto
    automatizado na tabela normativa.
    """

    categoria_normalizada = str(
        categoria or ""
    ).strip().upper()

    if categoria_normalizada != "MATERIAL_OPME":
        return ([], [])

    trechos: list[str] = []
    dispositivos: list[str] = []

    for indice_resultado, item in enumerate(
        resultados,
        start=1,
    ):
        arquivo = str(
            item.get("arquivo")
            or ""
        ).casefold()

        if "tabela_urs" not in arquivo:
            continue

        texto = str(
            item.get("texto")
            or ""
        )

        texto_normalizado = (
            _normalizar_texto_estrutural(
                texto
            )
        )

        for artigo in re.finditer(
            r"\bart\.?\s*(\d+)\b",
            texto_normalizado,
            flags=re.IGNORECASE,
        ):
            inicio_contexto = max(
                0,
                artigo.start() - 240,
            )

            contexto = texto_normalizado[
                inicio_contexto:
                artigo.end()
            ]

            if "opme" not in contexto:
                continue

            if (
                "sem teto automatizado"
                not in contexto
                and "sob analise"
                not in contexto
            ):
                continue

            trecho_id = (
                f"T{indice_resultado:03d}"
            )

            dispositivo = (
                f"ART-{artigo.group(1)}"
            )

            if trecho_id not in trechos:
                trechos.append(
                    trecho_id
                )

            if (
                dispositivo
                not in dispositivos
            ):
                dispositivos.append(
                    dispositivo
                )

    return (
        trechos,
        dispositivos,
    )


def _circulares_substituidas_pela_vigente(
    resultados: list[dict[str, Any]],
    trechos_circular: list[str],
) -> set[str]:
    """
    Identifica circular anterior cuja redação é explicitamente
    substituída pela circular vigente.
    """

    substituidas: set[str] = set()

    for trecho_id in trechos_circular:
        texto_id = str(
            trecho_id
        ).strip().upper()

        if (
            len(texto_id) != 4
            or not texto_id.startswith("T")
            or not texto_id[1:].isdigit()
        ):
            continue

        indice = int(
            texto_id[1:]
        ) - 1

        if not (
            0 <= indice < len(resultados)
        ):
            continue

        texto = str(
            resultados[indice].get(
                "texto"
            )
            or ""
        )

        for match in re.finditer(
            r"na\s+reda[cç][aã]o\s+dada\s+pela\s+"
            r"circular\s+(\d+)\s*/\s*(\d{4})"
            r".{0,220}?"
            r"passa\s+a\s+vigorar",
            texto,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        ):
            substituidas.add(
                "CIRC-"
                f"{int(match.group(1)):02d}-"
                f"{match.group(2)}"
            )

    return substituidas





def _trechos_definicao_acompanhamento_estrutural(
    resultados: list[dict[str, Any]],
) -> list[str]:
    """
    Preserva a definição normativa de acompanhamento continuado
    quando o próprio texto recuperado fornece um único limiar
    quantitativo consistente.

    Nenhum número de sessões é hardcoded aqui.
    """

    candidatos_por_limiar: dict[
        int,
        list[str],
    ] = {}

    for indice, item in enumerate(
        resultados,
        start=1,
    ):
        texto = str(
            item.get("texto")
            or ""
        )

        texto_normalizado = (
            _normalizar_texto_estrutural(
                texto
            )
        )

        match = re.search(
            r"considera-se\s+"
            r"acompanhamento\s+continuado"
            r".{0,360}?"
            r"pelo\s+menos\s+"
            r"(\d+)"
            r"(?:\s*\([^)]*\))?"
            r"\s+sessoes\s+realizadas"
            r"\s+no\s+ano\s+civil",
            texto_normalizado,
            flags=re.DOTALL,
        )

        if not match:
            continue

        limiar = int(
            match.group(1)
        )

        trecho_id = (
            f"T{indice:03d}"
        )

        candidatos_por_limiar.setdefault(
            limiar,
            [],
        ).append(
            trecho_id
        )

    # Só preserva deterministicamente se todas as
    # evidências recuperadas concordarem no mesmo limiar.
    if len(candidatos_por_limiar) != 1:
        return []

    return list(
        dict.fromkeys(
            next(
                iter(
                    candidatos_por_limiar.values()
                )
            )
        )
    )




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

    trechos_valor_urs = (
        _trechos_valor_urs_explicito(
            resultados_rag,
            resultado.trechos_aplicaveis,
        )
    )

    resultado.trechos_aplicaveis = list(
        dict.fromkeys(
            [
                *resultado.trechos_aplicaveis,
                *trechos_valor_urs,
            ]
        )
    )

    (
        trechos_limite_sessoes,
        dispositivos_limite_sessoes,
    ) = _regras_limite_sessoes_estrutural(
        resultados_rag
    )

    (
        trechos_limite_anual,
        dispositivos_limite_anual,
    ) = _regras_limite_anual_estrutural(
        resultados_rag
    )

    (
        trechos_opme_analise,
        dispositivos_opme_analise,
    ) = _regras_opme_analise_estrutural(
        resultados_rag,
        categoria=categoria,
    )

    trechos_definicao_acompanhamento = (
        _trechos_definicao_acompanhamento_estrutural(
            resultados_rag
        )
    )

    resultado.trechos_aplicaveis = list(
        dict.fromkeys(
            [
                *resultado.trechos_aplicaveis,
                *trechos_limite_sessoes,
                *trechos_limite_anual,
                *trechos_opme_analise,
                *trechos_definicao_acompanhamento,
            ]
        )
    )

    dispositivos_circular_vigente = (
        _dispositivos_alterados_circular_vigente(
            resultados_rag,
            trechos_vigencia,
        )
    )

    circulares_substituidas = (
        _circulares_substituidas_pela_vigente(
            resultados_rag,
            trechos_vigencia,
        )
    )

    dispositivos_llm = [
        dispositivo
        for dispositivo in normalizar_dispositivos(
            resultado.dispositivos
        )
        if dispositivo
        not in circulares_substituidas
    ]

    resultado.dispositivos_canonicos = list(
        dict.fromkeys(
            [
                *dispositivos_llm,
                *dispositivos_circular_vigente,
                *dispositivos_limite_sessoes,
                *dispositivos_limite_anual,
                *dispositivos_opme_analise,
            ]
        )
    )

    return resultado
