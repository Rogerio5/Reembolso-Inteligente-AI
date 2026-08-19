"""Auditoria das regras normativas efetivamente aplicadas ao resultado."""

from __future__ import annotations

import re
import unicodedata

from typing import Any

from pydantic import BaseModel, Field

from app.llm import criar_llm


class RegraAuditada(BaseModel):
    """Dispositivo e seu efeito concreto no caso."""

    dispositivo: str
    efeito_concreto: str


class AuditoriaRegras(BaseModel):
    """Resultado estruturado da auditoria normativa final."""

    regras: list[RegraAuditada] = Field(
        default_factory=list
    )


SISTEMA = """
Você audita quais dispositivos normativos foram EFETIVAMENTE usados
para produzir o resultado final de um pedido de reembolso.

Você não decide novamente o caso.

Regras obrigatórias:

1. Use somente os dispositivos candidatos fornecidos.
2. Nunca invente artigo, circular, nota técnica, anexo ou código TUSS.
3. Um dispositivo só pode permanecer se tiver efeito concreto sobre:
   - decisão final;
   - valor calculado;
   - teto aplicável;
   - coparticipação;
   - limite anual;
   - pendência documental;
   - elegibilidade/cobertura;
   - análise humana;
   - escalonamento;
   - abertura de protocolo.
4. Não mantenha dispositivo apenas porque apareceu no RAG.
5. Não mantenha dispositivo meramente conceitual, introdutório,
   contextual ou pertencente a outra categoria.
6. Não mantenha exceção que não tenha sido acionada.
7. Aplique o teste contrafactual:
   se remover o dispositivo não puder alterar decisão, valor,
   pendência, escalonamento ou protocolo deste caso concreto,
   ele não deve permanecer.
8. Preserve exatamente o identificador canônico recebido nos
   DISPOSITIVOS CANDIDATOS.
9. Use OPERACOES EFETIVAMENTE EXECUTADAS PELO MOTOR como evidência
   autoritativa do que realmente participou da apuração.
10. Para determinar_teto_procedimento, preserve a regra específica que
    fixa o teto do procedimento efetivamente analisado e somente as
    regras de conversão que tenham sido realmente necessárias.
11. Se PARAMETROS_UTILIZADOS contiver teto_brl, mas não contiver
    valor_urs_brl nem quantidade_urs, não mantenha uma regra apenas
    porque ela define o valor geral da URS.
12. Para apurar_menor_valor, preserve a regra que determina a comparação
    entre o valor efetivamente pago e o teto aplicável.
13. Para aplicar_coparticipacao, preserve a regra que determina o
    percentual ou a tabela de coparticipação efetivamente utilizada.
14. Para arredondar_valor_final, preserve a regra que determina o
    arredondamento final realmente executado.
15. Só preserve regra de limite anual quando a operação
    limitar_por_saldo_anual estiver entre as operações executadas.
16. Não preserve regra documental condicional quando não houver
    pendência documental e nenhuma condição documental tiver sido
    efetivamente acionada.
17. Não preserve regra de análise humana, alçada ou protocolo quando o
    caso não tiver sido escalado e nenhum protocolo tiver sido aberto.
18. Não preserve regra geral ou conceitual quando existir regra mais
    específica que sustente diretamente a operação executada.
19. Uma regra que apenas foi recuperada ou extraída como parâmetro, mas
    não alterou decisão, valor, pendência, escalonamento ou protocolo,
    deve ser removida.
20. Não faça diagnóstico clínico.
"""


def _formatar_trechos(
    resultados_rag: list[dict[str, Any]],
) -> str:
    """Reduz os trechos RAG para a auditoria final."""

    blocos: list[str] = []

    for item in resultados_rag[:10]:
        arquivo = str(
            item.get("arquivo")
            or "desconhecido"
        )

        pagina = item.get("pagina")

        texto = str(
            item.get("texto")
            or ""
        ).strip()

        if len(texto) > 1800:
            texto = texto[:1800]

        blocos.append(
            f"ARQUIVO: {arquivo}\n"
            f"PAGINA: {pagina}\n"
            f"{texto}"
        )

    return "\n\n---\n\n".join(blocos)


