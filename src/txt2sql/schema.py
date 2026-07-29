"""Introspecciona el esquema real de la base y lo vuelca a texto.

El texto que sale de aquí es lo que se le manda al modelo. No hay ningún
esquema escrito a mano en el código: si cambia la base, cambia el prompt.

POR QUÉ SE USA `PRAGMA table_info` Y NO `sqlite_master.sql`
-----------------------------------------------------------
SQLite guarda el texto literal del CREATE TABLE, comentarios `--` incluidos.
El CREATE TABLE de data/build_db.py está anotado con las ocho trampas del
dataset. Volcar `sqlite_master.sql` tal cual le entregaría al modelo la
respuesta a cada trampa dentro del propio prompt.

`PRAGMA table_info` devuelve el catálogo ya parseado: nombre, tipo, NOT NULL,
default y llave primaria, sin comentarios. Sigue siendo el esquema real —de
hecho es la versión que el motor de verdad usa— y deja que la rebanada 1
muestre cómo falla el modelo sin ayuda.

Darle pistas al modelo (comentarios, valores de ejemplo, cardinalidades) es
una variable legítima, pero se prende a propósito en una rebanada posterior,
no de contrabando en ésta.

INYECCIÓN DE VALORES (rebanada 2)
----------------------------------
`dump_schema(conn, with_values=True)` agrega un bloque de comentarios al final
del DDL con los valores distintos de las columnas. El DDL de arriba no cambia
ni un byte: la única diferencia entre las dos configuraciones es ese bloque.

Tres reglas, todas automáticas —salen de `PRAGMA table_info`, ninguna depende
de conocer el dominio:

1. **Completos o nada. Nunca una muestra.** Es la regla de diseño del
   ROADMAP. Enseñarle 10 de 800 valores hace que el modelo asuma que ésos son
   todos. Para las columnas que no califican va una línea de conteo
   (`N valores distintos, no listados`) y jamás un ejemplo.

2. **Ni llaves primarias ni foráneas.** Un id no le sirve al modelo para
   escribir un literal. Ojo con la consecuencia: `financials.fiscal_year` es
   parte de la llave primaria compuesta, así que 2023 y 2024 NO se listan. El
   modelo sigue teniendo que adivinar qué años existen, y eso puede explicar
   fallas residuales de adivinanza de literales aun con los valores prendidos.

3. **Solo columnas de texto o fecha. Las numéricas nunca**, sin importar su
   cardinalidad. El tipo declarado sale de `PRAGMA table_info`.

   El motivo de la #3 es de medición, no de estética. `financials` tiene
   cuatro filas, así que sus columnas numéricas caen todas bajo el umbral y
   entrarían completas al prompt. Eso pondría 35,441,452 y 36,801.4 lado a
   lado en el texto y mataría la trampa #1: si el modelo acierta en escalas ya
   no habría forma de saber si razonó sobre `unit_scale` o si nada más vio dos
   magnitudes absurdamente distintas. Un acierto que no se puede atribuir no
   sirve de evidencia.

   Y de todos modos adivinar literales es un problema de strings. Nadie
   escribe `WHERE revenues = 35441452`, así que listar números no aporta al
   objetivo de la rebanada y solo mete un confusor.
"""

from __future__ import annotations

import sqlite3

# Umbral de cardinalidad: hasta acá se listan todos los valores; pasando de
# acá va la línea de conteo. Es la variable de la rebanada 2 y por eso va en
# el nombre del archivo de resultados.
MAX_CARDINALITY = 20

