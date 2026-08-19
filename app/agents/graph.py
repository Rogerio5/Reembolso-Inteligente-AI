"""Grafo principal de orquestração do agente de reembolso."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.state import AgentState
from app.agents.supervisor.agent import supervisor_node
from app.agents.documento.agent import documento_node
from app.agents.normas.agent import normas_node
from app.agents.triagem.agent import triagem_node
from app.rag.retriever import buscar_normas


def rotear_supervisor(
    state: AgentState,
) -> str:
    destino = state.get("proximo_agente")

    if destino in {
        "triagem",
        "documento",
        "normas",
    }:
        return destino

    return "fim"


def criar_grafo():
    builder = StateGraph(
        AgentState
    )

    builder.add_node(
        "supervisor",
        supervisor_node,
    )

    builder.add_node(
        "triagem",
        triagem_node,
    )

    builder.add_node(
        "documento",
        documento_node,
    )

    builder.add_node(
        "normas",
        normas_node,
    )

    builder.set_entry_point(
        "supervisor"
    )

    builder.add_conditional_edges(
        "supervisor",
        rotear_supervisor,
        {
            "triagem": "triagem",
            "documento": "documento",
            "normas": "normas",
            "fim": END,
        },
    )

    builder.add_edge(
        "triagem",
        "supervisor",
    )

    builder.add_edge(
        "documento",
        "supervisor",
    )

    builder.add_edge(
        "normas",
        "supervisor",
    )

    checkpointer = MemorySaver()

    return builder.compile(
        checkpointer=checkpointer
    )


grafo = criar_grafo()