ORIGENS_PARAMETROS_DERIVADOS = {
    "percentual_coparticipacao": {
        "percentual_coparticipacao",
        "faixas_coparticipacao",
    },
    "quantidade_urs": {
        "quantidade_urs",
        "tetos_urs_condicionais",
    },
}


def obter_regras_obrigatorias(
    *,
    parametros_utilizados: list[str],
    parametros_calculo: dict[str, Any],
) -> list[str]:
    """Obtém regras que sustentam parâmetros realmente usados."""

    proveniencias = (
        parametros_calculo.get("proveniencias")
        or []
    )

    campos_necessarios: set[str] = set()

    for campo in parametros_utilizados:
        campos_necessarios.add(campo)

        campos_necessarios.update(
            ORIGENS_PARAMETROS_DERIVADOS.get(
                campo,
                set(),
            )
        )

    regras: list[str] = []

    for item in proveniencias:
        if not isinstance(item, dict):
            continue

        campo = str(
            item.get("campo")
            or ""
        ).strip()

        if campo not in campos_necessarios:
            continue

        for dispositivo in (
            item.get("dispositivos")
            or []
        ):
            dispositivo = str(
                dispositivo
            ).strip()

            if (
                dispositivo
                and dispositivo not in regras
            ):
                regras.append(
                    dispositivo
                )

    return regras


def _filtrar_candidatos_por_parametros_ativos(
    *,
    candidatos: list[str],
    parametros_utilizados: list[str],
    parametros_calculo: dict[str, Any],
) -> list[str]:
    """Remove regras ligadas somente a parâmetros não utilizados."""

    campos_ativos: set[str] = set()

    for campo in parametros_utilizados:
        campos_ativos.add(campo)

        campos_ativos.update(
            ORIGENS_PARAMETROS_DERIVADOS.get(
                campo,
                set(),
            )
        )

    proveniencias = (
        parametros_calculo.get(
            "proveniencias"
        )
        or []
    )

    campos_por_dispositivo: dict[
        str,
        set[str],
    ] = {}

    for item in proveniencias:
        if not isinstance(item, dict):
            continue

        campo = str(
            item.get("campo")
            or ""
        ).strip()

        if not campo:
            continue

        for dispositivo in (
            item.get("dispositivos")
            or []
        ):
            dispositivo = str(
                dispositivo
            ).strip()

            if not dispositivo:
                continue

            campos_por_dispositivo.setdefault(
                dispositivo,
                set(),
            ).add(
                campo
            )

    filtrados: list[str] = []

    for dispositivo in candidatos:

        campos = campos_por_dispositivo.get(
            dispositivo
        )

        # Sem proveniência parametrizada:
        # permanece candidato para auditoria das operações.
        if not campos:
            filtrados.append(
                dispositivo
            )
            continue

        # Mantém somente se alguma proveniência
        # realmente participou do cálculo.
        if campos & campos_ativos:
            filtrados.append(
                dispositivo
            )

    return list(
        dict.fromkeys(
            filtrados
        )
    )


def _normalizar_semantica(
    texto: str,
) -> str:
    """Normaliza texto para análise semântica determinística."""

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

    return normalizado.casefold()


def _secoes_por_artigo(
    texto: str,
) -> list[tuple[str, str]]:
    """Separa artigos iniciados explicitamente no texto normativo."""

    padrao = re.compile(
        r"(?im)^\s*art\.\s*(\d+)[ºo]?\b"
    )

    matches = list(
        padrao.finditer(texto)
    )

    secoes: list[
        tuple[str, str]
    ] = []

    for indice, match in enumerate(
        matches
    ):
        inicio = match.start()

        fim = (
            matches[indice + 1].start()
            if indice + 1 < len(matches)
            else len(texto)
        )

        secoes.append(
            (
                f"ART-{match.group(1)}",
                texto[inicio:fim],
            )
        )

    return secoes


