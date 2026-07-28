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
"""

from __future__ import annotations

import sqlite3


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


def dump_schema(conn: sqlite3.Connection) -> str:
    """Devuelve el esquema completo como DDL reconstruido."""
    blocks = []
    for table in table_names(conn):
        lines = _column_lines(conn, table)
        # Las llaves foráneas salen al revés del orden de declaración.
        lines.extend(reversed(_foreign_key_lines(conn, table)))
        body = ",\n".join(lines)
        blocks.append(f"CREATE TABLE {table} (\n{body}\n);")
    return "\n\n".join(blocks)
