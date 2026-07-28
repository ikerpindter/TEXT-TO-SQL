"""Una llamada al modelo: esquema + pregunta -> SQL.

Sin reintentos, sin few-shot, sin cadena de razonamiento explícita, sin
autocorrección. Una llamada, una respuesta. Todo lo demás es alcance de
rebanadas posteriores.

POR QUÉ RESPONSES API Y NO chat.completions
--------------------------------------------
Los proyectos 1 y 2 corren sobre la Responses API, y en la rebanada 5 esto se
conecta como tool del agente, que ya está construido sobre ella. Usar
chat.completions aquí obligaría a traducir después.

Forma de la llamada, verificada contra la doc oficial y contra los tipos del
SDK instalado (openai 2.49.0), no de memoria:

  client.responses.create(model=..., instructions=..., input=...)
    - `instructions` es el equivalente al mensaje de sistema.
    - el texto sale de `response.output_text`, que agrega todas las salidas
      de texto en un solo string.
    - `usage` trae `input_tokens` / `output_tokens` / `total_tokens`. Ojo:
      NO son `prompt_tokens` / `completion_tokens` como en chat.completions.
    - `usage.output_tokens_details.reasoning_tokens` son los tokens de
      razonamiento. Van INCLUIDOS en output_tokens y se facturan como
      salida. Se reportan aparte porque en un modelo de razonamiento suelen
      ser la mayor parte del costo.

No se fija `reasoning={"effort": ...}` a propósito: la rebanada 1 mide el
comportamiento por default del modelo. El esfuerzo de razonamiento es una
variable como cualquier otra y se prende en su propia rebanada, con su propio
archivo de resultados.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from openai import OpenAI

DEFAULT_MODEL = "gpt-5.4-nano"

# USD por millón de tokens: (entrada, salida).
# Si el modelo no está aquí, el CLI reporta tokens pero no costo, en vez de
# inventarse un número.
PRICING_USD_PER_MTOK = {
    "gpt-5.4-nano": (0.20, 1.25),
}

SYSTEM_PROMPT = """\
Eres un generador de SQL para SQLite. Recibes el esquema de una base de datos \
y una pregunta en lenguaje natural. Devuelves UNA sola consulta SELECT que \
responda la pregunta.

Reglas:
- Dialecto SQLite. Nada de sintaxis de Postgres, MySQL ni T-SQL.
- Solo lectura: SELECT o WITH. Nunca INSERT, UPDATE, DELETE, DROP, ALTER ni \
CREATE.
- Devuelve únicamente el SQL. Sin explicación, sin comentarios, sin markdown, \
sin punto y coma final.\
"""

USER_TEMPLATE = """\
Esquema de la base de datos:

{schema}

Pregunta: {question}

SQL:"""


def _price_for(model: str) -> tuple[float, float] | None:
    """Precio de un modelo. La API resuelve alias a nombres con sufijo de
    fecha ('gpt-5.4-nano' -> 'gpt-5.4-nano-2026-01-15'), así que si no hay
    coincidencia exacta se busca por prefijo."""
    if model in PRICING_USD_PER_MTOK:
        return PRICING_USD_PER_MTOK[model]
    candidates = [k for k in PRICING_USD_PER_MTOK if model.startswith(k)]
    if not candidates:
        return None
    return PRICING_USD_PER_MTOK[max(candidates, key=len)]


@dataclass(frozen=True)
class Generation:
    """Resultado de una llamada al modelo."""

    sql: str
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    raw: str

    @property
    def cost_usd(self) -> float | None:
        """Costo real de esta llamada, o None si no se conoce el precio.

        reasoning_tokens NO se suma aparte: ya viene dentro de output_tokens.
        """
        price = _price_for(self.model)
        if price is None:
            return None
        price_in, price_out = price
        return (
            self.input_tokens * price_in + self.output_tokens * price_out
        ) / 1_000_000


_FENCE = re.compile(r"^\s*```(?:sql)?\s*(.*?)\s*```\s*$", re.S | re.I)


def _unwrap(text: str) -> str:
    """Quita el bloque de markdown si el modelo lo puso.

    Esto no es parseo de SQL: es desenvolver el formato de la respuesta. El
    SQL que queda adentro no se valida ni se toca.
    """
    match = _FENCE.match(text)
    body = match.group(1) if match else text
    return body.strip().rstrip(";").strip()


def model_name() -> str:
    return os.environ.get("TXT2SQL_MODEL", DEFAULT_MODEL)


def generate_sql(
    question: str,
    schema: str,
    model: str | None = None,
    client: OpenAI | None = None,
) -> Generation:
    """Una llamada. Devuelve el SQL y lo que costó."""
    model = model or model_name()
    client = client or OpenAI()

    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=USER_TEMPLATE.format(schema=schema, question=question),
        # No dejar la respuesta guardada del lado de OpenAI. El proyecto
        # guarda sus propios resultados; no hace falta una segunda copia
        # fuera de nuestro control.
        store=False,
    )

    raw = response.output_text or ""
    usage = response.usage

    reasoning = 0
    if usage is not None and usage.output_tokens_details is not None:
        reasoning = usage.output_tokens_details.reasoning_tokens or 0

    return Generation(
        sql=_unwrap(raw),
        model=response.model,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        reasoning_tokens=reasoning,
        raw=raw,
    )