def _regras_tuss_explicitas(
    *,
    codigo_tuss: str | None,
    resultados_rag: list[dict[str, Any]],
) -> list[str]:
    """Extrai regra explicitamente ligada ao registro do TUSS."""

    codigo = str(
        codigo_tuss
        or ""
    ).strip()

    if not codigo:
        return []

    regras: list[str] = []

    for item in resultados_rag:
        texto = str(
            item.get("texto")
            or ""
        )

        inicio = texto.find(codigo)

        if inicio < 0:
            continue

        depois_codigo = inicio + len(codigo)

        proximo_codigo = re.search(
            rf"\b\d{{{len(codigo)}}}\b",
            texto[depois_codigo:],
        )

        if proximo_codigo:
            fim = (
                depois_codigo
                + proximo_codigo.start()
            )
        else:
            fim = min(
                len(texto),
                depois_codigo + 700,
            )

        registro = texto[inicio:fim]

        registro_normalizado = (
            _normalizar_semantica(
                registro
            )
        )

        artigos = re.findall(
            r"teto\s+do\s+art\.\s*(\d+)",
            registro_normalizado,
        )

        for numero in artigos:
            dispositivo = f"ART-{numero}"

            if dispositivo not in regras:
                regras.append(
                    dispositivo
                )

    return regras


def _regra_tuss_especifica(
    *,
    codigo_tuss: str | None,
    candidatos: set[str],
    resultados_rag: list[dict[str, Any]],
) -> list[str]:
    """Mantém regras TUSS explícitas entre candidatos válidos."""

    return [
        dispositivo
        for dispositivo
        in _regras_tuss_explicitas(
            codigo_tuss=codigo_tuss,
            resultados_rag=resultados_rag,
        )
        if dispositivo in candidatos
    ]


