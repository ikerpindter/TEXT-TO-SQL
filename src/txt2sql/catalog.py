"""El catálogo de la base, leído del motor y no escrito a mano.

Es la mitad no sintáctica del detector de fan-out. El árbol del SQL dice qué
tablas se unen; el catálogo dice **cuál de los dos lados es el "uno"**, y esa
dirección no se puede sacar del texto de la query.

DE DÓNDE SALE LA DIRECCIÓN DEL JOIN
------------------------------------
**Solo de llaves foráneas declaradas.** `PRAGMA foreign_key_list` da la FK; el
lado "uno" es la tabla referenciada, y solo cuando la columna referenciada es
única por sí sola: PK de una columna, o con índice UNIQUE de una columna.

**Nunca se infiere de los datos.** Que hoy `homes.community_id` tenga a lo mucho
una comunidad por casa es un hecho sobre las filas de hoy, no sobre el esquema, y
un detector que aprenda la dirección de los datos cambia de opinión cuando cambian
los datos.

La cláusula del índice UNIQUE **no tiene blanco en esta base**: el único índice
único es el autoindex de la PK compuesta de `financials`, con `origin='pk'`, y no
hay ninguna restricción UNIQUE declarada aparte de las PKs. Se implementa igual
porque el alcance de v1 la nombra, pero hoy el lado "uno" se determina solo por PK.

LOS TRES GUARDS DE `rowid`
--------------------------
El multiplicador se mide con `COUNT(T.rowid)`, y `rowid` tiene tres formas de
mentir. Dos se comprueban aquí, contra el catálogo, y la tercera —que `T` sea
tabla base— se comprueba en el AST porque el catálogo no la puede ver.

1. **`WITHOUT ROWID`**: la tabla no tiene `rowid` y la consulta truena. Va a
   `not_analyzed`. Medido el 2026-07-30: **cero tablas** en esta base.
2. **Una columna llamada `rowid`, `oid` o `_rowid_`** sombrea al `rowid` real, así
   que `COUNT(T.rowid)` contaría la columna del usuario sin avisar. Medido:
   **cero columnas** así en las cuatro tablas.
3. La tercera vive en `fanout.py`: sobre una subconsulta derivada, `T.rowid`
   **resuelve a NULL sin error**, así que `COUNT` da 0 y el caso quedaría
   clasificado silenciosamente como "T no aporta filas" teniendo filas.

Los dos de aquí no tienen blanco hoy. Se implementan porque una base que cambie
—o el set adversario de una rebanada posterior— sí los puede producir, y el modo
de falla del guard ausente es silencioso en un caso y ruidoso en el otro.

POR QUÉ NO SE REUSA `schema.py`
-------------------------------
`schema.py` construye el texto que se le manda al modelo y sus reglas son de
prompt: qué se lista, qué no, umbral de cardinalidad. Este módulo construye
hechos estructurales para decidir un veredicto. Comparten el `PRAGMA` y nada más;
atarlos haría que un cambio de política de prompt moviera un veredicto.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Los tres nombres que SQLite acepta como alias del rowid. Si una columna se
# llama así, sombrea al rowid real y `COUNT(T.rowid)` deja de medir identidad de
# fila sin dar ningún error.
ROWID_ALIASES = frozenset({"rowid", "oid", "_rowid_"})


@dataclass(frozen=True)
class ForeignKey:
    """Una FK declarada, ya resuelta a columnas concretas.

    `PRAGMA foreign_key_list` puede devolver `to_column` en NULL cuando la FK
    referencia la PK del padre implícitamente. Aquí ya viene resuelta.
    """

    child_table: str
    child_column: str
    parent_table: str
    parent_column: str

    @property
    def text(self) -> str:
        """Cómo se escribe el join en un mensaje. Tablas reales, no alias."""
        return (
            f"{self.child_table}.{self.child_column}"
            f" = {self.parent_table}.{self.parent_column}"
        )


@dataclass(frozen=True)
class Catalog:
    columns: dict[str, dict[str, str]]
    primary_keys: dict[str, list[str]]
    foreign_keys: tuple[ForeignKey, ...]
    # Columnas únicas por sí solas: PK de una columna o índice UNIQUE de una
    # columna. Una columna de una PK compuesta NO entra: no es única sola.
    unique_columns: dict[str, frozenset[str]]
    without_rowid: frozenset[str]
    rowid_shadowed: dict[str, tuple[str, ...]]

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(self.columns)

    def qualify_schema(self) -> dict[str, dict[str, str]]:
        """El esquema en la forma que `qualify` acepta: {tabla: {columna: TIPO}}."""
        return {table: dict(cols) for table, cols in self.columns.items()}

    def one_side_fk(self, child: str, child_col: str, parent: str, parent_col: str):
        """La FK que hace de `parent` el lado "uno", o None si no la hay.

        Exige las dos cosas: que la FK esté declarada y que la columna
        referenciada sea única por sí sola. Una FK contra una columna no única no
        establece un lado "uno" y por lo tanto no establece dirección.
        """
        for fk in self.foreign_keys:
            if (
                fk.child_table == child
                and fk.child_column == child_col
                and fk.parent_table == parent
                and fk.parent_column == parent_col
            ):
                if parent_col in self.unique_columns.get(parent, frozenset()):
                    return fk
                return None
        return None

    def rowid_is_safe(self, table: str) -> str | None:
        """None si se puede usar `table.rowid`; si no, la razón por la que no."""
        if table in self.without_rowid:
            return "without_rowid"
        if table in self.rowid_shadowed:
            return "rowid_shadowed"
        return None


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
    ]


def _primary_key(info: list[tuple]) -> list[str]:
    """Columnas de la PK en orden. En `PRAGMA table_info` `pk` es la posición."""
    positions = [(pk, name) for _cid, name, _t, _nn, _d, pk in info if pk]
    return [name for _pos, name in sorted(positions)]


def load(conn: sqlite3.Connection) -> Catalog:
    """Lee el catálogo completo. Read-only, sin llamadas a API."""
    tables = _user_tables(conn)

    columns: dict[str, dict[str, str]] = {}
    primary_keys: dict[str, list[str]] = {}
    unique_columns: dict[str, frozenset[str]] = {}
    without_rowid: set[str] = set()
    rowid_shadowed: dict[str, tuple[str, ...]] = {}

    for table in tables:
        info = list(conn.execute(f'PRAGMA table_info("{table}")'))
        columns[table] = {name: (ctype or "BLOB") for _c, name, ctype, _n, _d, _p in info}
        primary_keys[table] = _primary_key(info)

        shadow = tuple(
            name for _c, name, *_rest in info if name.lower() in ROWID_ALIASES
        )
        if shadow:
            rowid_shadowed[table] = shadow

        ddl_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        # El DDL guardado es texto literal: se normaliza el espacio antes de
        # buscar, porque `WITHOUT  ROWID` con dos espacios es válido.
        if ddl_row and ddl_row[0] and "WITHOUT ROWID" in " ".join(ddl_row[0].upper().split()):
            without_rowid.add(table)

        unique: set[str] = set()
        if len(primary_keys[table]) == 1:
            unique.add(primary_keys[table][0])
        for index in conn.execute(f'PRAGMA index_list("{table}")'):
            # (seq, name, unique, origin, partial)
            if not index[2] or index[4]:
                continue  # ni no-únicos ni parciales: un índice parcial no garantiza
            index_cols = [row[2] for row in conn.execute(f'PRAGMA index_info("{index[1]}")')]
            if len(index_cols) == 1 and index_cols[0] is not None:
                unique.add(index_cols[0])
        unique_columns[table] = frozenset(unique)

    # Las FKs van en una segunda pasada porque resolver un `to_column` en NULL
    # necesita la PK del padre, que puede haberse creado después que el hijo.
    foreign_keys: list[ForeignKey] = []
    for table in tables:
        for row in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            # (id, seq, table, from, to, on_update, on_delete, match)
            parent, child_col, parent_col = row[2], row[3], row[4]
            if parent_col is None:
                parent_pk = primary_keys.get(parent, [])
                if len(parent_pk) != 1:
                    # FK implícita contra una PK compuesta: no se puede resolver a
                    # una sola columna y no establece un lado "uno".
                    continue
                parent_col = parent_pk[0]
            foreign_keys.append(ForeignKey(table, child_col, parent, parent_col))

    return Catalog(
        columns=columns,
        primary_keys=primary_keys,
        foreign_keys=tuple(foreign_keys),
        unique_columns=unique_columns,
        without_rowid=frozenset(without_rowid),
        rowid_shadowed=rowid_shadowed,
    )
