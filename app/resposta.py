"""Resposta conversacional segura e contextual."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.guardrails import (
    pergunta_dado_clinico,
    resposta_dado_clinico,
    sanitizar_resposta,
)
from app.llm import criar_llm
from app.rag.retriever import buscar_normas


SISTEMA = """
Você é a camada de comunicação de um agente de reembolso.

Sua tarefa é responder EXATAMENTE à mensagem atual do beneficiário,
levando em conta o estado acumulado da sessão.

Regras obrigatórias:

1. Responda à pergunta atual antes de repetir o status do pedido.
2. Nunca invente decisão, valor, regra, protocolo ou dado do plano.
3. Nunca reproduza CPF completo.
4. Nunca reproduza número completo de carteirinha.
5. Nunca reproduza CID, hipótese diagnóstica ou diagnóstico.
6. Nunca revele informação de outro beneficiário.
7. Se a pessoa perguntar POR QUE existe uma pendência, explique o motivo
   usando o contexto normativo recuperado.
8. Se perguntar prazo, cobertura, regra ou motivo, responda essa pergunta
   usando somente os trechos normativos fornecidos.
9. Se o pedido já tiver decisão e a pessoa perguntar valor, informe o
   valor já calculado.
10. Se o pedido estiver escalado, diga que depende de análise humana e
    nunca antecipe valor.
11. Não transforme toda mensagem em pedido de documento.
12. Não peça novamente a carteirinha se ela já foi validada na sessão.
13. Não repita palavra por palavra nenhuma resposta anterior.
14. Se o beneficiário corrigir verbalmente um dado que tem como fonte
    obrigatória o documento ou o MCP, explique qual fonte prevalece.
