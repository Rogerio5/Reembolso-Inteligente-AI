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

    return _formatar_rag(
        resultados
        if isinstance(resultados, list)
        else []
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
        "Não repita nenhuma resposta anterior palavra por palavra."
    )

    try:
        modelo = criar_llm(
            temperature=0.35,
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
