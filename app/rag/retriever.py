"""Busca híbrida da base normativa.

Carrega os índices persistidos em storage/ e combina:

    busca vetorial
          +
        BM25
          ↓
 Reciprocal Rank Fusion
          ↓
      LLMRerank

Nenhuma regra normativa é hardcoded neste módulo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llama_index.core import (
    StorageContext,
    load_index_from_storage,
)
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import (
    FUSION_MODES,
)
from llama_index.retrievers.bm25 import BM25Retriever

from app.llm import (
    criar_embeddings_llamaindex,
    criar_llm_llamaindex,
)


RAIZ = Path(__file__).resolve().parents[2]
DIR_STORAGE = RAIZ / "storage"
DIR_VECTOR = DIR_STORAGE / "vector"
DIR_BM25 = DIR_STORAGE / "bm25"

DENSE_TOP_K = 8
BM25_TOP_K = 8
FUSION_TOP_K = 10
RERANK_TOP_N = 5


class ErroRAG(RuntimeError):
    """Falha ao carregar ou consultar o índice normativo."""


class RecuperadorNormativo:
    """Busca híbrida persistente da base normativa."""

    def __init__(self) -> None:
        if not DIR_VECTOR.exists():
            raise ErroRAG(
                f"Índice vetorial não encontrado: {DIR_VECTOR}"
            )

        if not DIR_BM25.exists():
            raise ErroRAG(
                f"Índice BM25 não encontrado: {DIR_BM25}"
            )

        embeddings = criar_embeddings_llamaindex()

        storage_context = StorageContext.from_defaults(
            persist_dir=str(DIR_VECTOR),
        )

        self._indice = load_index_from_storage(
            storage_context,
            embed_model=embeddings,
        )

        self._dense = self._indice.as_retriever(
            similarity_top_k=DENSE_TOP_K,
        )

        self._bm25 = BM25Retriever.from_persist_dir(
            str(DIR_BM25),
        )

        self._bm25.similarity_top_k = BM25_TOP_K

        llm = criar_llm_llamaindex()

        self._fusion = QueryFusionRetriever(
            retrievers=[
                self._dense,
                self._bm25,
            ],
            llm=llm,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=FUSION_TOP_K,
            num_queries=1,
            use_async=False,
            verbose=False,
        )

        self._reranker = LLMRerank(
            llm=llm,
            top_n=RERANK_TOP_N,
            choice_batch_size=10,
        )

    def buscar(
        self,
        consulta: str,
    ) -> list[dict[str, Any]]:
        consulta = consulta.strip()

        if not consulta:
            return []

        candidatos = self._fusion.retrieve(
            consulta
        )

        reranqueados = self._reranker.postprocess_nodes(
            candidatos,
            query_str=consulta,
        )

        resultados: list[dict[str, Any]] = []

        for posicao, item in enumerate(
            reranqueados,
            start=1,
        ):
            node = item.node
            metadata = dict(node.metadata or {})

            resultados.append(
                {
                    "posicao": posicao,
                    "score": (
                        float(item.score)
                        if item.score is not None
                        else None
                    ),
                    "arquivo": metadata.get(
                        "arquivo"
                    ),
                    "pagina": metadata.get(
                        "pagina"
                    ),
                    "texto": node.get_content(),
                    "metadata": metadata,
                }
            )

        return resultados


_recuperador: RecuperadorNormativo | None = None


def obter_recuperador() -> RecuperadorNormativo:
    """Instância lazy para não recarregar índices a cada turno."""

    global _recuperador

    if _recuperador is None:
        _recuperador = RecuperadorNormativo()

    return _recuperador


def buscar_normas(
    consulta: str,
) -> list[dict[str, Any]]:
    return obter_recuperador().buscar(
        consulta
    )


def limpar_cache() -> None:
    """Usado por testes ou reinicialização explícita."""

    global _recuperador
    _recuperador = None
