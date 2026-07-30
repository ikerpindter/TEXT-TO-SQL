"""El render del detector de fan-out para la CLI.

**Nombra la consecuencia, no la mecánica.** Va "el presupuesto se sumó una vez por
cada casa de la comunidad, no una vez por comunidad". **No va** "fan-out detectado
en el join": eso describe el árbol sintáctico, que es un dato sobre nuestro
detector y no sobre el número que la persona está mirando.

**Marca y explica, no bloquea.** La respuesta se sigue imprimiendo siempre, arriba
de esto. Bloquear convertiría una falla silenciosa en una ruidosa, que es mejor,
pero también mataría consultas legítimas.

LA REGLA QUE MANDA SOBRE TODO ESTE ARCHIVO
-------------------------------------------
**Nunca afirmar por cuánto está mal un número cuando solo se tiene
`row_multiplier`.**

`row_multiplier` cuenta **cuántas veces se repitió cada fila**. El error de la
cifra es otra cosa, porque está ponderado por los valores de la columna que se
agregó. Los dos números difieren, y **la brecha cambia de signo**: en Q4 el
multiplicador queda por debajo (40.0 contra 41.285653) y en A6 por encima (39.7
contra 39.6336). No acota ni por arriba ni por abajo, así que **queda prohibido
cualquier "al menos Nx" y cualquier "a lo mucho Nx"**, y también el atajo de
dividir el reportado entre el multiplicador: sobre Q4 eso da 359,701,250 contra
348,500,000 reales, 3.21% de error con cara de cifra exacta.

Un guardrail que reporta un factor de inflación que no midió está fabricando
precisión, que es exactamente la falla que le medimos al modelo en la rebanada 2.

TRES COSAS MÁS QUE EL TEXTO TIENE QUE RESPETAR
-----------------------------------------------
- **`AVG` se dice "distorsionado", no "inflado".** Para `SUM` y `COUNT` el efecto
  siempre va hacia arriba; para `AVG` el resultado se vuelve un promedio ponderado
  y puede ir en cualquier dirección. Medido sobre esta base: bajó, de 37,162,500 a
  37,100,377.83.
- **Con `GROUP BY`, la medición es global.** Prueba que existe duplicación en algún
  lugar del resultado, **no** que la fila que la persona está viendo esté afectada.
  El texto no le dice que su fila está inflada.
- **Los dos subcasos de `no_contributing_rows` piden textos distintos**, y el
  motivo es de producto: uno muestra un `NULL` y el otro muestra un **`0`**. El `0`
  es el peligroso, porque **parece una respuesta** —"cero casas en backlog" se lee
  como un hecho verificado— mientras que un `NULL` al menos se ve raro y hace que
  alguien pregunte.
"""

from __future__ import annotations

from txt2sql import fanout

# Cada razón dicha en términos de qué no se revisó, no del nombre interno del
# guard. La persona no tiene por qué saber qué es un `non_fk_join`.
_REASONS = {
    fanout.REASON_SELF_JOIN: "une una tabla consigo misma",
    fanout.REASON_WINDOW: "usa una función de ventana",
    fanout.REASON_SET_OPERATION: "usa UNION, INTERSECT o EXCEPT",
    fanout.REASON_NON_FK_JOIN: (
        "hay un join que no sigue ninguna llave foránea declarada, así que no hay"
        " forma de saber cuál lado se repite"
    ),
    fanout.REASON_AMBIGUOUS_COLUMN: (
        "hay una columna que no se puede resolver a una sola tabla"
    ),
    fanout.REASON_CORRELATED_SUBQUERY: (
        "trae una subconsulta correlacionada en la lista del SELECT"
    ),
    fanout.REASON_NON_BASE_TABLE: (
        "el agregado cae sobre un CTE o una subconsulta, y ahí no se puede"
        " identificar cada fila para saber si se repitió"
    ),
    fanout.REASON_WITHOUT_ROWID: (
        "una de las tablas es WITHOUT ROWID y no se puede identificar cada fila"
    ),
    fanout.REASON_ROWID_SHADOWED: (
        "una columna se llama rowid y tapa la identidad de fila"
    ),
    fanout.REASON_UNATTRIBUTABLE: (
        "el único agregado cuenta filas sin mirar ninguna columna, así que no hay"
        " a qué atribuirle la repetición"
    ),
    fanout.REASON_PARSE_ERROR: "no se pudo interpretar el SQL",
    fanout.REASON_NOT_A_SELECT: "no es un SELECT",
    fanout.REASON_QUALIFY_ERROR: "no se pudieron resolver sus columnas",
    fanout.REASON_PROBE_FAILED: "la consulta de medición falló",
}


