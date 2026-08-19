"""Classificação canônica do documento complementar exigido pela norma."""

from __future__ import annotations

from pydantic import BaseModel

from app.llm import criar_llm
from app.schemas import Categoria


class CategoriaDocumentoExigido(BaseModel):
    """Categoria canônica do documento normativamente exigido."""

    categoria: Categoria | None = None


SISTEMA = """
Você classifica somente o TIPO DE DOCUMENTO exigido por uma regra
normativa de reembolso.

Regras obrigatórias:

1. Classifique o documento exigido, não o procedimento principal.
2. Use somente uma categoria permitida pelo schema.
3. Não use a categoria do pedido principal como atalho.
4. Não invente informação.
5. Se o nome do documento exigido não corresponder com segurança a
   nenhuma categoria do schema, retorne categoria=null.
6. Documentos acessórios que não constituam uma das categorias
   permitidas devem retornar null.
7. Não aplique regras de reembolso e não determine decisão.
"""


def classificar_categoria_documento_exigido(
    documento: str,
) -> Categoria | None:
    """Converte a descrição normativa para uma categoria canônica."""

    if not documento.strip():
        return None

    modelo = criar_llm(
        temperature=0,
    ).with_structured_output(
        CategoriaDocumentoExigido
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
                    "TIPO DE DOCUMENTO EXIGIDO:\n"
                    f"{documento}"
                ),
            ),
        ]
    )

    if not isinstance(
        resultado,
        CategoriaDocumentoExigido,
    ):
        raise TypeError(
            "Structured output não retornou "
            "CategoriaDocumentoExigido."
        )

    return resultado.categoria
