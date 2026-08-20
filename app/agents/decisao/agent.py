"""Serviço responsável pela decisão e cálculo determinístico."""

from __future__ import annotations

from datetime import date

from app.agents.state import AgentState
from app.calculo.coparticipacao import (
    selecionar_percentual_coparticipacao,
)
from app.calculo.limite_anual import (
    calcular_saldo_anual,
)
from app.calculo.motor import calcular_reembolso
from app.calculo.parametros import (
    extrair_parametros_calculo,
)
from app.calculo.requisitos_documentais import (
    avaliar_requisito_documental,
)
from app.calculo.teto_condicional import (
    selecionar_quantidade_urs,
)
from app.tools.operadora import abrir_protocolo


def _contar_sessoes_terapia_historico(
    *,
    historico: dict,
    documento: dict,
) -> int | None:
    """Conta sessões anteriores usando somente o histórico MCP."""

    pedidos = historico.get("pedidos") or []

    if not isinstance(pedidos, list):
        return None

    data_atual = str(
        documento.get("data_atendimento")
        or documento.get("data_servico")
        or documento.get("data_procedimento")
        or documento.get("data")
        or ""
    ).strip()

    if (
        len(data_atual) < 10
        or not data_atual[:4].isdigit()
    ):
        return None

    ano_atual = data_atual[:4]
    contador = 0

    for pedido in pedidos:
        if not isinstance(pedido, dict):
            continue

        categoria = str(
            pedido.get("categoria")
            or ""
        ).strip().upper()

        if categoria != "SESSAO_TERAPIA":
            continue

        data_pedido = str(
            pedido.get("data_atendimento")
            or pedido.get("data")
            or ""
        ).strip()

        if not data_pedido.startswith(
            f"{ano_atual}-"
        ):
            continue

        # O pedido atual ainda não deve fazer parte
        # da quantidade de sessões já utilizadas.
        if (
            len(data_pedido) >= 10
            and data_pedido >= data_atual
        ):
            continue

        contador += 1

    return contador


