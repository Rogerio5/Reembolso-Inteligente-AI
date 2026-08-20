"""Extração estruturada de parâmetros de cálculo a partir das normas."""

from __future__ import annotations

import re
import unicodedata

from app.calculo.categoria_documento_exigido import (
    classificar_categoria_documento_exigido,
)

from typing import Any

from pydantic import BaseModel, Field

from app.calculo.modelos import (
    FaixaCoparticipacao,
    ParametrosCalculo,
    ProvenienciaParametro,
    RequisitoDocumentoCondicional,
    TetoURSCondicional,
)
from app.llm import criar_llm


SISTEMA = """
Você recebe uma resolução normativa já produzida a partir da base kb/.

Sua tarefa é transformar somente as regras explicitamente presentes
nessa resolução em parâmetros estruturados de cálculo.

Regras:
1. Não invente valores.
2. Não use conhecimento externo.
3. Não determine a decisão final.
4. Não calcule o valor de reembolso.
5. Preencha somente parâmetros sustentados pelo contexto.
6. Quando uma regra usar URS, extraia valor_urs_brl somente quando o
   valor monetário da URS estiver sustentado pelo contexto.
7. quantidade_urs representa o teto BASE ou incondicional do procedimento,
   quando houver.
8. Quando a norma trouxer um teto em URS que dependa de quantidade de
   sessões já realizadas, extraia essa regra em tetos_urs_condicionais.
9. Para cada teto condicional, preserve exatamente:
   - sessoes_min_inclusivo, quando houver mínimo;
   - sessoes_max_inclusivo, quando houver máximo;
   - quantidade_urs.
10. Não substitua o teto base pelo teto condicional durante a extração.
    A escolha da faixa aplicável será feita posteriormente de forma
    determinística com os dados do MCP.
11. Não invente limites de sessões ou quantidades de URS que não estejam
    explicitamente presentes no contexto.
12. Não determine percentual_coparticipacao diretamente quando a norma
   apresentar uma tabela dependente de plano e tempo de adesão.
8. Quando houver tabela normativa de coparticipação, extraia todas as
   faixas sustentadas pelo contexto em faixas_coparticipacao.
9. Para cada faixa, preserve exatamente:
   - plano;
   - limite inferior de meses, quando houver;
   - limite superior de meses, quando houver;
   - percentual.
10. meses_min_exclusivo significa que a faixa exige quantidade de meses
    estritamente maior que esse valor.
11. meses_max_inclusivo significa que a faixa aceita quantidade de meses
    menor ou igual a esse valor.
12. Não confunda coparticipação com percentual de reembolso.
13. teto_brl deve representar teto monetário explícito, quando houver.
14. limite_anual_urs deve ser preenchido quando o contexto trouxer limite
    anual aplicável expresso em URS.
15. limite_sessoes_ano deve ser preenchido somente se houver limite
    anual de sessões aplicável à categoria.
16. limite_alcada_brl representa exclusivamente o limite monetário de
    competência da análise automatizada, quando o contexto trouxer essa
    regra.
17. Não confunda limite_alcada_brl com teto_brl do procedimento.
18. Se a norma disser que o caso escala somente quando o valor solicitado
    ultrapassar a alçada, extraia limite_alcada_brl e NÃO marque
    exige_analise_humana=true apenas pela existência dessa regra.
19. analise_humana_incondicional deve ser true somente quando a categoria
    ou condição do caso exigir análise humana independentemente do valor.
20. exige_analise_humana deve ser true somente quando o próprio contexto
    já demonstrar que a condição de escalonamento foi efetivamente
    satisfeita, ou quando houver exigência humana incondicional.
21. exige_protocolo deve ser true somente quando a condição normativa que
    exige protocolo estiver efetivamente acionada neste caso.
22. Documentos normativos, tabelas, regulamentos, notas técnicas e
    circulares usados como fonte NÃO são documentos_obrigatorios do
    beneficiário.
23. Quando um documento adicional for exigido apenas se uma condição
    normativa ocorrer, NÃO o coloque em documentos_obrigatorios.
24. Extraia essas regras em requisitos_documentais_condicionais.
25. Para cada requisito condicional, preserve exatamente:
    - o tipo de documento exigido;
    - a categoria canônica do documento exigido, quando puder ser
      identificada pelas regras de classificação da base;
    - o mínimo de sessões, quando houver;
    - o percentual pelo qual o valor pago deve exceder o teto,
      quando houver;
    - o operador lógico indicado pela norma.
26. excedente_teto_percentual representa percentual, não multiplicador.
27. Se a norma estabelecer condições alternativas, use operador="OR".
28. Não determine neste módulo se a condição já foi satisfeita.
    A avaliação será feita posteriormente de forma determinística.
29. Se não houver dados suficientes para determinado campo, use null.
30. Preencha proveniencias para todo parâmetro normativo efetivamente
    extraído quando o dispositivo que o sustenta estiver identificado.
31. Em cada item de proveniencias, campo deve conter o nome exato do
    parâmetro de ParametrosCalculo ao qual a regra dá origem.
32. Em dispositivos, use SOMENTE identificadores presentes na lista
    DISPOSITIVOS_CANONICOS_PERMITIDOS fornecida no contexto.
33. Nunca invente, complete ou normalize um dispositivo por conta própria.
34. Não associe um dispositivo a um campo apenas porque eles aparecem
    no mesmo trecho. A regra deve sustentar diretamente o parâmetro.
35. Não crie proveniência normativa para valores calculados posteriormente
    a partir do MCP ou do histórico, como saldo_anual_brl,
    sessoes_utilizadas_ano ou percentual_coparticipacao selecionado
    posteriormente a partir das faixas.
36. Para estruturas normativas como faixas_coparticipacao,
    tetos_urs_condicionais e requisitos_documentais_condicionais,
    use o nome da estrutura como campo da proveniência.
37. Para cada item de requisitos_documentais_condicionais, preencha
    também o campo dispositivos com as regras que sustentam diretamente
    aquele requisito documental e suas condições.
38. Em requisitos_documentais_condicionais.dispositivos, use SOMENTE
    identificadores presentes em DISPOSITIVOS_CANONICOS_PERMITIDOS.
39. Não inclua dispositivo meramente contextual no requisito documental.
40. Se não for possível identificar com segurança a regra que sustenta
    o requisito documental, deixe dispositivos vazio em vez de inventar.
"""


