"""Cliente MCP da operadora SaúdeMais."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.llm import carregar_env


class ErroMCP(RuntimeError):
    """Falha retornada pelo servidor ou por uma ferramenta MCP."""


def _config() -> tuple[str, str]:
    carregar_env()

    url = os.getenv("MCP_OPERADORA_URL", "").strip()
    token = os.getenv("MCP_OPERADORA_TOKEN", "").strip()

    if not url:
        raise ErroMCP(
            "MCP_OPERADORA_URL não configurada."
        )

    return url, token


def _extrair_resultado(resultado: Any) -> dict[str, Any]:
    if getattr(resultado, "isError", False):
        mensagens = []

        for item in getattr(resultado, "content", []) or []:
            texto = getattr(item, "text", "")
            if texto:
                mensagens.append(texto)

        detalhe = " ".join(mensagens).strip()
        raise ErroMCP(
            detalhe or "A ferramenta MCP retornou erro."
        )

    estruturado = getattr(
        resultado,
        "structuredContent",
        None,
    )

    if isinstance(estruturado, dict) and estruturado:
        return estruturado

    for item in getattr(resultado, "content", []) or []:
        texto = getattr(item, "text", "")

        if not texto:
            continue

        try:
            valor = json.loads(texto)
        except json.JSONDecodeError:
            continue

        if isinstance(valor, dict):
            return valor

    raise ErroMCP(
        "Resposta MCP sem conteúdo estruturado válido."
    )


async def _chamar(
    ferramenta: str,
    argumentos: dict[str, Any],
) -> dict[str, Any]:
    url, token = _config()

    headers: dict[str, str] = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(
            url,
            http_client=http_client,
        ) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream,
                write_stream,
            ) as session:
                await session.initialize()

                resultado = await session.call_tool(
                    ferramenta,
                    arguments=argumentos,
                )

    return _extrair_resultado(resultado)


async def consultar_beneficiario(
    carteirinha: str,
) -> dict[str, Any]:
    return await _chamar(
        "consultar_beneficiario",
        {"carteirinha": carteirinha},
    )


async def consultar_historico(
    carteirinha: str,
) -> dict[str, Any]:
    return await _chamar(
        "consultar_historico",
        {"carteirinha": carteirinha},
    )


async def abrir_protocolo(
    carteirinha: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return await _chamar(
        "abrir_protocolo",
        {
            "carteirinha": carteirinha,
            "payload": payload,
        },
    )
