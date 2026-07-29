"""Smoke test de las cuatro APIs de sqlglot de las que depende el detector.

    uv run python evals/gold/smoke_sqlglot.py

No llama al modelo. Abre portfolio.db en modo solo lectura. Costo: $0.

QUÉ AFIRMA ESTE ARCHIVO, Y QUÉ NO
---------------------------------
Afirma una sola cosa: **que las cuatro APIs de sqlglot que el detector va a usar
se comportan como esperamos en la versión pineada.** Es el gate de la
dependencia.

No afirma nada sobre el corpus. **No lee `corpus_sql.json` y tiene que poder
correr sin que ese archivo exista.** Son dos afirmaciones distintas y mezclarlas
crea una dependencia circular: el gate de la librería no puede depender del
artefacto de datos que se construye usando la librería. La verificación de que el
SQL del corpus parsea vive en `extract_corpus.py`, que es donde el corpus se
produce.

Por eso los fixtures de abajo están escritos a mano. Son SQL contra el esquema
real de `portfolio.db`, pero no salen de ninguna corrida.

Cubre las cuatro partes, cada una con su assert:

  a) parse_one con dialecto sqlite sobre los seis fixtures
  b) build_scope y traverse_scope sobre el fixture con CTE y los de subconsulta
  c) qualify contra el esquema real, verificando que una columna sin prefijo se
     resuelve a su tabla correcta
  d) PRAGMA foreign_key_list y PRAGMA table_info devolviendo FKs y PKs esperadas

La parte (c) es la que justifica el archivo. Es la única API cuya firma no estaba
verificada antes de la etapa 1, la única que reescribe el SQL, y la única que
lanza excepción por defecto cuando no puede resolver una columna
(`validate_qualify_columns=True`). Un smoke test que solo parsea prueba el camino
seguro y se salta el riesgoso.

sqlglot sube el MINOR cuando rompe compatibilidad, así que la versión está
pineada exacta en `pyproject.toml`. Cuando se suba a propósito, este archivo es
el que dice si se puede. El gate de la 30.14.0 fue este test, no la lectura línea
por línea del changelog; eso está anotado en `docs/ROADMAP.md`.

REGLA DE IMPORTS
----------------
Solo se importa de `sqlglot` y de `sqlglot.optimizer`. Nunca de rutas internas
como `sqlglot.expressions.aggregate`: en el 30.x `expressions` está partido en
submódulos, y atarse a una ruta interna nos deja expuestos a un refactor de
upstream en un PATCH.

Un detalle verificado a mano: en 30.14.0 el `__init__` de `sqlglot.optimizer`
expone `build_scope`, `traverse_scope`, `find_all_in_scope`, `find_in_scope`,
`walk_in_scope`, `Scope`, `optimize` y `RULES` por un `__getattr__` PEP 562, pero
**`qualify` no está en esa lista.** `from sqlglot.optimizer import qualify`
devuelve el MÓDULO, no la función, así que abajo se llama `qualify_mod.qualify`.
"""

from __future__ import annotations

import sqlite3
import sys
import traceback
from pathlib import Path

import sqlglot
from sqlglot.optimizer import build_scope, find_all_in_scope, traverse_scope
from sqlglot.optimizer import qualify as qualify_mod

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from txt2sql import db  # noqa: E402

DIALECT = "sqlite"

# Fixtures escritos a mano contra el esquema real de portfolio.db. No salen de
# ninguna corrida: este archivo no depende del corpus.
#
# Los dos últimos son deliberadamente la forma de las dos puertas de fan-out
# medidas en la rebanada 2 —agregar sobre el lado "uno" de un join a `homes`, y
# colgar `financials` de un join sin relación de grano real— porque son
# exactamente los árboles que el detector va a tener que leer.
FIXTURES: tuple[tuple[str, str], ...] = (
    (
        "simple",
        "SELECT COUNT(*) AS n FROM homes WHERE status = 'closed'",
    ),
    (
        # Columna sin prefijo sobre un join: el caso de la parte (c).
        "join_agg_unprefixed",
        "SELECT SUM(budget_usd) AS total, COUNT(*) AS n "
        "FROM communities "
        "JOIN homes ON homes.community_id = communities.id "
        "WHERE communities.state = 'TX'",
    ),
    (
        "cte",
        "WITH per_community AS ("
        "  SELECT community_id, COUNT(*) AS homes_n"
        "  FROM homes GROUP BY community_id"
        ") "
        "SELECT c.name, p.homes_n "
        "FROM communities c JOIN per_community p ON p.community_id = c.id",
    ),
    (
        "subquery_from",
        "SELECT t.state, SUM(t.lot_count) AS lots FROM ("
        "  SELECT state, lot_count FROM communities WHERE region = 'Texas'"
        ") AS t GROUP BY t.state",
    ),
    (
        "subquery_where",
        "SELECT COUNT(*) AS n FROM homes "
        "WHERE community_id IN (SELECT id FROM communities WHERE state = 'TX')",
    ),
    (
        # La segunda puerta de fan-out: financials colgada por company_id.
        "financials_join",
        "SELECT c.name, SUM(f.backlog_value) AS backlog "
        "FROM companies c "
        "JOIN financials f ON f.company_id = c.id "
        "JOIN communities m ON m.company_id = c.id "
        "GROUP BY c.name",
    ),
)

FIXTURE_SQL = dict(FIXTURES)

# Esquema esperado de portfolio.db. Hardcodeado a propósito: si la base cambia,
# este test tiene que gritar, no adaptarse en silencio.
EXPECTED_PKS = {
    "companies": ["id"],
    # Llave compuesta. `fiscal_year` es parte de la PK, y por eso la rebanada 2
    # no lista 2023 ni 2024 en el prompt.
    "financials": ["company_id", "fiscal_year"],
    "communities": ["id"],
    "homes": ["id"],
}

EXPECTED_FKS = {
    "companies": set(),
    "financials": {("company_id", "companies", "id")},
    "communities": {("company_id", "companies", "id")},
    "homes": {("community_id", "communities", "id")},
}


def pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Columnas de la PK en orden. En PRAGMA table_info `pk` es la posición."""
    rows = [
        (pk, name)
        for _cid, name, _t, _nn, _d, pk in conn.execute(f'PRAGMA table_info("{table}")')
        if pk
    ]
    return [name for _pos, name in sorted(rows)]


def user_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
    ]


def build_schema_dict(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Esquema en la forma que `qualify` acepta: {tabla: {columna: TIPO}}.

    Sale de PRAGMA table_info, igual que el prompt que se le manda al modelo. No
    hay ningún esquema escrito a mano.
    """
    return {
        table: {
            name: (coltype or "BLOB")
            for _cid, name, coltype, _nn, _d, _pk in conn.execute(
                f'PRAGMA table_info("{table}")'
            )
        }
        for table in user_tables(conn)
    }


# --------------------------------------------------------------------------
# (a) parse_one con dialecto sqlite
# --------------------------------------------------------------------------
def part_a() -> str:
    failures = []
    for name, sql in FIXTURES:
        try:
            tree = sqlglot.parse_one(sql, dialect=DIALECT)
        except Exception:  # noqa: BLE001 - cualquier excepción es una falla
            failures.append((name, traceback.format_exc()))
            continue
        if tree is None:
            failures.append((name, "parse_one devolvió None"))
        elif not isinstance(tree, sqlglot.exp.Select):
            failures.append((name, f"no es un Select, es {type(tree).__name__}"))

    assert not failures, "parse_one falló en:\n" + "\n".join(
        f"  {n}\n{err}" for n, err in failures
    )
    return f"{len(FIXTURES)} fixtures parsean como Select"


# --------------------------------------------------------------------------
# (b) build_scope y traverse_scope
# --------------------------------------------------------------------------
def part_b() -> str:
    # El CTE, la subconsulta en FROM y la subconsulta en WHERE. Los tres tienen
    # que dar más de un scope; si sqlglot dejara de anidarlos, el detector
    # perdería la frontera entre el query externo y el interno.
    cases = ("cte", "subquery_from", "subquery_where")
    checked = []

    for name in cases:
        tree = sqlglot.parse_one(FIXTURE_SQL[name], dialect=DIALECT)

        root = build_scope(tree)
        assert root is not None, f"build_scope devolvió None en el fixture {name!r}"

        scopes = traverse_scope(tree)
        assert len(scopes) >= 2, (
            f"el fixture {name!r} debería dar >=2 scopes, dio {len(scopes)}"
        )

        # El scope raíz tiene que conocer sus fuentes: de ahí sale el join.
        assert root.sources, f"el scope raíz de {name!r} no tiene sources"

        # find_all_in_scope no debe cruzar la frontera del scope. Las columnas
        # que encuentre en la raíz son las de la raíz, no las de la subconsulta.
        cols = list(find_all_in_scope(root.expression, sqlglot.exp.Column))
        all_cols = list(tree.find_all(sqlglot.exp.Column))
        assert len(cols) <= len(all_cols), (
            f"find_all_in_scope devolvió más columnas ({len(cols)}) que el árbol "
            f"completo ({len(all_cols)}) en {name!r}"
        )

        checked.append(f"{name} scopes={len(scopes)} sources={len(root.sources)}")

    # El CTE tiene que ser reconocible como CTE, no solo como scope extra.
    cte_tree = sqlglot.parse_one(FIXTURE_SQL["cte"], dialect=DIALECT)
    assert cte_tree.find(sqlglot.exp.CTE) is not None, (
        "el fixture 'cte' dejó de exponer un nodo CTE"
    )

    return "; ".join(checked)