def _auditoria_operacional_deterministica(
    *,
    candidatos: list[str],
    resultados_rag: list[dict[str, Any]],
    operacoes_utilizadas: list[str],
    codigo_tuss: str | None,
) -> list[str]:
    """Relaciona operações executadas às regras normativas."""

    permitidos = set(
        candidatos
    )

    regras: list[str] = []

    def adicionar(
        dispositivo: str,
    ) -> None:

        if (
            dispositivo in permitidos
            and dispositivo not in regras
        ):
            regras.append(
                dispositivo
            )

    # --------------------------------------------------------
    # Teto específico identificado pela própria linha TUSS.
    # --------------------------------------------------------

    if (
        "determinar_teto_procedimento"
        in operacoes_utilizadas
    ):
        for dispositivo in (
            _regra_tuss_especifica(
                codigo_tuss=codigo_tuss,
                candidatos=permitidos,
                resultados_rag=resultados_rag,
            )
        ):
            adicionar(
                dispositivo
            )

    # --------------------------------------------------------
    # Análise dos próprios textos normativos.
    # --------------------------------------------------------

    for item in resultados_rag:

        texto = str(
            item.get("texto")
            or ""
        )

        texto_normalizado = (
            _normalizar_semantica(
                texto
            )
        )

        secoes = (
            _secoes_por_artigo(
                texto
            )
        )

        # ----------------------------------------------------
        # Determinação do teto do procedimento.
        # Exige referência explícita ao procedimento,
        # evitando regras genéricas de URS.
        # ----------------------------------------------------

        if (
            "determinar_teto_procedimento"
            in operacoes_utilizadas
        ):
            for dispositivo, secao in secoes:

                secao_normalizada = (
                    _normalizar_semantica(
                        secao
                    )
                )

                especifica_teto = (
                    "teto de cada procedimento"
                    in secao_normalizada
                    or (
                        "teto" in secao_normalizada
                        and "procedimento"
                        in secao_normalizada
                        and "multiplic"
                        in secao_normalizada
                    )
                )

                if especifica_teto:
                    adicionar(
                        dispositivo
                    )

        # ----------------------------------------------------
        # Comparação entre valor pago e teto.
        #
        # Também aproveita referências explícitas como
        # "apuração do art. N", sem conhecer N previamente.
        # ----------------------------------------------------

        if (
            "apurar_menor_valor"
            in operacoes_utilizadas
        ):

            for dispositivo, secao in secoes:

                secao_normalizada = (
                    _normalizar_semantica(
                        secao
                    )
                )

                compara_valores = (
                    "valor pago"
                    in secao_normalizada
                    and "teto"
                    in secao_normalizada
                ) or (
                    "menor"
                    in secao_normalizada
                    and "teto"
                    in secao_normalizada
                )

                if compara_valores:
                    adicionar(
                        dispositivo
                    )

            referencias = re.findall(
                r"apuracao.{0,140}art\.\s*(\d+)",
                texto_normalizado,
            )

            for numero in referencias:
                adicionar(
                    f"ART-{numero}"
                )

        # ----------------------------------------------------
        # Coparticipação.
        # ----------------------------------------------------

        if (
            "aplicar_coparticipacao"
            in operacoes_utilizadas
        ):

            for dispositivo, secao in secoes:

                secao_normalizada = (
                    _normalizar_semantica(
                        secao
                    )
                )

                if (
                    "coparticip"
                    in secao_normalizada
                ):
                    adicionar(
                        dispositivo
                    )

            # Normas posteriores podem dizer que a tabela
            # de determinado artigo passa a vigorar com
            # novos percentuais. Capturamos esse artigo.
            referencias = re.findall(
                r"tabela.{0,180}art\.\s*(\d+)",
                texto_normalizado,
            )

            for numero in referencias:
                adicionar(
                    f"ART-{numero}"
                )

        # ----------------------------------------------------
        # Arredondamento final.
        # ----------------------------------------------------

        if (
            "arredondar_valor_final"
            in operacoes_utilizadas
        ):

            for dispositivo, secao in secoes:

                if (
                    "arredond"
                    in _normalizar_semantica(
                        secao
                    )
                ):
                    adicionar(
                        dispositivo
                    )

        # ----------------------------------------------------
        # Limite anual somente quando realmente executado.
        # ----------------------------------------------------

        if (
            "limitar_por_saldo_anual"
            in operacoes_utilizadas
        ):

            for dispositivo, secao in secoes:

                secao_normalizada = (
                    _normalizar_semantica(
                        secao
                    )
                )

                if (
                    "limite anual"
                    in secao_normalizada
                    or "saldo anual"
                    in secao_normalizada
                ):
                    adicionar(
                        dispositivo
                    )

    return regras