async def decisao_node(
    state: AgentState,
) -> AgentState:
    """Aplica parâmetros normativos e calcula o reembolso."""

    resolucao = (
        state.get("resolucao_normativa")
        or {}
    )

    resultados_rag = (
        state.get("resultados_rag")
        or []
    )

    beneficiario = (
        state.get("beneficiario")
        or {}
    )

    historico = (
        state.get("historico_reembolsos")
        or {}
    )

    documento = (
        state.get("dados_documento")
        or {}
    )

    parametros = extrair_parametros_calculo(
        resolucao_normativa=resolucao,
        resultados_rag=resultados_rag,
    )

    valor_solicitado = state.get(
        "valor_solicitado_brl"
    )

    sessoes_utilizadas = None

    if (
        str(
            state.get("categoria_documento")
            or ""
        )
        == "SESSAO_TERAPIA"
    ):
        sessoes_utilizadas = (
            _contar_sessoes_terapia_historico(
                historico=historico,
                documento=documento,
            )
        )

    if sessoes_utilizadas is None:
        sessoes_utilizadas = beneficiario.get(
            "sessoes_terapia_ano"
        )

    if sessoes_utilizadas is not None:
        parametros.sessoes_utilizadas_ano = int(
            sessoes_utilizadas
        )

        parametros.quantidade_urs = (
            selecionar_quantidade_urs(
                quantidade_urs_base=(
                    parametros.quantidade_urs
                ),
                sessoes_utilizadas=(
                    parametros.sessoes_utilizadas_ano
                ),
                tetos_condicionais=(
                    parametros.tetos_urs_condicionais
                ),
            )
        )

    if parametros.analise_humana_incondicional:
        parametros.exige_analise_humana = True

    elif (
        parametros.limite_alcada_brl is not None
        and valor_solicitado is not None
    ):
        parametros.exige_analise_humana = (
            valor_solicitado
            > parametros.limite_alcada_brl
        )

    else:
        parametros.exige_analise_humana = False

    parametros.exige_protocolo = (
        parametros.exige_analise_humana
    )

    plano = beneficiario.get("plano")
    data_adesao_texto = beneficiario.get(
        "data_adesao"
    )
    data_atendimento_texto = documento.get(
        "data_atendimento"
    )

    teto_aplicavel_brl = parametros.teto_brl

    if (
        teto_aplicavel_brl is None
        and parametros.valor_urs_brl is not None
        and parametros.quantidade_urs is not None
    ):
        teto_aplicavel_brl = (
            parametros.valor_urs_brl
            * parametros.quantidade_urs
        )

    # ------------------------------------------------------
    # Competência decisória deve ser verificada antes de
    # continuar a análise automatizada.
    #
    # A existência de limite_alcada_brl não significa,
    # por si só, escalonamento. O escalonamento ocorre
    # quando o valor concreto ultrapassa esse limite.
    # ------------------------------------------------------

    parametros_escalonamento_previo: list[str] = []

    if parametros.analise_humana_incondicional:
        parametros_escalonamento_previo.append(
            "analise_humana_incondicional"
        )

    elif (
        parametros.limite_alcada_brl is not None
        and valor_solicitado is not None
        and valor_solicitado
        > parametros.limite_alcada_brl
    ):
        parametros_escalonamento_previo.append(
            "limite_alcada_brl"
        )

    if parametros_escalonamento_previo:

        regras_escalonamento_runtime: list[str] = []

        parametros_dump = parametros.model_dump(
            mode="json"
        )

        for proveniencia in (
            parametros_dump.get(
                "proveniencias"
            )
            or []
        ):
            if not isinstance(
                proveniencia,
                dict,
            ):
                continue

            campo = str(
                proveniencia.get(
                    "campo"
                )
                or ""
            ).strip()

            if (
                campo
                not in parametros_escalonamento_previo
            ):
                continue

            for dispositivo in (
                proveniencia.get(
                    "dispositivos"
                )
                or []
            ):
                dispositivo = str(
                    dispositivo
                    or ""
                ).strip()

                if (
                    dispositivo
                    and dispositivo
                    not in regras_escalonamento_runtime
                ):
                    regras_escalonamento_runtime.append(
                        dispositivo
                    )

        numero_protocolo = state.get(
            "protocolo"
        )

        if not numero_protocolo:
            carteirinha = state.get(
                "carteirinha"
            )

            if not carteirinha:
                raise RuntimeError(
                    "Carteirinha ausente para abertura "
                    "do protocolo."
                )

            protocolo_mcp = await abrir_protocolo(
                carteirinha=str(
                    carteirinha
                ),
                payload={
                    "session_id": state.get(
                        "session_id"
                    ),
                    "categoria_documento": (
                        state.get(
                            "categoria_documento"
                        )
                    ),
                    "valor_solicitado_brl": (
                        valor_solicitado
                    ),
                    "regras_aplicadas": (
                        state.get(
                            "regras_aplicadas"
                        )
                        or []
                    ),
                    "motivo": (
                        "Pedido fora da competência "
                        "decisória da análise automatizada."
                    ),
                },
            )

            numero_protocolo = (
                protocolo_mcp.get(
                    "protocolo"
                )
            )

            if not numero_protocolo:
                raise RuntimeError(
                    "MCP não retornou número "
                    "de protocolo."
                )

        return {
            **state,
            "agente_atual": "decisao",
            "parametros_calculo": (
                parametros.model_dump(
                    mode="json"
                )
            ),
            "decisao": "ESCALADO_ANALISTA",
            "valor_reembolso_brl": None,
            "parametros_utilizados": list(
                dict.fromkeys(
                    parametros_escalonamento_previo
                )
            ),
            "regras_obrigatorias_runtime": list(
                dict.fromkeys(
                    regras_escalonamento_runtime
                )
            ),
            "protocolo": str(
                numero_protocolo
            ),
            "pendencias": [],
            "pendencias_documentais_mensagens": [],
            "proximo_agente": None,
            "concluido": True,
        }

    documentos = (
        state.get("documentos")
        or []
    )

    categorias_presentes = {
        str(item.get("categoria") or "")
        for item in documentos
        if isinstance(item, dict)
    }

    pendencias_documentais_anteriores = set(
        state.get(
            "pendencias_documentais_mensagens"
        )
        or []
    )

    pendencias_base = [
        item
        for item in (
            state.get("pendencias")
            or []
        )
        if item
        not in pendencias_documentais_anteriores
    ]

    pendencias_documentais: list[str] = []

    parametros_documentais_utilizados: list[str] = []

    regras_obrigatorias_runtime: list[str] = []

    for requisito in (
        parametros.requisitos_documentais_condicionais
    ):
        avaliacao = avaliar_requisito_documental(
            requisito=requisito,
            sessoes_utilizadas=(
                parametros.sessoes_utilizadas_ano
            ),
            valor_pago_brl=valor_solicitado,
            teto_aplicavel_brl=teto_aplicavel_brl,
        )

        if not avaliacao.acionado:
            continue

        parametros_documentais_utilizados.append(
            "requisitos_documentais_condicionais"
        )

        if (
            "excedente_teto_percentual"
            in avaliacao.criterios_acionados
        ):
            if parametros.teto_brl is not None:
                parametros_documentais_utilizados.append(
                    "teto_brl"
                )

            elif (
                parametros.valor_urs_brl is not None
                and parametros.quantidade_urs is not None
            ):
                parametros_documentais_utilizados.extend(
                    [
                        "valor_urs_brl",
                        "quantidade_urs",
                    ]
                )

        categoria_exigida = (
            requisito.categoria_documento.value
            if requisito.categoria_documento
            else None
        )

        documento_presente = (
            categoria_exigida is not None
            and categoria_exigida
            in categorias_presentes
        )

        # A regra documental foi aplicada ao caso mesmo
        # quando o documento exigido já foi apresentado.
        # Portanto seus dispositivos permanecem na
        # rastreabilidade final.
        regras_obrigatorias_runtime.extend(
            requisito.dispositivos
        )

        if not documento_presente:
            pendencias_documentais.append(
                f"Envie o documento exigido: "
                f"{requisito.documento}."
            )

    if pendencias_documentais:
        numero_protocolo = state.get(
            "protocolo"
        )

        if not numero_protocolo:
            carteirinha = state.get(
                "carteirinha"
            )

            if not carteirinha:
                raise RuntimeError(
                    "Carteirinha ausente para abertura "
                    "do protocolo."
                )

            protocolo_mcp = await abrir_protocolo(
                carteirinha=str(carteirinha),
                payload={
                    "session_id": state.get(
                        "session_id"
                    ),
                    "categoria_documento": (
                        state.get(
                            "categoria_documento"
                        )
                    ),
                    "valor_solicitado_brl": (
                        valor_solicitado
                    ),
                    "regras_aplicadas": (
                        state.get(
                            "regras_aplicadas"
                        )
                        or []
                    ),
                    "motivo": (
                        "Pedido pendente de documento "
                        "complementar exigido pelas "
                        "regras aplicáveis."
                    ),
                },
            )

            numero_protocolo = (
                protocolo_mcp.get(
                    "protocolo"
                )
            )

            if not numero_protocolo:
                raise RuntimeError(
                    "MCP não retornou número "
                    "de protocolo."
                )

        return {
            **state,
            "agente_atual": "decisao",
            "parametros_calculo": parametros.model_dump(
                mode="json"
            ),
            "decisao": "PENDENTE_DOCUMENTO",
            "valor_reembolso_brl": None,
            "parametros_utilizados": list(
                dict.fromkeys(
                    parametros_documentais_utilizados
                )
            ),
            "regras_obrigatorias_runtime": list(
                dict.fromkeys(
                    regras_obrigatorias_runtime
                )
            ),
            "protocolo": str(
                numero_protocolo
            ),
            "pendencias": [
                *pendencias_base,
                *pendencias_documentais,
            ],
            "pendencias_documentais_mensagens": (
                pendencias_documentais
            ),
            "proximo_agente": None,
            "concluido": True,
        }

    if (
        plano
        and data_adesao_texto
        and data_atendimento_texto
    ):
        data_adesao = date.fromisoformat(
            data_adesao_texto
        )

        data_atendimento = date.fromisoformat(
            data_atendimento_texto
        )

        parametros.percentual_coparticipacao = (
            selecionar_percentual_coparticipacao(
                plano=plano,
                data_adesao=data_adesao,
                data_atendimento=data_atendimento,
                faixas=parametros.faixas_coparticipacao,
            )
        )

        if (
            parametros.valor_urs_brl is not None
            and parametros.limite_anual_urs is not None
        ):
            parametros.saldo_anual_brl = (
                calcular_saldo_anual(
                    historico=historico,
                    data_atendimento=data_atendimento,
                    valor_urs_brl=(
                        parametros.valor_urs_brl
                    ),
                    limite_anual_urs=(
                        parametros.limite_anual_urs
                    ),
                )
            )

    parametros_escalonamento_utilizados: list[str] = []

    if parametros.exige_analise_humana:
        if parametros.analise_humana_incondicional:
            parametros_escalonamento_utilizados.append(
                "analise_humana_incondicional"
            )

        elif (
            parametros.limite_alcada_brl is not None
            and valor_solicitado is not None
            and valor_solicitado
            > parametros.limite_alcada_brl
        ):
            parametros_escalonamento_utilizados.append(
                "limite_alcada_brl"
            )

        numero_protocolo = state.get(
            "protocolo"
        )

        if not numero_protocolo:
            carteirinha = state.get(
                "carteirinha"
            )

            if not carteirinha:
                raise RuntimeError(
                    "Carteirinha ausente para abertura "
                    "do protocolo."
                )

            protocolo_mcp = await abrir_protocolo(
                carteirinha=str(carteirinha),
                payload={
                    "session_id": state.get(
                        "session_id"
                    ),
                    "categoria_documento": (
                        state.get(
                            "categoria_documento"
                        )
                    ),
                    "valor_solicitado_brl": (
                        valor_solicitado
                    ),
                    "regras_aplicadas": (
                        state.get(
                            "regras_aplicadas"
                        )
                        or []
                    ),
                    "motivo": (
                        "Caso requer análise humana "
                        "conforme os parâmetros "
                        "normativos aplicáveis."
                    ),
                },
            )

            numero_protocolo = (
                protocolo_mcp.get(
                    "protocolo"
                )
            )

            if not numero_protocolo:
                raise RuntimeError(
                    "MCP não retornou número "
                    "de protocolo."
                )

        return {
            **state,
            "agente_atual": "decisao",
            "parametros_calculo": (
                parametros.model_dump(
                    mode="json"
                )
            ),
            "decisao": "ESCALADO_ANALISTA",
            "valor_reembolso_brl": None,
            "parametros_utilizados": list(
                dict.fromkeys(
                    parametros_escalonamento_utilizados
                )
            ),
            "regras_obrigatorias_runtime": [],
            "protocolo": str(
                numero_protocolo
            ),
            "pendencias": pendencias_base,
            "pendencias_documentais_mensagens": [],
            "proximo_agente": None,
            "concluido": True,
        }

    if parametros.exige_analise_humana:
        numero_protocolo = state.get(
            "protocolo"
        )

        if not numero_protocolo:
            carteirinha = state.get(
                "carteirinha"
            )

            if not carteirinha:
                raise RuntimeError(
                    "Carteirinha ausente para abertura "
                    "do protocolo."
                )

            protocolo_mcp = await abrir_protocolo(
                carteirinha=str(carteirinha),
                payload={
                    "session_id": state.get(
                        "session_id"
                    ),
                    "categoria_documento": (
                        state.get(
                            "categoria_documento"
                        )
                    ),
                    "valor_solicitado_brl": (
                        valor_solicitado
                    ),
                    "regras_aplicadas": (
                        state.get(
                            "regras_aplicadas"
                        )
                        or []
                    ),
                    "motivo": (
                        "Caso requer análise humana "
                        "conforme os parâmetros "
                        "normativos aplicáveis."
                    ),
                },
            )

            numero_protocolo = (
                protocolo_mcp.get(
                    "protocolo"
                )
            )

            if not numero_protocolo:
                raise RuntimeError(
                    "MCP não retornou número "
                    "de protocolo."
                )

        return {
            **state,
            "agente_atual": "decisao",
            "parametros_calculo": (
                parametros.model_dump(
                    mode="json"
                )
            ),
            "decisao": "ESCALADO_ANALISTA",
            "valor_reembolso_brl": None,
            "protocolo": str(
                numero_protocolo
            ),
            "pendencias": pendencias_base,
            "pendencias_documentais_mensagens": [],
            "proximo_agente": None,
            "concluido": True,
        }

    print()
    print("==========================================")
    print("DIAGNOSTICO PARAMETROS ANTES DO MOTOR")
    print("==========================================")
    print("VALOR_SOLICITADO=", state.get("valor_solicitado_brl"))
    print("VALOR_URS_BRL=", parametros.valor_urs_brl)
    print("QUANTIDADE_URS=", parametros.quantidade_urs)
    print("TETO_BRL=", parametros.teto_brl)
    print(
        "PERCENTUAL_COPARTICIPACAO=",
        parametros.percentual_coparticipacao,
    )
    print("LIMITE_ANUAL_URS=", parametros.limite_anual_urs)
    print("SALDO_ANUAL_BRL=", parametros.saldo_anual_brl)
    print(
        "SESSOES_UTILIZADAS_ANO=",
        parametros.sessoes_utilizadas_ano,
    )
    print("PLANO=", plano)
    print("DATA_ADESAO=", data_adesao_texto)
    print("DATA_ATENDIMENTO=", data_atendimento_texto)

    resultado = calcular_reembolso(
        valor_solicitado_brl=state.get(
            "valor_solicitado_brl"
        ),
        parametros=parametros,
    )

    print("RESULTADO_CALCULAVEL=", resultado.calculavel)
    print(
        "RESULTADO_DECISAO=",
        resultado.decisao.value
        if resultado.decisao
        else None,
    )
    print(
        "RESULTADO_VALOR_REEMBOLSO=",
        resultado.valor_reembolso_brl,
    )
    print("RESULTADO_MOTIVO=", resultado.motivo)

    return {
        **state,
        "agente_atual": "decisao",
        "parametros_calculo": parametros.model_dump(
            mode="json"
        ),
        "parametros_utilizados": (
            resultado.parametros_utilizados
        ),
        "operacoes_utilizadas": (
            resultado.operacoes_utilizadas
        ),
        "decisao": (
            resultado.decisao.value
            if resultado.decisao
            else None
        ),
        "valor_reembolso_brl": (
            resultado.valor_reembolso_brl
        ),
        "pendencias": [
            *pendencias_base,
            *resultado.pendencias,
        ],
        "pendencias_documentais_mensagens": [],

        "regras_obrigatorias_runtime": list(
            dict.fromkeys(
                regras_obrigatorias_runtime
            )
        ),
        "protocolo": (
            None
            if resultado.decisao is not None
            else state.get("protocolo")
        ),
        "proximo_agente": None,
        "concluido": True,
    }