15. Seja natural, direto e específico para a mensagem atual.
"""


def _moeda(valor: Any) -> str | None:
    if valor is None:
        return None

    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None

    return (
        f"R$ {numero:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _normalizar_comparacao(texto: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(texto or "").strip().casefold(),
    )


def _respostas_anteriores(
    historico: list[dict[str, Any]],
) -> list[str]:
    respostas: list[str] = []

    for item in historico:
        if not isinstance(item, dict):
            continue

        if item.get("role") != "assistant":
            continue

        conteudo = sanitizar_resposta(
            str(item.get("content") or "")
        )

        if conteudo:
            respostas.append(conteudo)

    return respostas[-6:]


def _eh_repetida(
    resposta: str,
    anteriores: list[str],
) -> bool:
    atual = _normalizar_comparacao(resposta)

    if not atual:
        return True

    return any(
        atual == _normalizar_comparacao(item)
        for item in anteriores
    )


def _formatar_rag(
    resultados: list[dict[str, Any]],
) -> str:
    blocos: list[str] = []

    for item in resultados[:4]:
        texto = str(
            item.get("texto")
            or ""
        ).strip()

        if not texto:
            continue

        arquivo = str(
            item.get("arquivo")
            or "fonte normativa"
        )

        pagina = item.get("pagina")

        blocos.append(
            (
                f"FONTE: {arquivo}\n"
                f"PÁGINA: {pagina}\n"
                f"TRECHO:\n{texto[:1800]}"
            )
        )

    return "\n\n---\n\n".join(blocos)



def _parece_identificador_carteirinha(
    mensagem: str,
) -> bool:
    """Detecta fornecimento de identificador numérico sem conhecer o caso."""
    digitos = re.sub(
        r"\D",
        "",
        str(mensagem or ""),
    )

    return len(digitos) >= 8






def _mensagem_sobre_historico_anual_reembolso(
    mensagem: str,
) -> bool:
    """Detecta dúvida sobre efeito de reembolsos anteriores no ano."""
    texto = str(
        mensagem
        or ""
    ).casefold()

    menciona_periodo_ou_saldo = any(
        termo in texto
        for termo in (
            "ano",
            "anual",
            "saldo",
            "limite",
        )
    )

    menciona_historico = any(
        termo in texto
        for termo in (
            "reembolso",
            "reembolsos",
            "pedi",
            "pedido",
            "pedidos",
            "outras vezes",
            "outros",
            "outras",
            "vezes",
        )
    )

    return (
        menciona_periodo_ou_saldo
        and menciona_historico
    )




def _mensagem_pergunta_status_pedido(
    mensagem: str,
) -> bool:
    """Detecta pergunta sobre aprovação/liberação do pedido."""
    texto = str(
        mensagem
        or ""
    ).casefold()

    if "deu certo" in texto:
        return True

    return bool(
        re.search(
            r"\b(?:"
            r"sai|sair|saiu|"
            r"aprovado|aprovada|"
            r"liberado|liberada"
            r")\b",
            texto,
        )
    )




def _mensagem_sobre_documento_pendente(
    mensagem: str,
) -> bool:
    """Detecta quando o beneficiário pergunta sobre o complemento pendente."""
    texto = str(
        mensagem
        or ""
    ).casefold()

    return any(
        termo in texto
        for termo in (
            "relat",
            "document",
            "papel",
            "laudo",
            "atestado",
            "complement",
        )
    )




def _mensagem_sobre_quantidade_sessoes(
    mensagem: str,
) -> bool:
    """Detecta dúvida do beneficiário sobre quantidade de sessões."""
    texto = str(
        mensagem
        or ""
    ).casefold()

    menciona_sessao = any(
        termo in texto
        for termo in (
            "sessão",
            "sessao",
            "sessões",
            "sessoes",
        )
    )

    menciona_quantidade = any(
        termo in texto
        for termo in (
            "quant",
            "número",
            "numero",
            "cont",
            "fiz",
            "realizei",
        )
    )

    return (
        menciona_sessao
        and menciona_quantidade
    )




def _mensagem_sobre_prazo_reanalise(
    mensagem: str,
) -> bool:
    """Identifica dúvida procedimental sobre prazo/reanálise."""
    texto = str(
        mensagem
        or ""
    ).casefold()

    return any(
        termo in texto
        for termo in (
            "prazo",
            "reanal",
            "recorr",
            "recurso",
            "indefer",
        )
    )




async def _buscar_contexto(
    state: dict[str, Any],
    mensagem: str,
) -> str:
    if not mensagem.strip():
        return ""

    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    documento_processado = bool(
        state.get("dados_documento")
        or state.get("categoria_documento")
    )

    categoria = state.get(
        "categoria_documento"
    )

    plano = beneficiario.get(
        "plano"
    )

    consulta = (
        f"{mensagem}\n"
        f"categoria={categoria or 'não definida'} | "
        f"plano={plano or 'não definido'}"
    )

    try:
        resultados = await asyncio.to_thread(
            buscar_normas,
            consulta,
        )
    except Exception:
        return ""

    resultados_base = (
        resultados
        if isinstance(resultados, list)
        else []
    )

    if _mensagem_sobre_prazo_reanalise(
        mensagem
    ):
        try:
            resultados_procedimentais = (
                await asyncio.to_thread(
                    buscar_normas,
                    (
                        "pedido de reanálise após decisão de "
                        "indeferimento de reembolso; prazo da "
                        "reanálise; efeito da perda do prazo "
                        "original do pedido; verificar se a "
                        "reanálise reabre ou não o prazo original. "
                        f"Pergunta atual: {mensagem}"
                    ),
                )
            )
        except Exception:
            resultados_procedimentais = []

        if isinstance(
            resultados_procedimentais,
            list,
        ):
            fundidos = []

            for item in [
                *resultados_procedimentais[:4],
                *resultados_base[:4],
            ]:
                if item not in fundidos:
                    fundidos.append(item)

            return _formatar_rag(
                fundidos
            )

    return _formatar_rag(
        resultados_base
    )


def _extrair_texto_llm(resultado: Any) -> str:
    conteudo = getattr(
        resultado,
        "content",
        resultado,
    )

    if isinstance(conteudo, str):
        return conteudo.strip()

    if isinstance(conteudo, list):
        partes: list[str] = []

        for item in conteudo:
            if isinstance(item, str):
                partes.append(item)

            elif isinstance(item, dict):
                texto = (
                    item.get("text")
                    or item.get("content")
                    or ""
                )

                if texto:
                    partes.append(str(texto))

        return "\n".join(partes).strip()

    return str(conteudo or "").strip()


def _fallback(
    state: dict[str, Any],
    mensagem: str,
) -> str:
    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    documento_processado = bool(
        state.get("dados_documento")
        or state.get("categoria_documento")
        or state.get("documentos")
    )

    pendencias = (
        state.get("pendencias")
        or []
    )

    decisao = state.get(
        "decisao"
    )

    valor = _moeda(
        state.get(
            "valor_reembolso_brl"
        )
    )

    protocolo = state.get(
        "protocolo"
    )

    texto = mensagem.casefold()

    if not beneficiario:
        if documento_processado:
            return (
                "Recebi e analisei o documento enviado, que ficou "
                "registrado nesta solicitação. Para continuar o "
                "pedido de reembolso e consultar a operadora, "
                "informe a sua carteirinha."
            )

        if state.get("anexo_base64"):
            return (
                "Recebi o documento enviado. Para continuar a "
                "solicitação de reembolso, preciso da sua "
                "carteirinha para consultar a operadora."
            )

        return (
            "Entendi que se trata de um pedido de reembolso. "
            "Para continuar a análise e consultar a operadora, "
            "informe a sua carteirinha."
        )

    if decisao == "ESCALADO_ANALISTA":
        complemento = (
            f" O protocolo aberto é {protocolo}."
            if protocolo
            else ""
        )

        return (
            "Esse pedido depende de análise humana antes "
            "da conclusão, por isso ainda não posso informar "
            f"um valor de reembolso.{complemento}"
        )

    if decisao in {
        "APROVADO",
        "APROVADO_PARCIAL",
    }:
        if any(
            termo in texto
            for termo in (
                "quanto",
                "valor",
                "volta",
                "receber",
            )
        ):
            if valor:
                return (
                    f"O valor já apurado para este pedido "
                    f"é {valor}. Se quiser, também posso "
                    f"explicar quais regras influenciaram "
                    f"esse resultado."
                )

        if any(
            termo in texto
            for termo in (
                "por que",
                "porque",
                "inteiro",
                "só isso",
            )
        ):
            operacoes = set(
                state.get("operacoes_utilizadas")
                or []
            )

            fatores = []

            if "determinar_teto_procedimento" in operacoes:
                fatores.append(
                    "o teto aplicável ao procedimento"
                )

            if "aplicar_coparticipacao" in operacoes:
                fatores.append(
                    "a coparticipação prevista para o caso"
                )

            if "limitar_por_saldo_anual" in operacoes:
                fatores.append(
                    "o saldo ou limite anual disponível"
                )

            if fatores:
                if len(fatores) == 1:
                    motivo = fatores[0]
                else:
                    motivo = (
                        ", ".join(fatores[:-1])
                        + " e "
                        + fatores[-1]
                    )

                return (
                    f"O valor final foi apurado considerando {motivo}. "
                    + (
                        f"Por isso, o reembolso calculado é {valor}, "
                        "e não o valor integral solicitado."
                        if valor
                        else
                        "Por isso, o valor integral solicitado "
                        "não é necessariamente reembolsado."
                    )
                )

            return (
                "O valor final foi calculado pelas regras aplicáveis "
                "ao procedimento e ao plano, sem usar apenas o valor "
                "pago como referência."
            )

        return (
            "Seu pedido já foi analisado. "
            + (
                f"O valor apurado foi {valor}."
                if valor
                else "A decisão já está registrada."
            )
        )

    if decisao == "PENDENTE_DOCUMENTO":
        detalhe = (
            str(pendencias[0])
            if pendencias
            else "há documentação complementar pendente"
        )

        if any(
            termo in texto
            for termo in (
                "por que",
                "porque",
                "relatório",
                "relatorio",
                "precisa",
            )
        ):
            return (
                f"A análise ainda depende dessa documentação: "
                f"{detalhe} O complemento precisa ser recebido "
                f"antes da conclusão do pedido."
            )

        return (
            f"A análise continua pendente de documentação. "
            f"{detalhe}"
        )

    if pendencias:
        return str(
            pendencias[0]
        )

    return (
        "Recebi sua mensagem e o atendimento continua "
        "com os dados já registrados nesta sessão."
    )


async def gerar_resposta(
    state: dict[str, Any],
    mensagem: str,
) -> str:
    """Produz resposta específica, não repetitiva e sanitizada."""

    if pergunta_dado_clinico(
        mensagem
    ):
        return resposta_dado_clinico(
            mensagem
        )

    historico = (
        state.get("historico")
        or []
    )

    anteriores = _respostas_anteriores(
        historico
    )

    contexto_normativo = await _buscar_contexto(
        state,
        mensagem,
    )

    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    documento_processado = bool(
        state.get("dados_documento")
        or state.get("categoria_documento")
        or state.get("documentos")
    )

    if (
        not beneficiario
        and not documento_processado
        and state.get("decisao") is None
    ):
        return (
            "Posso ajudar com o pedido de reembolso. "
            "Para consultar a operadora e iniciar a análise, "
            "informe o número da sua carteirinha."
        )

    parametros_calculo_estado = (
        state.get(
            "parametros_calculo"
        )
        or {}
    )

    sessoes_anteriores_historico = (
        parametros_calculo_estado.get(
            "sessoes_utilizadas_ano"
        )
    )

    if (
        beneficiario
        and state.get("decisao") == "PENDENTE_DOCUMENTO"
        and _mensagem_sobre_documento_pendente(
            mensagem
        )
    ):
        requisitos = (
            parametros_calculo_estado.get(
                "requisitos_documentais_condicionais"
            )
            or []
        )

        requisito_acionado = None

        for item in requisitos:
            if isinstance(
                item,
                dict,
            ):
                requisito_acionado = item
                break

        if requisito_acionado:
            documento_exigido = str(
                requisito_acionado.get(
                    "documento"
                )
                or "documento complementar"
            ).strip()

            minimo_sessoes = (
                requisito_acionado.get(
                    "sessoes_min_inclusivo"
                )
            )

            partes = [
                (
                    f"Você pode solicitar o {documento_exigido} "
                    "ao profissional responsável pelo atendimento."
                )
            ]

            if (
                minimo_sessoes is not None
                and sessoes_anteriores_historico is not None
            ):
                try:
                    minimo = int(
                        minimo_sessoes
                    )

                    utilizadas = int(
                        sessoes_anteriores_historico
                    )
                except (TypeError, ValueError):
                    minimo = None
                    utilizadas = None

                if (
                    minimo is not None
                    and utilizadas is not None
                    and utilizadas >= minimo
                ):
                    partes.append(
                        (
                            "Neste caso, essa exigência já foi "
                            "acionada porque o acompanhamento atingiu "
                            f"o ponto previsto na regra, a partir da "
                            f"{minimo}ª sessão no ano civil."
                        )
                    )

            partes.append(
                (
                    "Sem esse complemento, o pedido não é negado "
                    "automaticamente: ele permanece pendente até "
                    "o documento ser apresentado."
                )
            )

            protocolo = state.get(
                "protocolo"
            )

            if protocolo:
                partes.append(
                    (
                        f"O protocolo {protocolo} continua aberto "
                        "aguardando esse documento."
                    )
                )
            else:
                partes.append(
                    (
                        "O protocolo permanece aberto aguardando "
                        "a documentação complementar."
                    )
                )

            return " ".join(
                partes
            )

    if (
        beneficiario
        and _mensagem_sobre_quantidade_sessoes(
            mensagem
        )
    ):
        sessoes_realizadas_operadora = (
            beneficiario.get(
                "sessoes_terapia_ano"
            )
        )

        quantidade_total = (
            sessoes_realizadas_operadora
            if sessoes_realizadas_operadora is not None
            else sessoes_anteriores_historico
        )

        try:
            quantidade_total = int(
                quantidade_total
            )
        except (TypeError, ValueError):
            quantidade_total = None

        if quantidade_total is not None:
            partes = [
                (
                    "Consultei o histórico da operadora: "
                    f"você já realizou {quantidade_total} sessões "
                    "de terapia neste ano civil."
                )
            ]

            if (
                state.get("decisao")
                == "PENDENTE_DOCUMENTO"
            ):
                requisitos = (
                    parametros_calculo_estado.get(
                        "requisitos_documentais_condicionais"
                    )
                    or []
                )

                for requisito in requisitos:
                    if not isinstance(
                        requisito,
                        dict,
                    ):
                        continue

                    documento = str(
                        requisito.get(
                            "documento"
                        )
                        or ""
                    ).strip()

                    minimo = requisito.get(
                        "sessoes_min_inclusivo"
                    )

                    if (
                        documento
                        and minimo is not None
                    ):
                        try:
                            minimo = int(
                                minimo
                            )
                        except (TypeError, ValueError):
                            minimo = None

                        if (
                            minimo is not None
                            and quantidade_total >= minimo
                        ):
                            partes.append(
                                (
                                    f"Como o acompanhamento já atingiu "
                                    f"o ponto previsto pela regra, a partir "
                                    f"da {minimo}ª sessão, o {documento} "
                                    "é necessário para concluir a análise. "
                                    "Sem ele, o pedido permanece pendente."
                                )
                            )

                        break

            return " ".join(
                partes
            )

    if (
        beneficiario
        and _mensagem_sobre_historico_anual_reembolso(
            mensagem
        )
    ):
        parametros_limites = (
            state.get(
                "parametros_calculo"
            )
            or {}
        )

        limite_anual_urs = (
            parametros_limites.get(
                "limite_anual_urs"
            )
        )

        saldo_anual_brl = _moeda(
            parametros_limites.get(
                "saldo_anual_brl"
            )
        )

        limite_sessoes_ano = (
            parametros_limites.get(
                "limite_sessoes_ano"
            )
        )

        sessoes_realizadas = (
            beneficiario.get(
                "sessoes_terapia_ano"
            )
        )

        valor_aprovado = _moeda(
            state.get(
                "valor_reembolso_brl"
            )
        )

        partes = [
            (
                "Sim. Os reembolsos anteriores do mesmo ano "
                "podem influenciar o valor disponível, mas o que "
                "importa é o total já reembolsado, e não apenas "
                "a quantidade de pedidos."
            )
        ]

        if limite_anual_urs is not None:
            partes.append(
                (
                    "Existe um limite anual acumulado de "
                    f"{limite_anual_urs:g} URS por beneficiário."
                )
            )

        if saldo_anual_brl:
            partes.append(
                (
                    "Os valores já pagos anteriormente são "
                    "descontados desse limite. Para este pedido, "
                    f"o saldo anual disponível apurado foi "
                    f"{saldo_anual_brl}, e esse saldo limita o "
                    "quanto pode ser reembolsado agora."
                )
            )

        if valor_aprovado:
            partes.append(
                (
                    f"O valor aprovado neste pedido, "
                    f"{valor_aprovado}, também passa a consumir "
                    "o saldo anual quando for pago."
                )
            )

        if limite_sessoes_ano is not None:
            try:
                limite_sessoes = int(
                    limite_sessoes_ano
                )
            except (TypeError, ValueError):
                limite_sessoes = None

            try:
                realizadas = (
                    int(sessoes_realizadas)
                    if sessoes_realizadas is not None
                    else None
                )
            except (TypeError, ValueError):
                realizadas = None

            if limite_sessoes is not None:
                if realizadas is not None:
                    partes.append(
                        (
                            "Além do limite financeiro, as terapias "
                            f"têm limite de {limite_sessoes} sessões "
                            f"por ano civil. A operadora registra "
                            f"{realizadas} sessões realizadas neste "
                            "ano; portanto esse limite quantitativo "
                            "também é uma regra aplicável ao pedido, "
                            "embora ainda não tenha sido atingido."
                        )
                    )
                else:
                    partes.append(
                        (
                            "Além do limite financeiro, as terapias "
                            f"têm limite de {limite_sessoes} sessões "
                            "por ano civil."
                        )
                    )

        return " ".join(
            partes
        )

    if (
        state.get("decisao")
        in {
            "APROVADO",
            "APROVADO_PARCIAL",
        }
        and _mensagem_pergunta_status_pedido(
            mensagem
        )
    ):
        valor_status = _moeda(
            state.get(
                "valor_reembolso_brl"
            )
        )

        if (
            state.get("decisao")
            == "APROVADO_PARCIAL"
        ):
            situacao = "foi aprovado parcialmente"
        else:
            situacao = "foi aprovado"

        if valor_status:
            return (
                f"Sim. O pedido {situacao} e o valor "
                f"do reembolso é {valor_status}."
            )

        return (
            f"Sim. O pedido {situacao}."
        )

    if (
        beneficiario
        and not documento_processado
        and state.get("decisao") is None
        and _parece_identificador_carteirinha(
            mensagem
        )
    ):
        return (
            "Carteirinha recebida e validada com sucesso. "
            "O cadastro foi localizado na operadora e podemos "
            "continuar a análise do pedido de reembolso."
        )

    if (
        not beneficiario
        and documento_processado
    ):
        if not mensagem.strip():
            return (
                "Recebi e analisei o documento enviado. "
                "Ele ficou registrado nesta sessão. "
                "O que você deseja fazer com esse documento?"
            )

        categoria = str(
            state.get("categoria_documento")
            or ""
        ).strip()

        tipo_atendimento = (
            "consulta médica"
            if categoria == "CONSULTA_MEDICA"
            else "atendimento"
        )

        return (
            f"Entendi: você está solicitando o reembolso de uma "
            f"{tipo_atendimento} particular. Recebi o documento "
            f"que você enviou e posso usá-lo para analisar essa "
            f"solicitação. Para consultar a operadora e prosseguir "
            f"com o reembolso, informe a sua carteirinha."
        )

    contexto = {
        "beneficiario_validado": bool(
            beneficiario
        ),
        "plano": beneficiario.get(
            "plano"
        ),
        "status_contrato": beneficiario.get(
            "status"
        ),
        "categoria_documento": state.get(
            "categoria_documento"
        ),
        "decisao": state.get(
            "decisao"
        ),
        "valor_solicitado_brl": _moeda(
            state.get(
                "valor_solicitado_brl"
            )
        ),
        "valor_reembolso_brl": _moeda(
            state.get(
                "valor_reembolso_brl"
            )
        ),
        "regras_aplicadas": (
            state.get(
                "regras_aplicadas"
            )
            or []
        ),
        "protocolo": state.get(
            "protocolo"
        ),
        "pendencias": (
            state.get(
                "pendencias"
            )
            or []
        ),
        "documentos_recebidos": len(
            state.get(
                "documentos"
            )
            or []
        ),
        "sessoes_terapia_ano_operadora": (
            beneficiario.get(
                "sessoes_terapia_ano"
            )
        ),
        "sessoes_utilizadas_no_calculo": (
            (
                state.get(
                    "parametros_calculo"
                )
                or {}
            ).get(
                "sessoes_utilizadas_ano"
            )
        ),
        "documento_principal": (
            state.get(
                "dados_documento"
            )
            or {}
        ),
        "categorias_documentos_recebidos": [
            str(
                item.get(
                    "categoria"
                )
                or ""
            )
            for item in (
                state.get(
                    "documentos"
                )
                or []
            )
            if isinstance(
                item,
                dict,
            )
        ],
        "parametros_calculo": (
            state.get(
                "parametros_calculo"
            )
            or {}
        ),
        "operacoes_utilizadas": (
            state.get(
                "operacoes_utilizadas"
            )
            or []
        ),
        "limite_anual_urs": (
            (
                state.get(
                    "parametros_calculo"
                )
                or {}
            ).get(
                "limite_anual_urs"
            )
        ),
        "saldo_anual_brl": _moeda(
            (
                state.get(
                    "parametros_calculo"
                )
                or {}
            ).get(
                "saldo_anual_brl"
            )
        ),
    }

    mensagem_atual = (
        mensagem.strip()
        or (
            "O beneficiário enviou somente um anexo "
            "neste turno, sem texto."
        )
    )

    prompt = (
        f"MENSAGEM ATUAL:\n{mensagem_atual}\n\n"
        f"ESTADO SEGURO DA SESSÃO:\n{contexto}\n\n"
        f"CONTEXTO NORMATIVO RECUPERADO:\n"
        f"{contexto_normativo or 'Nenhum trecho adicional recuperado.'}\n\n"
        f"RESPOSTAS RECENTES DO ASSISTENTE:\n"
        f"{anteriores}\n\n"
        "Responda à MENSAGEM ATUAL. "
        "Não repita nenhuma resposta anterior palavra por palavra.\n\n"

        "REGRAS PARA ESTE TURNO:\n"

        "1. Responda primeiro ao que o beneficiário acabou de informar "
        "ou perguntar. Não antecipe assunto diferente.\n"

        "2. Se beneficiario_validado=True, documentos_recebidos=0 e "
        "pendencias=[], e a mensagem atual estiver fornecendo a "
        "carteirinha ou outro identificador solicitado anteriormente, "
        "confirme claramente o recebimento/validação da carteirinha. "
        "Nesse caso não diga que está faltando documento e não solicite "
        "um documento novo nessa mesma resposta.\n"

        "3. Se um documento fiscal já estiver em documento_principal e "
        "a decisão for PENDENTE_DOCUMENTO, reconheça explicitamente que "
        "o documento enviado foi recebido. Depois explique qual "
        "complemento consta em pendencias e por que a análise ainda não "
        "pode ser concluída. Não trate o documento fiscal recebido como "
        "se ele não tivesse sido enviado.\n"

        "4. Se a pergunta atual for sobre quantas sessões o beneficiário "
        "já realizou no ano, use sessoes_terapia_ano_operadora quando "
        "esse dado estiver disponível, pois ele representa a quantidade "
        "oficial registrada pela operadora. Use "
        "sessoes_utilizadas_no_calculo somente quando for necessário "
        "explicar a contagem interna utilizada no cálculo ou sessões "
        "anteriores à sessão atual. Não use a estimativa do beneficiário. Não substitua o número por uma explicação "
        "genérica sobre como a contagem funciona. Não use palpite do "
        "beneficiário como fonte.\n"

        "5. Se uma documentação antes pendente tiver sido recebida e "
        "pendencias=[] agora, não peça novamente esse documento. "
        "Considere o estado atual da sessão.\n"

        "6. Em perguntas sobre perda de prazo, recurso, contestação ou "
        "reanálise, responda às duas partes quando o CONTEXTO NORMATIVO "
        "as sustentar: a consequência da perda do prazo original e a "
        "existência ou não de pedido de reanálise. Não diga que a "
        "reanálise reabre um prazo original já perdido. Não invente "
        "prazo numérico que não esteja sustentado pelo contexto normativo.\n"

        "7. Nunca invente pendência. Somente diga que falta documento "
        "quando ESTADO SEGURO DA SESSÃO.pendencias contiver uma pendência.\n"

        "8. Quando houver um dado concreto no ESTADO SEGURO DA SESSÃO, "
        "prefira informar esse dado em vez de responder genericamente.\n"

        "9. Quando a pergunta for sobre reembolsos anteriores, saldo ou "
        "limite anual e operacoes_utilizadas contiver "
        "limitar_por_saldo_anual, informe explicitamente que existe um "
        "limite anual acumulado. Informe limite_anual_urs quando estiver "
        "disponível, explique que os valores já reembolsados no mesmo ano "
        "reduzem o saldo disponível e informe saldo_anual_brl quando "
        "estiver disponível. Se esse saldo tiver limitado o pedido, diga "
        "isso claramente. Não responda apenas que pedidos anteriores "
        "'podem influenciar'.\n"

        "10. Quando a mensagem perguntar hipoteticamente sobre perder "
        "prazo, recorrer ou pedir reanálise, não altere a decisão do "
        "pedido atual. Se a decisão atual já for APROVADO ou "
        "APROVADO_PARCIAL, esclareça que ela continua válida e trate a "
        "pergunta de prazo como uma hipótese geral. Se o CONTEXTO "
        "NORMATIVO informar pedido de reanálise, explique essa "
        "possibilidade e o prazo previsto na norma. Deixe claro que a "
        "reanálise de uma decisão não reabre um prazo original de "
        "solicitação que já tenha sido perdido."
    )

    try:
        modelo = criar_llm(
            temperature=0,
        )

        resultado = await asyncio.to_thread(
            modelo.invoke,
            [
                (
                    "system",
                    SISTEMA,
                ),
                (
                    "human",
                    prompt,
                ),
            ],
        )

        resposta = sanitizar_resposta(
            _extrair_texto_llm(
                resultado
            )
        )

        if (
            resposta
            and not _eh_repetida(
                resposta,
                anteriores,
            )
        ):
            return resposta

        resultado_retry = await asyncio.to_thread(
            modelo.invoke,
            [
                (
                    "system",
                    SISTEMA,
                ),
                (
                    "human",
                    (
                        f"{prompt}\n\n"
                        "A primeira tentativa repetiu uma resposta "
                        "anterior ou ficou vazia. Reescreva de forma "
                        "diferente e responda especificamente ao que "
                        "foi perguntado neste turno."
                    ),
                ),
            ],
        )

        resposta_retry = sanitizar_resposta(
            _extrair_texto_llm(
                resultado_retry
            )
        )

        if (
            resposta_retry
            and not _eh_repetida(
                resposta_retry,
                anteriores,
            )
        ):
            return resposta_retry

    except Exception:
        pass

    resposta_fallback = sanitizar_resposta(
        _fallback(
            state,
            mensagem,
        )
    )

    if not resposta_fallback:
        resposta_fallback = (
            "Recebi sua mensagem e vou continuar o atendimento "
            "com os dados já registrados nesta sessão."
        )

    return resposta_fallback