def auditar_regras_aplicadas(
    *,
    dispositivos_candidatos: list[str],
    resultados_rag: list[dict[str, Any]],
    parametros_calculo: dict[str, Any],
    parametros_utilizados: list[str],
    operacoes_utilizadas: list[str],
    codigo_tuss: str | None,
    decisao: str | None,
    valor_solicitado_brl: float | None,
    valor_reembolso_brl: float | None,
    pendencias: list[str],
    protocolo: str | None,
) -> list[str]:
    """Mantém somente dispositivos com efeito concreto no resultado."""

    candidatos = list(
        dict.fromkeys(
            str(item)
            for item in dispositivos_candidatos
            if item
        )
    )

    regras_tuss_explicitas = (
        _regras_tuss_explicitas(
            codigo_tuss=codigo_tuss,
            resultados_rag=resultados_rag,
        )
    )

    regras_proveniencia_operacoes: list[str] = []

    if (
        "aplicar_coparticipacao"
        in operacoes_utilizadas
    ):
        regras_proveniencia_operacoes.extend(
            obter_regras_obrigatorias(
                parametros_utilizados=[
                    "percentual_coparticipacao"
                ],
                parametros_calculo=(
                    parametros_calculo
                ),
            )
        )

    regras_referenciadas_operacoes: list[str] = []

    for item in resultados_rag:
        texto = str(
            item.get("texto")
            or ""
        )

        secoes = _secoes_por_artigo(
            texto
        )

        for _, secao in secoes:
            secao_normalizada = (
                _normalizar_semantica(
                    secao
                )
            )

            referencias: list[str] = []

            if (
                "apurar_menor_valor"
                in operacoes_utilizadas
                and "apuracao"
                in secao_normalizada
                and (
                    "valor pago"
                    in secao_normalizada
                    or "menor"
                    in secao_normalizada
                    or "teto"
                    in secao_normalizada
                )
            ):
                referencias.extend(
                    re.findall(
                        r"apuracao.{0,140}art\.\s*(\d+)",
                        secao_normalizada,
                    )
                )

            if (
                "aplicar_coparticipacao"
                in operacoes_utilizadas
                and "coparticip"
                in secao_normalizada
            ):
                referencias.extend(
                    re.findall(
                        r"tabela.{0,180}art\.\s*(\d+)",
                        secao_normalizada,
                    )
                )

            for numero in referencias:
                dispositivo = (
                    f"ART-{numero}"
                )

                if (
                    dispositivo
                    not in regras_referenciadas_operacoes
                ):
                    regras_referenciadas_operacoes.append(
                        dispositivo
                    )

    candidatos = list(
        dict.fromkeys(
            [
                *candidatos,
                *regras_tuss_explicitas,
                *regras_referenciadas_operacoes,
                *regras_proveniencia_operacoes,
            ]
        )
    )

    candidatos = (
        _filtrar_candidatos_por_parametros_ativos(
            candidatos=candidatos,
            parametros_utilizados=(
                parametros_utilizados
            ),
            parametros_calculo=(
                parametros_calculo
            ),
        )
    )

    if not candidatos:
        return []

    regras_deterministicas = (
        _auditoria_operacional_deterministica(
            candidatos=candidatos,
            resultados_rag=resultados_rag,
            operacoes_utilizadas=(
                operacoes_utilizadas
            ),
            codigo_tuss=codigo_tuss,
        )
    )

    if (
        operacoes_utilizadas
        and regras_deterministicas
    ):
        return list(
            dict.fromkeys(
                [
                    *regras_deterministicas,
                    *regras_proveniencia_operacoes,
                ]
            )
        )

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        AuditoriaRegras
    )

    usuario = f"""
DISPOSITIVOS CANDIDATOS:
{candidatos}

RESULTADO FINAL:
DECISAO: {decisao}
VALOR_SOLICITADO_BRL: {valor_solicitado_brl}
VALOR_REEMBOLSO_BRL: {valor_reembolso_brl}
PENDENCIAS: {pendencias}
PROTOCOLO_ABERTO: {bool(protocolo)}

PARAMETROS UTILIZADOS PELO MOTOR:
{parametros_utilizados}

PARAMETROS EFETIVAMENTE APURADOS:
{parametros_calculo}

OPERACOES EFETIVAMENTE EXECUTADAS PELO MOTOR:
{operacoes_utilizadas}

TRECHOS NORMATIVOS RECUPERADOS:
{_formatar_trechos(resultados_rag)}

Selecione somente os dispositivos candidatos que tenham efeito
concreto sobre esse resultado final.
Para cada dispositivo mantido, explique resumidamente qual foi
esse efeito.
"""

    resultado = modelo.invoke(
        [
            ("system", SISTEMA),
            ("human", usuario),
        ]
    )

    if not isinstance(
        resultado,
        AuditoriaRegras,
    ):
        raise TypeError(
            "Structured output não retornou AuditoriaRegras."
        )

    permitidos = set(candidatos)

    mantidos: list[str] = []

    for regra in resultado.regras:
        dispositivo = regra.dispositivo.strip()

        if (
            dispositivo in permitidos
            and dispositivo not in mantidos
        ):
            mantidos.append(
                dispositivo
            )

    return mantidos
