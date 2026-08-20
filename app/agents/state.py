"""Estado compartilhado entre supervisor e subagentes."""

from __future__ import annotations

from typing import Any, TypedDict

from app.schemas import Categoria, Decisao


class AgentState(TypedDict, total=False):
    # Conversa
    session_id: str
    mensagem: str
    historico: list[dict[str, str]]

    # Anexo/documento
    anexo_base64: str | None
    categoria_documento: Categoria | None
    dados_documento: dict[str, Any]
    documentos: list[dict[str, Any]]

    # Beneficiário / MCP
    carteirinha: str | None
    beneficiario: dict[str, Any]
    historico_reembolsos: dict[str, Any]

    # Normas / RAG
    consulta_normativa: str
    resultados_rag: list[dict[str, Any]]
    regras_aplicadas: list[str]
    regras_obrigatorias_runtime: list[str]
    resolucao_normativa: dict[str, Any]
    parametros_calculo: dict[str, Any]
    parametros_utilizados: list[str]
    operacoes_utilizadas: list[str]

    # Decisão
    decisao: Decisao | None
    valor_solicitado_brl: float | None
    valor_reembolso_brl: float | None
    protocolo: str | None
    pendencias: list[str]
    pendencias_documentais_mensagens: list[str]

    # Controle do grafo
    agente_atual: str
    proximo_agente: str | None
    handoff_reason: str | None
    concluido: bool
    encerrar_apos_triagem: bool

    # Resposta final
    resposta: str
