"""Subagente responsável pela análise normativa."""

from __future__ import annotations

import asyncio

from app.agents.normas.auditoria import (
    auditar_regras_aplicadas,
    obter_regras_obrigatorias,
)
from app.agents.normas.consultas import (
    construir_consultas_normativas,
    fundir_resultados_rag,
)
from app.agents.decisao.agent import decisao_node
from app.agents.normas.resolver import (
    filtrar_resultados_aplicaveis,
    resolver_normas,
)
from app.agents.state import AgentState
from app.rag.retriever import buscar_normas


async def normas_node(
    state: AgentState,
) -> AgentState:
    """Recupera e resolve as normas aplicáveis ao caso."""

    consulta = (
        state.get("consulta_normativa")
        or state.get("mensagem")
        or ""
    )

    dados_documento = (
        state.get("dados_documento")
        or {}
    )

    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    categoria = (
        state.get("categoria_documento")
        or dados_documento.get("categoria")
    )

    codigo_tuss = dados_documento.get(
        "codigo_tuss"
    )

    plano = beneficiario.get(
        "plano"
    )

    data_atendimento = (
        dados_documento.get("data_atendimento")
        or dados_documento.get("data")
    )

    consultas = construir_consultas_normativas(
        consulta=consulta,
        categoria=categoria,
        codigo_tuss=codigo_tuss,
        plano=plano,
        data_atendimento=data_atendimento,
    )

    grupos_resultados = []

    for indice, item in enumerate(
        consultas
    ):
        resultados_consulta = await asyncio.to_thread(
            buscar_normas,
            item,
        )

        consulta_documental = (
            indice == len(consultas) - 1
        )

        # Mantém diversidade suficiente nas consultas
        # normativas. Algumas fontes essenciais podem
        # aparecer logo após os dois primeiros resultados.
        limite_resultados = (
            5
            if consulta_documental
            else 3
        )

        grupos_resultados.append(
            resultados_consulta[
                :limite_resultados
            ]
        )

    resultados = fundir_resultados_rag(
        grupos_resultados
    )

    resolucao = resolver_normas(
        consulta=consulta,
        data_atendimento=data_atendimento,
        resultados_rag=resultados,
        categoria=categoria,
        codigo_tuss=codigo_tuss,
        plano=plano,
    )

    resultados_aplicaveis = (
        filtrar_resultados_aplicaveis(
            resultados,
            resolucao.trechos_aplicaveis,
        )
    )

    resultados_auditoria = list(
        resultados_aplicaveis
    )

    codigo_tuss_texto = str(
        codigo_tuss or ""
    ).strip()

    if codigo_tuss_texto:
        for item in resultados:
            texto_item = str(
                item.get("texto")
                or ""
            )

            if (
                codigo_tuss_texto in texto_item
                and item not in resultados_auditoria
            ):
                resultados_auditoria.append(
                    item
                )

    estado_normativo: AgentState = {
        **state,
        "agente_atual": "normas",
        "resultados_rag": resultados_aplicaveis,
        "resolucao_normativa": resolucao.model_dump(
            mode="json"
        ),
        "regras_aplicadas": (
            resolucao.dispositivos_canonicos
        ),
        "regras_obrigatorias_runtime": [],
        "proximo_agente": None,
        "handoff_reason": (
            "Normas resolvidas; cálculo determinístico iniciado."
        ),
        "concluido": False,
    }

    resultado = await decisao_node(
        estado_normativo
    )

    parametros_calculo = (
        resultado.get("parametros_calculo")
        or {}
    )

    regras_obrigatorias = obter_regras_obrigatorias(
        parametros_utilizados=(
            resultado.get(
                "parametros_utilizados"
            )
            or []
        ),
        parametros_calculo=parametros_calculo,
    )

    codigo_tuss_normalizado = (
        str(codigo_tuss).strip()
        if codigo_tuss
        else ""
    )

    if codigo_tuss_normalizado:
        regras_obrigatorias.append(
            f"TUSS-{codigo_tuss_normalizado}"
        )

    regras_obrigatorias = list(
        dict.fromkeys(
            [
                *regras_obrigatorias,
                *(
                    resultado.get(
                        "regras_obrigatorias_runtime"
                    )
                    or []
                ),
            ]
        )
    )

    if resultado.get("decisao") in {
        "PENDENTE_DOCUMENTO",
        "ESCALADO_ANALISTA",
    }:
        regras_auditadas = []

    else:
        regras_auditadas = await asyncio.to_thread(
            auditar_regras_aplicadas,
            dispositivos_candidatos=(
                resultado.get("regras_aplicadas")
                or []
            ),
            resultados_rag=resultados_auditoria,
            parametros_calculo=parametros_calculo,
            parametros_utilizados=(
                resultado.get(
                    "parametros_utilizados"
                )
                or []
            ),
            operacoes_utilizadas=(
                resultado.get(
                    "operacoes_utilizadas"
                )
                or []
            ),
            codigo_tuss=codigo_tuss,
            decisao=resultado.get("decisao"),
            valor_solicitado_brl=(
                resultado.get(
                    "valor_solicitado_brl"
                )
            ),
            valor_reembolso_brl=(
                resultado.get(
                    "valor_reembolso_brl"
                )
            ),
            pendencias=(
                resultado.get("pendencias")
                or []
            ),
            protocolo=resultado.get("protocolo"),
        )

    regras_runtime = (
        resultado.get(
            "regras_obrigatorias_runtime"
        )
        or []
    )

    regras_obrigatorias_validadas = [
        regra
        for regra in regras_obrigatorias
        if (
            regra.startswith("TUSS-")
            or regra in regras_runtime
            or regra in regras_auditadas
        )
    ]

    regras_finais = list(
        dict.fromkeys(
            [
                *regras_obrigatorias_validadas,
                *regras_auditadas,
            ]
        )
    )

    return {
        **resultado,
        "agente_atual": "normas",
        "regras_aplicadas": regras_finais,
        "proximo_agente": None,
        "handoff_reason": (
            "Análise normativa, decisão determinística "
            "e auditoria final concluídas."
        ),
    }