# --------------------------------------------------------------------------
# (c) qualify con el esquema real
# --------------------------------------------------------------------------
def part_c() -> str:
    """La API riesgosa: resolver una columna sin prefijo a su tabla correcta.

    `budget_usd` vive solo en `communities`. El fixture es la forma exacta de la
    trampa de fan-out de Q4: agregar una columna del lado "uno" de un join
    uno-a-muchos. Si qualify no la ata a `communities`, el detector no tiene de
    dónde agarrarse.
    """
    conn = db.connect()
    schema = build_schema_dict(conn)

    assert "budget_usd" in schema["communities"], (
        "budget_usd no está en communities; el esquema cambió"
    )

    qualified = qualify_mod.qualify(
        sqlglot.parse_one(FIXTURE_SQL["join_agg_unprefixed"], dialect=DIALECT),
        dialect=DIALECT,
        schema=schema,
        # Esquema explícito: que no invente columnas que no se le dieron.
        infer_schema=False,
    )

    targets = [
        col for col in qualified.find_all(sqlglot.exp.Column) if col.name == "budget_usd"
    ]
    assert targets, "qualify no dejó ninguna columna budget_usd en el árbol"
    tables = {col.table for col in targets}
    assert tables == {"communities"}, (
        f"budget_usd quedó resuelta a {tables}, se esperaba {{'communities'}}"
    )

    # La agregación tiene que seguir envolviendo esa columna: si qualify moviera
    # el SUM, el detector estaría leyendo un árbol distinto al que cree.
    sums = list(qualified.find_all(sqlglot.exp.Sum))
    assert len(sums) == 1, f"se esperaba 1 SUM, hay {len(sums)}"
    inner = sums[0].this
    assert isinstance(inner, sqlglot.exp.Column) and inner.name == "budget_usd", (
        f"el SUM ya no envuelve budget_usd, envuelve {inner!r}"
    )
    assert inner.table == "communities", (
        f"la columna dentro del SUM quedó en {inner.table!r}, no en 'communities'"
    )

    # Contraprueba de que qualify de verdad valida. `name` existe en companies y
    # en communities, así que sin prefijo y con las dos en el FROM tiene que
    # tronar. Si esto NO truena, validate_qualify_columns dejó de validar y el
    # detector estaría confiando en una resolución que nunca ocurrió. Un assert
    # de que la resolución funciona no detecta que la validación se apagó.
    ambiguous = (
        "SELECT name FROM communities "
        "JOIN companies ON companies.id = communities.company_id"
    )
    try:
        qualify_mod.qualify(
            sqlglot.parse_one(ambiguous, dialect=DIALECT),
            dialect=DIALECT,
            schema=schema,
            infer_schema=False,
        )
    except Exception as exc:  # noqa: BLE001 - la excepción concreta es de sqlglot
        ambiguity = f"columna ambigua rechazada ({type(exc).__name__})"
    else:
        raise AssertionError(
            "qualify aceptó `name` con companies y communities en el FROM. "
            "validate_qualify_columns no está validando; revisar antes de confiar."
        )

    return f"budget_usd -> communities dentro del SUM; {ambiguity}"


# --------------------------------------------------------------------------
# (d) PRAGMA foreign_key_list y PRAGMA table_info
# --------------------------------------------------------------------------
def part_d() -> str:
    """Las FKs son la otra mitad del detector: sin ellas no hay lado 'uno'."""
    conn = db.connect()

    tables = user_tables(conn)
    assert set(tables) == set(EXPECTED_PKS), (
        f"tablas {sorted(tables)}, se esperaban {sorted(EXPECTED_PKS)}"
    )

    for table in tables:
        got_pk = pk_columns(conn, table)
        assert got_pk == EXPECTED_PKS[table], (
            f"PK de {table}: {got_pk}, se esperaba {EXPECTED_PKS[table]}"
        )

        # PRAGMA foreign_key_list devuelve las FKs al revés del orden de
        # declaración, así que se compara como conjunto.
        got_fk = {
            (row[3], row[2], row[4])
            for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        assert got_fk == EXPECTED_FKS[table], (
            f"FKs de {table}: {sorted(got_fk)}, se esperaban {sorted(EXPECTED_FKS[table])}"
        )

    n_fks = sum(len(v) for v in EXPECTED_FKS.values())
    return f"{len(tables)} tablas, PKs y {n_fks} FKs como se esperaba"


PARTS = [
    ("a) parse_one dialecto sqlite", part_a),
    ("b) build_scope / traverse_scope", part_b),
    ("c) qualify con esquema real", part_c),
    ("d) PRAGMA table_info / foreign_key_list", part_d),
]


def main() -> int:
    print(f"sqlglot {sqlglot.__version__}   dialecto {DIALECT!r}")
    print("fixtures escritos a mano; este test no lee corpus_sql.json\n")

    failed = []
    for name, fn in PARTS:
        try:
            detail = fn()
        except Exception:  # noqa: BLE001 - se reporta el traceback completo
            print(f"FALLA  {name}")
            print(traceback.format_exc())
            failed.append(name)
        else:
            print(f"ok     {name}")
            print(f"       {detail}")

    print()
    if failed:
        print(f"FALLARON {len(failed)} de {len(PARTS)}: {', '.join(failed)}")
        return 1
    print(f"las {len(PARTS)} partes pasan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
