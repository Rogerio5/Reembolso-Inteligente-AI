"""Extração de texto de documentos enviados em base64."""

from __future__ import annotations

import base64
import io

import pymupdf
import pytesseract
from PIL import Image


class ErroDocumento(Exception):
    """Falha na leitura do documento."""


def decodificar_base64(
    conteudo: str,
) -> bytes:
    try:
        return base64.b64decode(
            conteudo,
            validate=True,
        )
    except Exception as exc:
        raise ErroDocumento(
            "Anexo base64 inválido."
        ) from exc


def extrair_texto_pdf(
    dados: bytes,
) -> str:
    try:
        documento = pymupdf.open(
            stream=dados,
            filetype="pdf",
        )
    except Exception as exc:
        raise ErroDocumento(
            "Não foi possível abrir o PDF."
        ) from exc

    paginas: list[str] = []

    for pagina in documento:
        texto = pagina.get_text(
            "text"
        ).strip()

        if texto:
            paginas.append(texto)

    documento.close()

    return "\n\n".join(paginas)


def extrair_texto_imagem(
    dados: bytes,
) -> str:
    try:
        imagem = Image.open(
            io.BytesIO(dados)
        )
    except Exception as exc:
        raise ErroDocumento(
            "Não foi possível abrir a imagem."
        ) from exc

    return pytesseract.image_to_string(
        imagem,
        lang="por",
    ).strip()


def extrair_texto_anexo(
    conteudo_base64: str,
) -> str:
    dados = decodificar_base64(
        conteudo_base64
    )

    if dados.startswith(b"%PDF"):
        return extrair_texto_pdf(
            dados
        )

    try:
        return extrair_texto_imagem(
            dados
        )
    except ErroDocumento as exc:
        raise ErroDocumento(
            "Formato de documento não suportado."
        ) from exc