def _number(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _times(multiplier: float) -> str:
    """`39.7` y no `39.70`. El número medido, sin adornos."""
    text = f"{multiplier:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _consequence(finding: fanout.Finding) -> list[str]:
    """La frase que nombra qué le pasó al número, sin decir por cuánto."""
    columns = ", ".join(finding.columns) or finding.table
    multiplier = finding.row_multiplier

    if finding.shape == fanout.FAN_TRAP:
        verb = {"SUM": "se sumó", "TOTAL": "se sumó", "COUNT": "se contó"}.get(
            finding.aggregate_function, "se promedió"
        )
        lines = [
            f"{columns} {verb} una vez por cada fila de {finding.many_side},"
            f" no una vez por {finding.one_side}."
        ]
        if finding.aggregate_function == "AVG":
            lines.append(
                f"El promedio quedó ponderado por cuántas filas de"
                f" {finding.many_side} tiene cada {finding.one_side}: distorsionado,"
                f" y puede haber quedado por arriba o por abajo."
            )
    elif finding.shape == fanout.CHASM_TRAP:
        lines = [
            f"Cada fila de {finding.table} se repitió una vez por cada fila de"
            f" {finding.many_side} colgada de la misma {finding.one_side}."
        ]
        if finding.aggregate_function == "AVG":
            lines.append(
                "El promedio quedó ponderado por esas repeticiones: distorsionado,"
                " y puede haber quedado por arriba o por abajo."
            )
    else:
        lines = [
            f"Las filas de {finding.table} entraron repetidas al cálculo de"
            f" {finding.aggregate}."
        ]
        lines.append(
            "No pude nombrar qué join las repite, así que lo único que puedo"
            " afirmar es que la repetición existe y está medida."
        )

    if multiplier is not None:
        lines.append(
            f"Cada fila de {finding.table} entró {_times(multiplier)} veces"
            f" al cálculo ({finding.contributing_rows:,} filas sobre"
            f" {finding.distinct_rows:,} distintas)."
        )
    if finding.join_path:
        lines.append("Por el join: " + " · ".join(finding.join_path))
    return lines


def _how_wrong(finding: fanout.Finding) -> list[str]:
    """Cuánto cambia la cifra. Solo si se midió; si no, se dice que no se midió."""
    if finding.value_inflation is not None:
        return [
            f"Qué tanto cambia el número: {_times(finding.value_inflation)}x.",
            f"Sin la repetición, {finding.aggregate} da"
            f" {_number(finding.deduplicated_value)} en vez de"
            f" {_number(finding.reported_value)}.",
            "Ese valor es un diagnóstico, no la respuesta a tu pregunta.",
        ]
    # Ésta es la línea que define el proyecto. El multiplicador NO es el factor de
    # error de la cifra y no se puede convertir en uno.
    detail = (
        f" {_times(finding.row_multiplier)} es cuántas veces se repitió cada fila,"
        f" no por cuánto está mal la cifra."
        if finding.row_multiplier is not None
        else ""
    )
    return [f"Qué tanto cambia el número: no se midió.{detail}"]


def _finding_block(finding: fanout.Finding) -> list[str]:
    lines = _consequence(finding)
    lines.extend(_how_wrong(finding))
    if finding.grouped:
        lines.append(
            "La medición es global sobre todo el resultado: dice que hay"
            " repetición en algún lugar de la tabla de arriba, no que la fila que"
            " estás viendo esté afectada."
        )
    return lines


def render(result: fanout.FanoutResult) -> str:
    """El bloque completo para la CLI. Cadena vacía si no hay nada que decir."""
    head: str
    body: list[str] = []

    if result.verdict == fanout.NOT_ANALYZED:
        reason = _REASONS.get(result.reason, result.reason or "razón desconocida")
        head = "no revisé esta respuesta por filas repetidas"
        body = [f"{reason.capitalize()}.", "No es que esté bien: es que no la revisé."]
        if result.unattributed_aggregates:
            body.append("Sin revisar: " + ", ".join(result.unattributed_aggregates))
        return _block("i", head, body)

    if result.verdict == fanout.NO_CONTRIBUTING_ROWS:
        if result.subcase == fanout.EMPTY_SOURCE:
            head = "el NULL de arriba no es un dato: ninguna fila pasó los filtros"
            body = [
                "El agregado se calculó sobre cero filas, y sobre cero filas siempre"
                " devuelve exactamente una fila con un NULL adentro.",
            ]
        else:
            missing = result.findings[0].table if result.findings else "la tabla"
            source_rows = result.findings[0].source_rows if result.findings else 0
            head = f"ese 0 no es un conteo: es la ausencia de {missing}"
            body = [
                f"La consulta recorrió {source_rows:,} filas y ninguna trajo un"
                f" registro de {missing}, así que el agregado contó cero.",
                'Se lee como una respuesta —"cero"— y no lo es.',
            ]
        for finding in result.findings:
            body.append("")
            body.append(
                f"Además, {finding.aggregate} tiene la estructura que repite filas,"
                f" y con estos datos no se pudo medir cuánto."
            )
        return _block("!", head, body)

    if result.verdict == fanout.INFLATED:
        head = "esta respuesta se calculó sobre filas repetidas"
        for index, finding in enumerate(result.findings):
            if index:
                body.append("")
            body.extend(_finding_block(finding))
        body.extend(_unchecked(result))
        return _block("!", head, body)

    if result.verdict == fanout.SHAPE_NO_INFLATION:
        head = "la estructura permitía repetir filas y con estos datos no las repitió"
        for index, finding in enumerate(result.findings):
            if index:
                body.append("")
            body.append(
                f"{finding.aggregate} cae donde un join podría repetir filas, pero"
                f" hoy cada fila de {finding.table} entra exactamente una vez."
            )
            if finding.join_path:
                body.append("Por el join: " + " · ".join(finding.join_path))
        body.append(
            "Con otros datos la misma consulta sí inflaría: lo que la salva es la"
            " cardinalidad de hoy, no cómo está escrita."
        )
        body.extend(_unchecked(result))
        return _block("i", head, body)

    # clean
    head = "sin filas repetidas medidas"
    body = [
        "Es lo único que revisé. Escalas de unidades, año fiscal y literales de"
        " texto no entran en este chequeo, así que el número de arriba puede"
        " seguir estando mal por otra razón.",
    ]
    body.extend(_unchecked(result))
    return _block("ok", head, body)


def _unchecked(result: fanout.FanoutResult) -> list[str]:
    if not result.unattributed_aggregates:
        return []
    return [
        "",
        "Sin revisar: "
        + ", ".join(result.unattributed_aggregates)
        + " — cuenta filas sin mirar ninguna columna, así que no hay a qué"
        " atribuirle la repetición.",
    ]


_MARKS = {"!": "[!]", "i": "[i]", "ok": "[ok]"}


def _block(mark: str, head: str, body: list[str], width: int = 76) -> str:
    lines = [f"{_MARKS[mark]} {head}"]
    for paragraph in body:
        if not paragraph:
            lines.append("")
            continue
        lines.extend(f"    {line}" for line in _wrap(paragraph, width - 4))
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if current and sum(len(w) + 1 for w in current) + len(word) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines
