"""Classificação e extração estruturada de documentos."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import criar_llm
from app.schemas import Categoria


class DocumentoExtraido(BaseModel):
    """Dados observáveis extraídos do documento."""

    categoria: Categoria

    valor_brl: float | None = None
    data_atendimento: str | None = None
    codigo_tuss: str | None = None

    tipo_servico: str | None = None

    paciente_identificado: bool = False
    prestador_identificado: bool = False
    registro_profissional_identificado: bool = False
    assinatura_identificada: bool = False

    campos_identificados: list[str] = Field(
        default_factory=list
    )

    observacoes: list[str] = Field(
        default_factory=list
    )

    texto_suficiente: bool = True


SISTEMA = """
Você é o subagente de análise documental de um sistema de reembolso.

Analise somente o conteúdo do documento recebido.

Classifique o documento em exatamente uma das categorias permitidas
pelo schema.

Extraia apenas informações explicitamente presentes no documento.

Regras:
1. Não invente informação ausente.
2. Não determine se o reembolso será aprovado ou negado.
3. Não aplique regras normativas.
4. Não calcule valor de reembolso.
5. Não reproduza CPF completo.
6. Não reproduza CID.
7. Não reproduza hipótese ou diagnóstico clínico.
8. codigo_tuss deve conter somente o código quando estiver explícito.
9. valor_brl deve ser numérico.
10. data_atendimento deve ser preservada em formato ISO YYYY-MM-DD
    quando identificável.
11. Se o conteúdo não representar documento válido para as categorias
    de reembolso, classifique como INVALIDO.
"""


def classificar_documento(
    texto: str,
) -> DocumentoExtraido:
    if not texto.strip():
        return DocumentoExtraido(
            categoria=Categoria.INVALIDO,
            texto_suficiente=False,
            observacoes=[
                "Documento sem texto suficiente para análise."
            ],
        )

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        DocumentoExtraido
    )

    resultado = modelo.invoke(
        [
            (
                "system",
                SISTEMA,
            ),
            (
                "human",
                (
                    "Analise o documento abaixo.\n\n"
                    "DOCUMENTO:\n"
                    f"{texto}"
                ),
            ),
        ]
    )

    if not isinstance(
        resultado,
        DocumentoExtraido,
    ):
        raise TypeError(
            "Structured output não retornou DocumentoExtraido."
        )

    return resultado
