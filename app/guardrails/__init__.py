"""Guardrails de segurança aplicados à conversa."""

from __future__ import annotations

import hashlib
import re
import unicodedata


CPF_RE = re.compile(
    r"(?<!\d)"
    r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}"
    r"(?!\d)"
)

CARTEIRINHA_RE = re.compile(
    r"(?<!\d)"
    r"(?:\d[\s.-]?){15}\d"
    r"(?!\d)"
)

CID_RE = re.compile(
    r"(?i)"
    r"\b(?:CID[\s:-]*)?"
    r"[A-Z][0-9]{2}"
    r"(?:\.[0-9A-Z]{1,4})?"
    r"\b"
)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize(
        "NFKD",
        texto,
    )

    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(
            caractere
        )
    )

    return texto.lower()


def extrair_carteirinha(
    mensagem: str,
) -> str | None:
    """Extrai carteirinha de 16 dígitos da mensagem."""

    match = CARTEIRINHA_RE.search(
        mensagem
    )

    if not match:
        return None

    numero = re.sub(
        r"\D",
        "",
        match.group(0),
    )

    if len(numero) != 16:
        return None

    return numero


def pedido_sobre_terceiro(
    mensagem: str,
) -> bool:
    """Detecta referência explícita a terceiro."""

    texto = _normalizar(
        mensagem
    )

    expressoes = (
        "minha esposa",
        "meu marido",
        "minha companheira",
        "meu companheiro",
        "meu conjuge",
        "minha conjuge",
        "minha filha",
        "meu filho",
        "minha mae",
        "meu pai",
        "meu irmao",
        "minha irma",
        "meu dependente",
        "minha dependente",
        "outra pessoa",
        "outra carteirinha",
        "carteirinha de outra pessoa",
        "pedido de terceiro",
        "reembolso de terceiro",
    )

    return any(
        expressao in texto
        for expressao in expressoes
    )


def pergunta_dado_clinico(
    mensagem: str,
) -> bool:
    """Detecta pedido explícito de CID/diagnóstico."""

    texto = _normalizar(
        mensagem
    )

    termos = (
        "qual meu cid",
        "qual e meu cid",
        "me diga o cid",
        "codigo cid",
        "qual meu diagnostico",
        "qual e meu diagnostico",
        "me diga meu diagnostico",
        "hipotese diagnostica",
        "qual a hipotese diagnostica",
    )

    return any(
        termo in texto
        for termo in termos
    )


def sanitizar_resposta(
    resposta: str,
) -> str:
    """Remove dados que nunca podem sair na resposta."""

    texto = str(
        resposta
        or ""
    )

    texto = CPF_RE.sub(
        "[CPF protegido]",
        texto,
    )

    texto = CARTEIRINHA_RE.sub(
        "[carteirinha protegida]",
        texto,
    )

    texto = CID_RE.sub(
        "[CID protegido]",
        texto,
    )

    return texto.strip()


def resposta_fora_escopo(
    mensagem: str,
) -> str:
    """Resposta explícita e segura para pedido sobre terceiro."""

    opcoes = (
        (
            "Não posso consultar, validar, confirmar, usar ou fornecer "
            "informações sobre outro beneficiário nesta sessão, incluindo "
            "plano, carteirinha, dados ou reembolso. Não vou validar nem "
            "usar a carteirinha informada para essa outra pessoa. Esse "
            "pedido de terceiro está fora do escopo. O seu pedido original "
            "continua normalmente."
        ),
        (
            "Esse pedido envolve outro beneficiário e está fora do escopo "
            "desta sessão. Não posso consultar, validar, confirmar nem "
            "fornecer informações sobre o plano, a carteirinha, os dados "
            "ou o reembolso dessa pessoa. A carteirinha informada para o "
            "terceiro não será utilizada. Continuamos normalmente apenas "
            "com o seu pedido original."
        ),
        (
            "Não vou consultar nem validar dados de outra pessoa nesta "
            "sessão. Isso inclui plano, carteirinha, informações cadastrais "
            "e dados de reembolso de cônjuge, dependente ou qualquer outro "
            "beneficiário. O pedido sobre terceiro fica fora do escopo, "
            "enquanto o seu pedido original permanece em andamento."
        ),
    )

    indice = int(
        hashlib.sha256(
            mensagem.encode("utf-8")
        ).hexdigest()[:8],
        16,
    ) % len(opcoes)

    return opcoes[indice]


def resposta_dado_clinico(
    mensagem: str,
) -> str:
    """Resposta segura quando pedem CID/diagnóstico."""

    opcoes = (
        (
            "Não posso reproduzir CID, hipótese "
            "diagnóstica ou diagnóstico clínico. "
            "Posso continuar ajudando com a análise "
            "do reembolso."
        ),
        (
            "Dados clínicos como CID e diagnóstico "
            "não são apresentados neste atendimento. "
            "Posso informar o andamento do pedido de "
            "reembolso."
        ),
        (
            "Por proteção de dados clínicos, não "
            "reproduzo CID nem diagnóstico. Posso "
            "explicar a situação do seu pedido e as "
            "pendências de reembolso."
        ),
    )

    indice = int(
        hashlib.sha256(
            mensagem.encode(
                "utf-8"
            )
        ).hexdigest()[-8:],
        16,
    ) % len(opcoes)

    return opcoes[indice]