# Se listan los valores de una columna solo si su tipo declarado es de texto o
# de fecha. Las claves siguen el orden de precedencia de las reglas de afinidad
# de SQLite: 'INT' gana primero, así que un INTEGER nunca cae acá por accidente.
# DATE y TIME van explícitas porque en SQLite tienen afinidad NUMERIC, y una
# fecha sí es un literal que el modelo necesita escribir bien.
_TEXTUAL_TYPE_KEYS = ("CHAR", "CLOB", "TEXT", "DATE", "TIME")


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Tablas de usuario, en orden de creación. Excluye las internas."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY rowid"
    ).fetchall()
    return [r[0] for r in rows]


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Columnas de la llave primaria, en orden.

    En `PRAGMA table_info` la columna `pk` no es un booleano: es la posición
    1-based dentro de la llave primaria, y 0 si la columna no participa. Una
    llave compuesta da 1, 2, 3...
    """
    rows = [
        (pk, name)
        for _cid, name, _type, _notnull, _default, pk in conn.execute(
            f'PRAGMA table_info("{table}")'
        )
        if pk
    ]
    return [name for _pos, name in sorted(rows)]


def _column_lines(conn: sqlite3.Connection, table: str) -> list[str]:
    # Una llave primaria de una sola columna se declara pegada a la columna.
    # Una compuesta tiene que salir como restricción de tabla, abajo.
    pk_cols = _pk_columns(conn, table)
    inline_pk = pk_cols[0] if len(pk_cols) == 1 else None

    lines = []
    for _cid, name, coltype, notnull, default, _pk in conn.execute(
        f'PRAGMA table_info("{table}")'
    ):
        parts = [f"  {name} {coltype or 'BLOB'}"]
        if name == inline_pk:
            parts.append("PRIMARY KEY")
        if notnull:
            parts.append("NOT NULL")
        if default is not None:
            parts.append(f"DEFAULT {default}")
        lines.append(" ".join(parts))

    if len(pk_cols) > 1:
        lines.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")

    return lines


def _foreign_key_lines(conn: sqlite3.Connection, table: str) -> list[str]:
    lines = []
    for row in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
        # id, seq, referenced_table, from_col, to_col, on_update, on_delete, match
        _id, _seq, ref_table, from_col, to_col = row[0], row[1], row[2], row[3], row[4]
        lines.append(f"  FOREIGN KEY ({from_col}) REFERENCES {ref_table}({to_col})")
    return lines


def _key_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Columnas que participan en la llave primaria o en alguna foránea."""
    keys = set(_pk_columns(conn, table))
    keys.update(row[3] for row in conn.execute(f'PRAGMA foreign_key_list("{table}")'))
    return keys


def _is_textual(declared_type: str | None) -> bool:
    """¿El tipo declarado es de texto o de fecha? Ver regla #3 del docstring."""
    coltype = (declared_type or "").upper()
    if "INT" in coltype:
        return False
    return any(key in coltype for key in _TEXTUAL_TYPE_KEYS)


def _sql_literal(value: object) -> str:
    """El valor tal como el modelo tendría que escribirlo en un WHERE."""
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def _value_lines(
    conn: sqlite3.Connection, table: str, max_cardinality: int
) -> list[str]:
    keys = _key_columns(conn, table)
    lines = []

    for _cid, name, coltype, _notnull, _default, _pk in conn.execute(
        f'PRAGMA table_info("{table}")'
    ):
        if name in keys:
            continue

        # COUNT(DISTINCT) ignora los NULL, y el listado de abajo también. Un
        # NULL no es un valor que se pueda escribir en un WHERE con `=`.
        n_distinct = conn.execute(
            f'SELECT COUNT(DISTINCT "{name}") FROM "{table}"'
        ).fetchone()[0]

        if n_distinct == 0:
            lines.append(f"--   {name}: sin valores")
        elif not _is_textual(coltype) or n_distinct > max_cardinality:
            lines.append(f"--   {name}: {n_distinct} valores distintos, no listados")
        else:
            values = [
                row[0]
                for row in conn.execute(
                    f'SELECT DISTINCT "{name}" FROM "{table}"'
                    f' WHERE "{name}" IS NOT NULL ORDER BY 1'
                )
            ]
            listed = ", ".join(_sql_literal(v) for v in values)
            lines.append(f"--   {name} ({n_distinct} valores): {listed}")

    return lines


def dump_values(
    conn: sqlite3.Connection, max_cardinality: int = MAX_CARDINALITY
) -> str:
    """Bloque de valores distintos por columna, como comentarios SQL."""
    blocks = []
    for table in table_names(conn):
        lines = _value_lines(conn, table, max_cardinality)
        if lines:
            blocks.append(f"-- Valores de {table}:\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def dump_schema(
    conn: sqlite3.Connection,
    with_values: bool = False,
    max_cardinality: int = MAX_CARDINALITY,
) -> str:
    """Devuelve el esquema completo como DDL reconstruido.

    Con `with_values=True` se le anexa el bloque de valores. El DDL sale
    idéntico byte por byte en los dos casos: el bloque es la única variable.
    """
    blocks = []
    for table in table_names(conn):
        lines = _column_lines(conn, table)
        # Las llaves foráneas salen al revés del orden de declaración.
        lines.extend(reversed(_foreign_key_lines(conn, table)))
        body = ",\n".join(lines)
        blocks.append(f"CREATE TABLE {table} (\n{body}\n);")

    ddl = "\n\n".join(blocks)
    if not with_values:
        return ddl

    values = dump_values(conn, max_cardinality)
    return f"{ddl}\n\n{values}" if values else ddl
