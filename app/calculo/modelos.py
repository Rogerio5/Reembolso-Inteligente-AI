"""Modelos estruturados para cálculo de reembolso."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas import Categoria

from app.schemas import Decisao


class FaixaCoparticipacao(BaseModel):
    """Faixa normativa de coparticipação recuperada da KB."""

    plano: str

    meses_min_exclusivo: int | None = None
    meses_max_inclusivo: int | None = None

    percentual: float


class TetoURSCondicional(BaseModel):
    """Teto em URS condicionado a uma quantidade de sessões."""

    sessoes_min_inclusivo: int | None = None
    sessoes_max_inclusivo: int | None = None

    quantidade_urs: float


class RequisitoDocumentoCondicional(BaseModel):
    """Documento exigido somente quando uma condição normativa é atendida."""

    documento: str
    categoria_documento: Categoria | None = None

    sessoes_min_inclusivo: int | None = None
    excedente_teto_percentual: float | None = None

    operador: str = "OR"

    dispositivos: list[str] = Field(
        default_factory=list
    )


class ProvenienciaParametro(BaseModel):
    """Rastreabilidade normativa de um parâmetro extraído."""

    campo: str

    dispositivos: list[str] = Field(
        default_factory=list
    )


class ParametrosCalculo(BaseModel):
    """Parâmetros extraídos das normas aplicáveis."""

    metodo: str | None = None

    valor_urs_brl: float | None = None
    quantidade_urs: float | None = None

    tetos_urs_condicionais: list[TetoURSCondicional] = Field(
        default_factory=list
    )

    percentual_reembolso: float | None = None
    percentual_coparticipacao: float | None = None

    faixas_coparticipacao: list[FaixaCoparticipacao] = Field(
        default_factory=list
    )

    teto_brl: float | None = None

    limite_alcada_brl: float | None = None
    analise_humana_incondicional: bool = False

    limite_anual_urs: float | None = None
    saldo_anual_brl: float | None = None

    limite_sessoes_ano: int | None = None
    sessoes_utilizadas_ano: int | None = None

    exige_protocolo: bool = False
    exige_analise_humana: bool = False

    documentos_obrigatorios: list[str] = Field(
        default_factory=list
    )

    requisitos_documentais_condicionais: list[
        RequisitoDocumentoCondicional
    ] = Field(
        default_factory=list
    )

    proveniencias: list[
        ProvenienciaParametro
    ] = Field(
        default_factory=list
    )


class ResultadoCalculo(BaseModel):
    """Resultado determinístico do cálculo."""

    decisao: Decisao | None = None

    valor_solicitado_brl: float | None = None
    valor_reembolso_brl: float | None = None

    calculavel: bool = False

    motivo: str = ""

    pendencias: list[str] = Field(
        default_factory=list
    )

    parametros_utilizados: list[str] = Field(
        default_factory=list
    )

    operacoes_utilizadas: list[str] = Field(
        default_factory=list
    )
