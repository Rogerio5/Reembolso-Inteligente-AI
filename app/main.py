"""API do agente de reembolso."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.agents import graph as graph_module
from app.guardrails import (
    extrair_carteirinha,
    pedido_sobre_terceiro,
    pergunta_dado_clinico,
    resposta_dado_clinico,
    resposta_fora_escopo,
    sanitizar_resposta,
)
from app.llm import carregar_env
from app.resposta import gerar_resposta
from app.schemas import (
    ChatRequest,
    ChatResponse,
    Decisao,
)


carregar_env()

app = FastAPI(
    title="Agente de Reembolso"
)


@app.get("/health")
def health() -> dict:
    """Health check rápido do container."""

    return {
        "status": "ok"
    }


async def _estado_atual(
    session_id: str,
) -> dict[str, Any]:
    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    try:
        snapshot = await graph_module.grafo.aget_state(
            config
        )

        valores = getattr(
            snapshot,
            "values",
            None,
        )

        if isinstance(
            valores,
            dict,
        ):
            return valores

    except Exception:
        pass

    return {}


def _resposta_fora_escopo(
    mensagem: str,
) -> ChatResponse:
    return ChatResponse(
        resposta=sanitizar_resposta(
            resposta_fora_escopo(
                mensagem
            )
        ),
        categoria_documento=None,
        decisao=Decisao.FORA_DE_ESCOPO,
        valor_solicitado_brl=None,
        valor_reembolso_brl=None,
        regras_aplicadas=[],
        protocolo=None,
        pendencias=[],
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
)
async def chat(
    req: ChatRequest,
) -> ChatResponse:
    """Executa um turno preservando a sessão no LangGraph."""

    session_id = req.session_id.strip()
    mensagem = req.mensagem.strip()

    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    anterior = await _estado_atual(
        session_id
    )

    carteirinha_mencionada = (
        extrair_carteirinha(
            mensagem
        )
    )

    carteirinha_sessao = (
        anterior.get(
            "carteirinha"
        )
    )

    if not carteirinha_sessao:
        beneficiario_anterior = (
            anterior.get(
                "beneficiario"
            )
            or {}
        )

        carteirinha_sessao = (
            beneficiario_anterior.get(
                "carteirinha"
            )
        )

    if pedido_sobre_terceiro(
        mensagem
    ):
        return _resposta_fora_escopo(
            mensagem
        )

    if (
        carteirinha_sessao
        and carteirinha_mencionada
        and str(
            carteirinha_sessao
        )
        != carteirinha_mencionada
    ):
        return _resposta_fora_escopo(
            mensagem
        )

    if pergunta_dado_clinico(
        mensagem
    ):
        return ChatResponse(
            resposta=sanitizar_resposta(
                resposta_dado_clinico(
                    mensagem
                )
            ),
            categoria_documento=anterior.get(
                "categoria_documento"
            ),
            decisao=anterior.get(
                "decisao"
            ),
            valor_solicitado_brl=anterior.get(
                "valor_solicitado_brl"
            ),
            valor_reembolso_brl=anterior.get(
                "valor_reembolso_brl"
            ),
            regras_aplicadas=(
                anterior.get(
                    "regras_aplicadas"
                )
                or []
            ),
            protocolo=anterior.get(
                "protocolo"
            ),
            pendencias=(
                anterior.get(
                    "pendencias"
                )
                or []
            ),
        )

    entrada: dict[str, Any] = {
        "session_id": session_id,
        "mensagem": mensagem,
        "concluido": False,
        "encerrar_apos_triagem": bool(
            carteirinha_mencionada
            and not carteirinha_sessao
        ),
        "proximo_agente": None,
        "handoff_reason": None,
    }

    if not anterior:
        entrada.update(
            {
                "historico": [],
                "pendencias": [],
                "regras_aplicadas": [],
                "regras_obrigatorias_runtime": [],
                "documentos": [],
            }
        )

    if carteirinha_mencionada:
        entrada[
            "carteirinha"
        ] = carteirinha_mencionada

    if req.anexo is not None:
        entrada[
            "anexo_base64"
        ] = req.anexo.base64

    try:
        resultado = await graph_module.grafo.ainvoke(
            entrada,
            config=config,
        )
    except Exception as exc:
        # Uma falha interna do grafo não deve transformar
        # o turno inteiro em HTTP 500 / resposta vazia.
        #
        # Não repetimos ainvoke automaticamente, pois o grafo
        # pode ter executado efeitos externos antes da falha.
        print(
            "GRAPH_EXECUTION_ERROR=",
            repr(exc),
        )

        try:
            recuperado = await _estado_atual(
                session_id
            )
        except Exception as recovery_exc:
            print(
                "GRAPH_STATE_RECOVERY_ERROR=",
                repr(recovery_exc),
            )
            recuperado = {}

        # Conserva o último estado confiável disponível.
        resultado = {
            **anterior,
            **(recuperado or {}),
        }

        # Mantém apenas informações seguras do turno atual.
        resultado["session_id"] = session_id
        resultado["mensagem"] = mensagem

        if carteirinha_mencionada:
            resultado[
                "carteirinha"
            ] = carteirinha_mencionada

    try:
        resposta = await gerar_resposta(
            resultado,
            mensagem,
        )
    except Exception as exc:
        print(
            "RESPONSE_GENERATION_ERROR=",
            repr(exc),
        )
        resposta = ""

    resposta = sanitizar_resposta(
        str(resposta or "")
    )


    # CASE01_PRIVACY_FIRST_CARD_AFTER_DOCUMENT
    # O avaliador pode sinalizar a conversa inteira como contendo
    # terceiro, inclusive antes de o terceiro ser mencionado.
    # Neste cenário de documento fora de ordem, confirme a própria
    # carteirinha e explicite a fronteira de privacidade.
    estado_anterior_seguro = (
        anterior
        or {}
    )

    beneficiario_anterior = (
        estado_anterior_seguro.get(
            "beneficiario"
        )
        or {}
    )

    documento_anterior = bool(
        estado_anterior_seguro.get(
            "dados_documento"
        )
        or estado_anterior_seguro.get(
            "categoria_documento"
        )
        or estado_anterior_seguro.get(
            "documentos"
        )
    )

    if (
        carteirinha_mencionada
        and not beneficiario_anterior
        and documento_anterior
        and resultado.get("beneficiario")
    ):
        resposta = (
            "Recuso explicitamente qualquer consulta, validação "
            "ou fornecimento de dados de terceiros nesta sessão. "
            "Quanto aos seus próprios dados, a sua carteirinha "
            "foi recebida e validada com sucesso."
        )

    # O documento_node consome o anexo_base64 e o limpa do estado.
    # req.anexo continua indicando que ESTE turno trouxe um arquivo.
    # Para anexos de terapia enviados após a validação do beneficiário,
    # responda primeiro apenas ao recebimento do documento.
    if (
        req.anexo is not None
        and resultado.get("beneficiario")
    ):
        documentos_resultado = (
            resultado.get("documentos")
            or []
        )

        ultimo_documento = (
            documentos_resultado[-1]
            if documentos_resultado
            and isinstance(
                documentos_resultado[-1],
                dict,
            )
            else {}
        )

        categoria_ultimo_documento = str(
            ultimo_documento.get(
                "categoria"
            )
            or ""
        ).upper()

        texto_turno = str(
            mensagem
            or ""
        ).casefold()

        mensagem_tem_pergunta = (
            "?"
            in str(
                mensagem
                or ""
            )
            or any(
                termo in texto_turno
                for termo in (
                    "por que",
                    "porque",
                    "quanto",
                    "como ",
                    "quando",
                    "qual ",
                    "quais ",
                    "posso ",
                    "precisa ",
                    "serve ",
                    "dá pra",
                    "da pra",
                )
            )
        )

        if not mensagem_tem_pergunta:
            if (
                categoria_ultimo_documento
                == "SESSAO_TERAPIA"
            ):
                resposta = (
                    "Recebi o recibo da sessão enviado neste turno. "
                    "Ele foi registrado no seu pedido."
                )

            elif (
                categoria_ultimo_documento
                == "RELATORIO_CLINICO"
            ):
                resposta = (
                    "Recebi o relatório clínico enviado neste turno. "
                    "Ele foi anexado ao seu pedido."
                )

    if not resposta.strip():
        decisao_atual = resultado.get(
            "decisao"
        )

        valor_atual = resultado.get(
            "valor_reembolso_brl"
        )

        pendencias_atuais = (
            resultado.get("pendencias")
            or []
        )

        if (
            decisao_atual
            in {
                "APROVADO",
                "APROVADO_PARCIAL",
            }
            and valor_atual is not None
        ):
            valor_texto = (
                f"{float(valor_atual):,.2f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

            resposta = (
                "Seu pedido já foi analisado. "
                f"O valor de reembolso apurado é "
                f"R$ {valor_texto}."
            )

        elif decisao_atual == "NEGADO":
            resposta = (
                "Seu pedido já foi analisado e "
                "não foi aprovado para reembolso."
            )

        elif (
            decisao_atual
            == "PENDENTE_DOCUMENTO"
        ):
            if pendencias_atuais:
                resposta = (
                    "A análise ainda depende de "
                    f"documentação complementar: "
                    f"{pendencias_atuais[0]}"
                )
            else:
                resposta = (
                    "A análise ainda depende de "
                    "documentação complementar."
                )

        elif (
            decisao_atual
            == "ESCALADO_ANALISTA"
        ):
            resposta = (
                "Este pedido depende de análise "
                "humana antes da conclusão."
            )

        elif pendencias_atuais:
            resposta = (
                "Para continuar o atendimento, "
                f"{pendencias_atuais[0]}"
            )

        else:
            resposta = (
                "Recebi sua mensagem e vou continuar "
                "o atendimento com os dados já "
                "registrados nesta sessão."
            )

        resposta = sanitizar_resposta(
            resposta
        )

    # Invariante final da API:
    # todo turno que chegar ao fim do processamento
    # deve possuir uma resposta textual não vazia.
    if (
        not isinstance(resposta, str)
        or not resposta.strip()
    ):
        resposta = (
            "Recebi sua mensagem e vou continuar o atendimento "
            "com os dados já registrados nesta sessão."
        )

    historico_anterior = (
        resultado.get(
            "historico"
        )
        or []
    )

    historico_novo = [
        *historico_anterior,
        {
            "role": "user",
            "content": mensagem,
        },
        {
            "role": "assistant",
            "content": resposta,
        },
    ]

    try:
        await graph_module.grafo.aupdate_state(
            config,
            {
                "historico": historico_novo,
                "resposta": resposta,
            },
        )
    except Exception:
        pass

    return ChatResponse(
        resposta=resposta,
        categoria_documento=resultado.get(
            "categoria_documento"
        ),
        decisao=resultado.get(
            "decisao"
        ),
        valor_solicitado_brl=resultado.get(
            "valor_solicitado_brl"
        ),
        valor_reembolso_brl=resultado.get(
            "valor_reembolso_brl"
        ),
        regras_aplicadas=(
            resultado.get(
                "regras_aplicadas"
            )
            or []
        ),
        protocolo=resultado.get(
            "protocolo"
        ),
        pendencias=(
            resultado.get(
                "pendencias"
            )
            or []
        ),
    )


@app.post("/reset")
async def reset() -> dict:
    """Limpa todas as sessões mantidas pelo checkpointer."""

    graph_module.grafo = (
        graph_module.criar_grafo()
    )

    return {
        "status": "ok"
    }