class TabelaCoparticipacaoExtraida(BaseModel):
    """Tabela normativa completa de coparticipação."""

    faixas: list[
        FaixaCoparticipacao
    ] = Field(
        default_factory=list
    )


SISTEMA_COPARTICIPACAO = """
Você recebe somente trechos normativos já considerados
aplicáveis ao caso.

Sua única tarefa é extrair a TABELA COMPLETA de
coparticipação, quando ela estiver presente.

Regras obrigatórias:

1. Não invente plano, faixa, limite ou percentual.
2. Não use conhecimento externo.
3. Se não houver tabela normativa de coparticipação,
   retorne faixas=[].
4. Quando houver tabela, extraia TODAS as linhas,
   TODOS os planos e TODAS as faixas temporais presentes.
5. Não retorne apenas a faixa que parece aplicável ao caso.
6. Não omita primeira, intermediária ou última faixa.
7. Não misture exemplos, FAQ ou percentuais informais com
   uma tabela normativa existente.
8. Converta percentual para fração decimal:
   35% -> 0.35
   15% -> 0.15
9. Interprete:
   "até N meses" como
       meses_min_exclusivo=None
       meses_max_inclusivo=N
10. Interprete:
    "de A a B meses" como
       meses_min_exclusivo=A
       meses_max_inclusivo=B
11. Interprete:
    "acima de N meses" como
       meses_min_exclusivo=N
       meses_max_inclusivo=None
12. Não una duas faixas diferentes.
13. Não altere os valores presentes na fonte.
"""


class MapaProveniencias(BaseModel):
    """Mapa estruturado entre parâmetros e dispositivos normativos."""

    proveniencias: list[
        ProvenienciaParametro
    ] = Field(
        default_factory=list
    )


SISTEMA_PROVENIENCIA = """
Você recebe parâmetros normativos já extraídos e os trechos que
fundamentaram essa extração.

Sua única tarefa é identificar qual dispositivo normativo sustenta
diretamente cada parâmetro.

Regras obrigatórias:

1. Não altere os valores dos parâmetros.
2. Não faça cálculo.
3. Não determine a decisão.
4. Não invente dispositivo.
5. Use SOMENTE identificadores presentes em
   DISPOSITIVOS_CANONICOS_PERMITIDOS.
6. campo deve ser exatamente um nome recebido em
   PARAMETROS_NORMATIVOS_EXTRAIDOS.
7. Só associe um dispositivo quando o trecho realmente sustentar
   aquele parâmetro.
8. Não associe dispositivo apenas porque aparece no mesmo trecho.
9. Um parâmetro pode possuir mais de um dispositivo quando todos
   forem necessários para sustentá-lo.
10. Se não houver sustentação identificável para um parâmetro,
    simplesmente não crie proveniência para ele.
"""


