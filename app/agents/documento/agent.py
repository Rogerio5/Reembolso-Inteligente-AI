"""Subagente responsável pela análise documental."""

from __future__ import annotations

from app.agents.documento.classificador import (
    classificar_documento,
)
from app.agents.documento.extracao import (
    ErroDocumento,
    extrair_texto_anexo,
)
from app.agents.state import AgentState


_PENDENCIA_DOCUMENTO_GENERICA = (
    "Envie o documento necessário para análise."
)


def documento_node(
    state: AgentState,
) -> AgentState:
    """Extrai e classifica o documento enviado pelo beneficiário."""

    anexo_base64 = state.get(
        "anexo_base64"
    )

    if not anexo_base64:
        return {
            **state,
            "agente_atual": "documento",
            "pendencias": list(
                dict.fromkeys(
                    [
                        *state.get(
                            "pendencias",
                            [],
                        ),
                        _PENDENCIA_DOCUMENTO_GENERICA,
                    ]
                )
            ),
            "proximo_agente": None,
            "handoff_reason": (
                "Documento ainda não foi enviado."
            ),
            "concluido": True,
        }

    try:
        texto = extrair_texto_anexo(
            anexo_base64
        )
    except ErroDocumento:
        return {
            **state,
            "agente_atual": "documento",
            "anexo_base64": None,
            "pendencias": [
                *state.get("pendencias", []),
                "Não foi possível analisar o documento enviado.",
            ],
            "proximo_agente": None,
            "handoff_reason": (
                "Falha na leitura do documento."
            ),
            "concluido": True,
        }

    documento = classificar_documento(
        texto
    )

    dados_documento_novo = documento.model_dump(
        mode="json"
    )

    # Campos livres do LLM não são necessários para
    # as etapas posteriores e não devem persistir
    # no checkpoint da conversa.
    dados_documento_novo.pop(
        "campos_identificados",
        None,
    )
    dados_documento_novo.pop(
        "observacoes",
        None,
    )

    pendencias_atuais = [
        item
        for item in (
            state.get("pendencias")
            or []
        )
        if item
        != _PENDENCIA_DOCUMENTO_GENERICA
    ]

    documentos_anteriores = list(
        state.get("documentos") or []
    )

    documentos = [
        *documentos_anteriores,
        dados_documento_novo,
    ]

    documento_principal_anterior = (
        state.get("dados_documento")
        or {}
    )

    categoria_anterior = str(
        documento_principal_anterior.get("categoria")
        or ""
    ).upper()

    eh_complementar = (
        documento.categoria.value
        == "RELATORIO_CLINICO"
        and bool(documento_principal_anterior)
        and categoria_anterior
        not in {
            "INVALIDO",
            "RELATORIO_CLINICO",
        }
    )

    if eh_complementar:
        dados_documento = (
            documento_principal_anterior
        )
    else:
        dados_documento = (
            dados_documento_novo
        )

        # O novo anexo substituiu o documento principal.
        # Pendências derivadas do documento anterior não podem
        # contaminar a nova análise; as normas recalcularão
        # eventuais pendências a partir do novo documento.
        pendencias_atuais = []

    categoria_principal = str(
        dados_documento.get("categoria")
        or documento.categoria.value
    )

    valor_principal = (
        dados_documento.get("valor_brl")
    )

    consulta_normativa = (
        f"{categoria_principal}: "
        f"{dados_documento.get('tipo_servico') or ''} "
        f"TUSS {dados_documento.get('codigo_tuss') or ''}"
    ).strip()

    return {
        **state,
        "agente_atual": "documento",
        "anexo_base64": None,
        "categoria_documento": categoria_principal,
        "dados_documento": dados_documento,
        "documentos": documentos,
        "pendencias": pendencias_atuais,
        "valor_solicitado_brl": valor_principal,
        "consulta_normativa": consulta_normativa,
        "proximo_agente": (
            "normas"
            if state.get("beneficiario")
            else "triagem"
        ),
        "handoff_reason": (
            "Documento classificado e dados extraídos; "
            + (
                "beneficiário já validado, seguir para normas."
                if state.get("beneficiario")
                else "beneficiário ainda precisa ser validado."
            )
        ),
    }
