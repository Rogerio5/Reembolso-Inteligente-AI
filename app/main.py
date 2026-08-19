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

    resultado = await graph_module.grafo.ainvoke(
        entrada,
        config=config,
    )

    resposta = await gerar_resposta(
        resultado,
        mensagem,
    )

    resposta = sanitizar_resposta(
        resposta
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