def _selecionar_trechos_coparticipacao(
    trechos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Seleciona a fonte normativa vigente da tabela de coparticipação."""

    relevantes: list[
        dict[str, Any]
    ] = []

    for item in trechos:
        texto = str(
            item.get("texto")
            or ""
        ).casefold()

        if "coparticip" not in texto:
            continue

        relevantes.append(item)

    if not relevantes:
        return []

    circulares_alteradoras: list[
        dict[str, Any]
    ] = []

    for item in relevantes:
        arquivo = str(
            item.get("arquivo")
            or ""
        ).casefold()

        if not arquivo.startswith(
            "circular_"
        ):
            continue

        texto = str(
            item.get("texto")
            or ""
        ).casefold()

        if (
            "não altera o art. 44"
            in texto
            or "nao altera o art. 44"
            in texto
        ):
            continue

        menciona_artigo = (
            "art. 44" in texto
            or "artigo 44" in texto
        )

        altera_redacao = any(
            marcador in texto
            for marcador in (
                "passa a vigorar",
                "nova redação",
                "nova redacao",
                "alteração do art. 44",
                "alteracao do art. 44",
            )
        )

        if (
            menciona_artigo
            and altera_redacao
        ):
            circulares_alteradoras.append(
                item
            )

    if circulares_alteradoras:
        return circulares_alteradoras

    return relevantes


def _normalizar_linha_tabela(
    texto: str,
) -> str:
    """Normaliza texto somente para reconhecer cabeçalhos."""

    normalizado = unicodedata.normalize(
        "NFKD",
        texto,
    )

    normalizado = "".join(
        caractere
        for caractere in normalizado
        if not unicodedata.combining(
            caractere
        )
    )

    return " ".join(
        normalizado.casefold().split()
    )


def _extrair_tabela_coparticipacao_deterministica(
    trechos: list[dict[str, Any]],
) -> list[FaixaCoparticipacao]:
    """Lê linhas e percentuais diretamente do texto normativo."""

    linhas: list[str] = []

    for item in trechos:
        texto = str(
            item.get("texto")
            or ""
        )

        linhas.extend(
            linha.strip()
            for linha in texto.splitlines()
            if linha.strip()
        )

    intervalos: list[
        tuple[int | None, int | None]
    ] = []

    ultimo_cabecalho = -1

    for indice, linha in enumerate(linhas):

        normalizada = (
            _normalizar_linha_tabela(
                linha
            )
        )

        ate = re.fullmatch(
            r"ate\s+(\d+)\s+meses(?:\s+de\s+adesao)?",
            normalizada,
        )

        entre = re.fullmatch(
            r"de\s+(\d+)\s+a\s+(\d+)\s+meses",
            normalizada,
        )

        acima = re.fullmatch(
            r"acima\s+de\s+(\d+)\s+meses",
            normalizada,
        )

        if ate:
            intervalos.append(
                (
                    None,
                    int(ate.group(1)),
                )
            )
            ultimo_cabecalho = indice
            continue

        if entre:
            intervalos.append(
                (
                    int(entre.group(1)),
                    int(entre.group(2)),
                )
            )
            ultimo_cabecalho = indice
            continue

        if acima:
            intervalos.append(
                (
                    int(acima.group(1)),
                    None,
                )
            )
            ultimo_cabecalho = indice

    if (
        not intervalos
        or ultimo_cabecalho < 0
    ):
        return []

    percentual_re = re.compile(
        r"^(\d+(?:[.,]\d+)?)\s*%$"
    )

    quantidade_colunas = len(
        intervalos
    )

    resultado: list[
        FaixaCoparticipacao
    ] = []

    indice = ultimo_cabecalho + 1

    while indice < len(linhas):

        plano = linhas[indice].strip()

        if not plano:
            indice += 1
            continue

        percentuais: list[float] = []

        for deslocamento in range(
            1,
            quantidade_colunas + 1,
        ):

            posicao = indice + deslocamento

            if posicao >= len(linhas):
                break

            match = percentual_re.fullmatch(
                linhas[posicao].strip()
            )

            if not match:
                break

            percentual = float(
                match.group(1).replace(
                    ",",
                    ".",
                )
            ) / 100

            percentuais.append(
                percentual
            )

        if len(percentuais) != quantidade_colunas:
            indice += 1
            continue

        for (
            intervalo,
            percentual,
        ) in zip(
            intervalos,
            percentuais,
            strict=True,
        ):

            minimo, maximo = intervalo

            resultado.append(
                FaixaCoparticipacao(
                    plano=plano,
                    meses_min_exclusivo=minimo,
                    meses_max_inclusivo=maximo,
                    percentual=percentual,
                )
            )

        indice += (
            quantidade_colunas + 1
        )

    return resultado


def _extrair_faixas_coparticipacao(
    trechos: list[dict[str, Any]],
) -> list[FaixaCoparticipacao]:
    """Extrai a tabela completa em uma etapa especializada."""

    if not trechos:
        return []

    trechos = (
        _selecionar_trechos_coparticipacao(
            trechos
        )
    )

    if not trechos:
        return []

    possui_contexto = any(
        (
            "coparticip" in str(
                item.get("texto")
                or ""
            ).casefold()
        )
        for item in trechos
    )

    if not possui_contexto:
        return []

    faixas_deterministicas = (
        _extrair_tabela_coparticipacao_deterministica(
            trechos
        )
    )

    if faixas_deterministicas:
        return faixas_deterministicas

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        TabelaCoparticipacaoExtraida
    )

    contexto = [
        {
            "arquivo": item.get(
                "arquivo"
            ),
            "pagina": item.get(
                "pagina"
            ),
            "texto": str(
                item.get("texto")
                or ""
            ),
        }
        for item in trechos
    ]

    resultado = modelo.invoke(
        [
            (
                "system",
                SISTEMA_COPARTICIPACAO,
            ),
            (
                "human",
                (
                    "Extraia a tabela normativa completa "
                    "dos trechos abaixo:\n\n"
                    f"{contexto}"
                ),
            ),
        ]
    )

    if not isinstance(
        resultado,
        TabelaCoparticipacaoExtraida,
    ):
        raise TypeError(
            "Structured output não retornou "
            "TabelaCoparticipacaoExtraida."
        )

    unicas: list[
        FaixaCoparticipacao
    ] = []

    chaves: set[
        tuple[
            str,
            int | None,
            int | None,
            float,
        ]
    ] = set()

    for faixa in resultado.faixas:
        percentual = float(
            faixa.percentual
        )

        if 1 < percentual <= 100:
            percentual = (
                percentual / 100
            )

        faixa.percentual = percentual

        chave = (
            faixa.plano.strip().casefold(),
            faixa.meses_min_exclusivo,
            faixa.meses_max_inclusivo,
            round(
                faixa.percentual,
                10,
            ),
        )

        if chave in chaves:
            continue

        chaves.add(
            chave
        )

        unicas.append(
            faixa
        )

    # ------------------------------------------------------
    # Normalização determinística dos intervalos.
    #
    # Se o LLM preservar os limites inferiores das faixas,
    # mas omitir um limite superior intermediário, o início
    # da faixa seguinte define naturalmente esse fechamento.
    #
    # Nenhum número normativo é hardcoded aqui.
    # ------------------------------------------------------

    por_plano: dict[
        str,
        list[FaixaCoparticipacao],
    ] = {}

    for faixa in unicas:
        chave_plano = (
            faixa.plano
            .strip()
            .casefold()
        )

        por_plano.setdefault(
            chave_plano,
            [],
        ).append(
            faixa
        )

    normalizadas: list[
        FaixaCoparticipacao
    ] = []

    for faixas_plano in por_plano.values():

        ordenadas = sorted(
            faixas_plano,
            key=lambda faixa: (
                -1
                if faixa.meses_min_exclusivo
                is None
                else faixa.meses_min_exclusivo
            ),
        )

        for indice in range(
            len(ordenadas) - 1
        ):
            atual = ordenadas[indice]
            seguinte = ordenadas[
                indice + 1
            ]

            if (
                atual.meses_max_inclusivo
                is None
                and seguinte.meses_min_exclusivo
                is not None
            ):
                atual.meses_max_inclusivo = (
                    seguinte.meses_min_exclusivo
                )

        for faixa in ordenadas:
            minimo = (
                faixa.meses_min_exclusivo
            )

            maximo = (
                faixa.meses_max_inclusivo
            )

            if (
                minimo is not None
                and maximo is not None
                and maximo <= minimo
            ):
                raise ValueError(
                    "Faixa normativa de coparticipação "
                    "possui intervalo inválido."
                )

        normalizadas.extend(
            ordenadas
        )

    return normalizadas


def _extrair_proveniencias(
    *,
    parametros: ParametrosCalculo,
    dispositivos_permitidos: list[str],
    trechos: list[dict[str, Any]],
) -> list[ProvenienciaParametro]:
    """Extrai separadamente a proveniência normativa dos parâmetros."""

    proveniencias_iniciais = list(
        parametros.proveniencias
        or []
    )

    dados = parametros.model_dump(
        mode="json"
    )

    campos_derivados_runtime = {
        "saldo_anual_brl",
        "sessoes_utilizadas_ano",
        "percentual_coparticipacao",
        "proveniencias",
    }

    parametros_extraidos: dict[str, Any] = {}

    for campo, valor in dados.items():
        if campo in campos_derivados_runtime:
            continue

        if valor is None:
            continue

        if valor == [] or valor == {} or valor == "":
            continue

        if isinstance(valor, bool) and not valor:
            continue

        parametros_extraidos[campo] = valor

    if (
        not parametros_extraidos
        or not dispositivos_permitidos
    ):
        return []

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        MapaProveniencias
    )

    contexto = {
        "DISPOSITIVOS_CANONICOS_PERMITIDOS": (
            dispositivos_permitidos
        ),
        "PARAMETROS_NORMATIVOS_EXTRAIDOS": (
            parametros_extraidos
        ),
        "TRECHOS_RECUPERADOS": trechos,
    }

    resultado = modelo.invoke(
        [
            (
                "system",
                SISTEMA_PROVENIENCIA,
            ),
            (
                "human",
                (
                    "Mapeie a proveniência normativa "
                    "dos parâmetros abaixo:\n\n"
                    f"{contexto}"
                ),
            ),
        ]
    )

    if not isinstance(
        resultado,
        MapaProveniencias,
    ):
        raise TypeError(
            "Structured output não retornou "
            "MapaProveniencias."
        )

    campos_permitidos = set(
        parametros_extraidos
    )

    dispositivos_permitidos_set = set(
        dispositivos_permitidos
    )

    validas: list[ProvenienciaParametro] = []

    for item in resultado.proveniencias:
        campo = item.campo.strip()

        if campo not in campos_permitidos:
            continue

        dispositivos = [
            dispositivo
            for dispositivo in item.dispositivos
            if dispositivo
            in dispositivos_permitidos_set
        ]

        dispositivos = list(
            dict.fromkeys(dispositivos)
        )

        if not dispositivos:
            continue

        validas.append(
            ProvenienciaParametro(
                campo=campo,
                dispositivos=dispositivos,
            )
        )

    if not validas:
        for item in proveniencias_iniciais:

            campo = str(
                item.campo
            ).strip()

            if campo not in campos_permitidos:
                continue

            dispositivos = [
                dispositivo
                for dispositivo
                in item.dispositivos
                if dispositivo
                in dispositivos_permitidos_set
            ]

            dispositivos = list(
                dict.fromkeys(
                    dispositivos
                )
            )

            if not dispositivos:
                continue

            validas.append(
                ProvenienciaParametro(
                    campo=campo,
                    dispositivos=dispositivos,
                )
            )

    return validas



_MESES_VIGENCIA_CALCULO = {
    "janeiro": 1,
    "fevereiro": 2,
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


def _texto_sem_acentos(
    texto: str,
) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize(
            "NFD",
            texto,
        )
        if unicodedata.category(
            caractere
        ) != "Mn"
    )


def _numero_decimal_pt(
    valor: str,
) -> float:
    texto = str(valor).strip()

    if "," in texto:
        texto = (
            texto.replace(".", "")
            .replace(",", ".")
        )

    return float(texto)


def _extrair_vigencia_circular_calculo(
    texto: str,
) -> tuple[int, int, int] | None:
    normalizado = (
        _texto_sem_acentos(texto)
        .casefold()
    )

    match = re.search(
        r"inicio\s+de\s+vigencia\s*:\s*"
        r"(\d{1,2})(?:º|°)?\s+de\s+"
        r"([a-z]+)\s+de\s+(\d{4})",
        normalizado,
    )

    if not match:
        return None

    dia = int(match.group(1))
    mes = _MESES_VIGENCIA_CALCULO.get(
        match.group(2)
    )
    ano = int(match.group(3))

    if mes is None:
        return None

    return (
        ano,
        mes,
        dia,
    )


def _trechos_circular_mais_recente_calculo(
    resultados_rag: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    por_arquivo: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for item in resultados_rag:
        arquivo = str(
            item.get("arquivo")
            or ""
        )

        if "circular" not in arquivo.casefold():
            continue

        por_arquivo.setdefault(
            arquivo,
            [],
        ).append(
            item
        )

    vigencias: dict[
        str,
        tuple[int, int, int],
    ] = {}

    for arquivo, itens in por_arquivo.items():
        texto = "\n".join(
            str(
                item.get("texto")
                or ""
            )
            for item in itens
        )

        vigencia = (
            _extrair_vigencia_circular_calculo(
                texto
            )
        )

        if vigencia is not None:
            vigencias[arquivo] = vigencia

    if not vigencias:
        return []

    maior_vigencia = max(
        vigencias.values()
    )

    arquivos_recentes = {
        arquivo
        for arquivo, vigencia
        in vigencias.items()
        if vigencia == maior_vigencia
    }

    return [
        item
        for item in resultados_rag
        if str(
            item.get("arquivo")
            or ""
        ) in arquivos_recentes
    ]


def _dispositivo_circular_por_arquivo(
    arquivo: str,
) -> str | None:
    match = re.search(
        r"circular[_\-\s]*(\d+)"
        r"[_\-\s]*(\d{4})",
        arquivo,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    numero = int(
        match.group(1)
    )

    ano = match.group(2)

    return (
        f"CIRC-{numero:02d}-{ano}"
    )



def _extrair_limites_regulamento_deterministicos(
    resultados_rag: list[dict[str, Any]],
) -> tuple[set[int], set[float]]:
    """
    Extrai limites quantitativos e financeiros somente
    de artigos explícitos do Regulamento.
    """

    limites_sessoes: set[int] = set()
    limites_anuais_urs: set[float] = set()

    for item in resultados_rag:
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
                _texto_sem_acentos(
                    bloco
                )
                .casefold()
            )

            limite_sessoes = re.search(
                r"numero\s+de\s+sessoes"
                r".{0,180}?"
                r"limitad[oa]\s+a\s+"
                r"(\d+)",
                bloco_normalizado,
                flags=re.DOTALL,
            )

            if limite_sessoes:
                limites_sessoes.add(
                    int(
                        limite_sessoes.group(1)
                    )
                )

            limite_anual = re.search(
                r"somatorio\s+dos\s+reembolsos"
                r".{0,220}?"
                r"(?:nao\s+podera\s+exceder|"
                r"limitad[oa]\s+a)"
                r"\s+(\d+(?:[.,]\d+)?)"
                r"(?:\s*\([^)]*\))?"
                r"\s+urs",
                bloco_normalizado,
                flags=re.DOTALL,
            )

            if limite_anual:
                limites_anuais_urs.add(
                    _numero_decimal_pt(
                        limite_anual.group(1)
                    )
                )

    return (
        limites_sessoes,
        limites_anuais_urs,
    )




def _normalizar_parametros_normativos(
    *,
    resultado: ParametrosCalculo,
    resultados_rag: list[dict[str, Any]],
    dispositivos_permitidos_set: set[str],
) -> None:
    """
    Corrige parâmetros que podem variar na extração do LLM
    usando somente valores explicitamente presentes nas normas.
    """

    texto_total = "\n".join(
        str(
            item.get("texto")
            or ""
        )
        for item in resultados_rag
    )

    # ------------------------------------------------------
    # Valor monetário da URS.
    # ------------------------------------------------------

    valores_urs = {
        round(
            _numero_decimal_pt(valor),
            10,
        )
        for valor in re.findall(
            r"\b1\s*URS\s*=\s*R\$\s*"
            r"(\d+(?:[.,]\d+)?)",
            texto_total,
            flags=re.IGNORECASE,
        )
    }

    if len(valores_urs) == 1:
        resultado.valor_urs_brl = (
            next(iter(valores_urs))
        )

    (
        limites_sessoes,
        limites_anuais_urs,
    ) = _extrair_limites_regulamento_deterministicos(
        resultados_rag
    )

    if len(limites_sessoes) == 1:
        resultado.limite_sessoes_ano = (
            next(iter(limites_sessoes))
        )

    if len(limites_anuais_urs) == 1:
        resultado.limite_anual_urs = (
            next(iter(limites_anuais_urs))
        )

    # ------------------------------------------------------
    # Circular de vigência mais recente já presente no
    # contexto normativo aplicável.
    # ------------------------------------------------------

    circular_atual = (
        _trechos_circular_mais_recente_calculo(
            resultados_rag
        )
    )

    if not circular_atual:
        return

    texto_atual = "\n".join(
        str(
            item.get("texto")
            or ""
        )
        for item in circular_atual
    )

    normalizado_atual = (
        _texto_sem_acentos(
            texto_atual
        )
        .casefold()
    )

    # ------------------------------------------------------
    # Teto-base explicitamente dado por nova redação.
    # Ex.: “Art. X. ... tem teto de N URS ...”
    # ------------------------------------------------------

    tetos_base = {
        round(
            _numero_decimal_pt(
                quantidade
            ),
            10,
        )
        for _, quantidade in re.findall(
            r'[“"]\s*Art\.\s*(\d+)\.\s*'
            r'.{0,700}?'
            r'\btem\s+teto\s+de\s*'
            r'(\d+(?:[.,]\d+)?)\s*URS',
            texto_atual,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )
    }

    if len(tetos_base) == 1:
        resultado.quantidade_urs = (
            next(iter(tetos_base))
        )

    # ------------------------------------------------------
    # Teto condicional.
    # O valor vem da circular atual.
    # A definição de quantidade de sessões pode estar em
    # norma anterior quando a emenda diz que a mantém.
    # ------------------------------------------------------

    valores_condicionais = {
        round(
            _numero_decimal_pt(valor),
            10,
        )
        for valor in re.findall(
            r"nessa\s+hipotese\s+"
            r"o\s+teto\s+e\s+de\s*"
            r"(\d+(?:[.,]\d+)?)\s*urs",
            normalizado_atual,
        )
    }

    texto_total_normalizado = (
        _texto_sem_acentos(
            texto_total
        )
        .casefold()
    )

    minimos_sessoes = {
        int(valor)
        for valor in re.findall(
            r"pelo\s+menos\s+(\d+)"
            r"(?:\s*\([^)]*\))?"
            r"\s+sessoes\s+realizadas"
            r"\s+no\s+ano\s+civil",
            texto_total_normalizado,
        )
    }

    if len(valores_condicionais) == 1:
        sessoes_min = (
            next(
                iter(minimos_sessoes)
            )
            if len(minimos_sessoes) == 1
            else None
        )

        resultado.tetos_urs_condicionais = [
            TetoURSCondicional(
                sessoes_min_inclusivo=(
                    sessoes_min
                ),
                sessoes_max_inclusivo=None,
                quantidade_urs=next(
                    iter(
                        valores_condicionais
                    )
                ),
            )
        ]

    # ------------------------------------------------------
    # Requisito documental condicional.
    # Condições alternativas:
    # - sessão mínima;
    # - percentual acima do teto.
    # ------------------------------------------------------

    sessoes_relatorio = {
        int(valor)
        for valor in re.findall(
            r"sessao\s+for\s+a\s+"
            r"(\d+)(?:a|ª|º)?"
            r"\s+ou\s+posterior",
            normalizado_atual,
        )
    }

    percentuais_relatorio = {
        round(
            _numero_decimal_pt(valor),
            10,
        )
        for valor in re.findall(
            r"exceder\s+em\s+mais\s+de\s+"
            r"(\d+(?:[.,]\d+)?)\s*%",
            normalizado_atual,
        )
    }

    documento_match = re.search(
        r"(relat[oó]rio\s+cl[ií]nico)",
        texto_atual,
        flags=re.IGNORECASE,
    )

    if (
        documento_match
        and len(sessoes_relatorio) == 1
        and len(percentuais_relatorio) == 1
    ):
        percentual = next(
            iter(
                percentuais_relatorio
            )
        )

        if 1 < percentual <= 100:
            percentual = (
                percentual / 100
            )

        dispositivos: list[str] = []

        arquivos_circular = {
            str(
                item.get("arquivo")
                or ""
            )
            for item in circular_atual
        }

        for arquivo in arquivos_circular:
            dispositivo = (
                _dispositivo_circular_por_arquivo(
                    arquivo
                )
            )

            if (
                dispositivo
                and dispositivo
                in dispositivos_permitidos_set
            ):
                dispositivos.append(
                    dispositivo
                )

        artigo_match = re.search(
            r"§\s*\d+º?\s+do\s+art\.\s*"
            r"(\d+)"
            r".{0,700}?"
            r"relat[oó]rio\s+cl[ií]nico",
            texto_atual,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if artigo_match:
            dispositivo_artigo = (
                f"ART-{artigo_match.group(1)}"
            )

            if (
                dispositivo_artigo
                in dispositivos_permitidos_set
            ):
                dispositivos.append(
                    dispositivo_artigo
                )

        dispositivos = list(
            dict.fromkeys(
                dispositivos
            )
        )

        resultado.requisitos_documentais_condicionais = [
            RequisitoDocumentoCondicional(
                documento=(
                    documento_match.group(1)
                ),
                categoria_documento=None,
                sessoes_min_inclusivo=next(
                    iter(
                        sessoes_relatorio
                    )
                ),
                excedente_teto_percentual=(
                    percentual
                ),
                operador="OR",
                dispositivos=dispositivos,
            )
        ]



def _selecionar_trechos_calculo(
    resultados_rag: list[dict[str, Any]],
    *,
    fontes_descartadas: set[str] | None = None,
    max_trechos: int = 8,
    max_caracteres_por_trecho: int = 2500,
) -> list[dict[str, Any]]:
    """Seleciona contexto relevante de cálculo sem enviar o RAG inteiro."""

    termos = (
        "urs",
        "teto",
        "apuração",
        "coparticip",
        "limite anual",
        "saldo",
        "sessões",
        "arredond",
        "alçada",
        "protocolo",
    )

    candidatos: list[
        tuple[int, int, dict[str, Any]]
    ] = []

    fontes_descartadas = fontes_descartadas or set()

    for posicao, item in enumerate(resultados_rag):
        arquivo = str(
            item.get("arquivo") or ""
        )

        if arquivo in fontes_descartadas:
            continue

        texto = str(
            item.get("texto") or ""
        )

        texto_normalizado = texto.casefold()

        pontuacao = sum(
            1
            for termo in termos
            if termo in texto_normalizado
        )

        candidatos.append(
            (
                pontuacao,
                -posicao,
                {
                    "arquivo": item.get("arquivo"),
                    "pagina": item.get("pagina"),
                    "texto": texto[
                        :max_caracteres_por_trecho
                    ],
                },
            )
        )

    candidatos.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    return [
        item[2]
        for item in candidatos[:max_trechos]
    ]


def extrair_parametros_calculo(
    resolucao_normativa: dict[str, Any],
    resultados_rag: list[dict[str, Any]],
) -> ParametrosCalculo:
    """Converte contexto normativo em parâmetros estruturados."""

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        ParametrosCalculo
    )

    # resultados_rag já contém somente os trechos considerados
    # aplicáveis pelo agente de normas. Não descarte novamente
    # um arquivo inteiro nesta etapa de extração.
    trechos = _selecionar_trechos_calculo(
        resultados_rag,
    )

    dispositivos_permitidos = [
        str(item)
        for item in (
            resolucao_normativa.get(
                "dispositivos_canonicos"
            )
            or []
        )
        if item
    ]

    contexto = {
        "DISPOSITIVOS_CANONICOS_PERMITIDOS": (
            dispositivos_permitidos
        ),
        "resolucao_normativa": resolucao_normativa,
        "trechos_recuperados": trechos,
    }

    resultado = modelo.invoke(
        [
            (
                "system",
                SISTEMA,
            ),
            (
                "human",
                (
                    "Extraia os parâmetros de cálculo "
                    "do contexto abaixo:\n\n"
                    f"{contexto}"
                ),
            ),
        ]
    )

    if not isinstance(
        resultado,
        ParametrosCalculo,
    ):
        raise TypeError(
            "Structured output não retornou ParametrosCalculo."
        )

    dispositivos_permitidos_set = set(
        dispositivos_permitidos
    )

    _normalizar_parametros_normativos(
        resultado=resultado,
        resultados_rag=resultados_rag,
        dispositivos_permitidos_set=(
            dispositivos_permitidos_set
        ),
    )

    faixas_coparticipacao = (
        _extrair_faixas_coparticipacao(
            trechos
        )
    )

    if faixas_coparticipacao:
        resultado.faixas_coparticipacao = (
            faixas_coparticipacao
        )

    for requisito in (
        resultado.requisitos_documentais_condicionais
    ):
        if (
            requisito.excedente_teto_percentual
            is not None
            and 1
            < requisito.excedente_teto_percentual
            <= 100
        ):
            requisito.excedente_teto_percentual = (
                requisito.excedente_teto_percentual
                / 100
            )

        categoria_exigida = (
            classificar_categoria_documento_exigido(
                requisito.documento
            )
        )

        requisito.categoria_documento = (
            categoria_exigida
            if categoria_exigida is not None
            else None
        )

        requisito.dispositivos = list(
            dict.fromkeys(
                dispositivo
                for dispositivo in requisito.dispositivos
                if dispositivo
                in dispositivos_permitidos_set
            )
        )

    resultado.proveniencias = (
        _extrair_proveniencias(
            parametros=resultado,
            dispositivos_permitidos=(
                dispositivos_permitidos
            ),
            trechos=trechos,
        )
    )

    return resultado
