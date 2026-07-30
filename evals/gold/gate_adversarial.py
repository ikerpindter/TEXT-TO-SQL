"""GATE de la etapa 3: los 21 casos del set adversario.

    uv run python evals/gold/gate_adversarial.py

No llama al modelo. Abre `portfolio.db` en modo solo lectura. Costo: $0.

QUÉ ES UN GATE Y QUÉ NO ES UNA MEDICIÓN
----------------------------------------
El set adversario **no se parte** y va entero a dev. Son unit tests con respuesta
declarada, no una muestra, y **no entran a la estimación de desempeño de nadie**:
son deliberadamente adversarios y no representan output del modelo. Mezclarlos con
el corpus real produciría una precision y un recall que no describen ninguna de las
dos poblaciones. Por eso esto reporta **pasa o falla por caso**, y ni un porcentaje.

**21 de 21 o el detector no avanza.** Los dos que no se negocian son A2, la forma
multi-salto medida en la rebanada 2, y C1, la prueba de que la corrección de la
fórmula sirve.

LA PRECONDICIÓN VA ANTES DEL VEREDICTO
---------------------------------------
Ésta es la regla que da valor al archivo, y está escrita en el propio corpus:

    "El runner evalúa la precondición ANTES del veredicto y truena ruidoso si no se
    cumple. Un caso que no puede discriminar tiene que FALLAR, no pasar."

**La regla se ganó.** El C1 original unía por `h.status = 'cancelled'` para producir
filas con el rowid en NULL, y en esta base **las 20 comunidades tienen al menos una
casa cancelada**: cero filas NULL, las dos fórmulas daban 1.0, y el caso pasaba
verde **sin medir nada**. Un test que no puede distinguir la implementación correcta
de la rota no es un test, es decoración que da confianza.

Así que cada precondición se mide primero, con las consultas de este archivo y
contra la constante declarada en el JSON. Si no se cumple, el caso **falla**, y
falla aunque el veredicto haya salido correcto: un acierto sobre un caso que no
discrimina es accidental.

Las precondiciones se miden sobre `fanout.row_source`, la misma fuente de filas que
usa el detector, pero **con consultas propias**. Reconstruirla aparte estaría
midiendo otra query; medirla llamando a `analyze` dejaría que un detector roto
hiciera pasar sus propias precondiciones.

EL GATE CERO
------------
Antes de cualquier caso se compara el hash de `data/portfolio.db` contra el que
declara el corpus. Decisión pre-registrada: **si el hash no cuadra, se para todo.**
Un corpus cuya base cambió no es un corpus, y todas las constantes de abajo son
mediciones sobre una base concreta.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import sqlglot
from sqlglot.optimizer import traverse_scope

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from txt2sql import catalog as catalog_mod  # noqa: E402
from txt2sql import db, fanout  # noqa: E402

GOLD = REPO_ROOT / "evals" / "gold"
# Dos archivos, y son dos a propósito. `corpus_sql_adversarial.json` quedó
# congelado en cuanto produjo una medición —el gate de 21 de 21 del commit
# `b0de43d`— así que los casos nuevos van en un archivo aparte con la variable en
# el nombre, nunca como una edición del congelado. El gate los corre juntos.
CORPORA = (
    GOLD / "corpus_sql_adversarial.json",
    GOLD / "corpus_sql_adversarial_guards_20260730.json",
)

exp = sqlglot.exp


class PreconditionError(Exception):
    """La precondición no se pudo medir o no se cumple. El caso queda anulado."""


def db_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Medición de precondiciones, independiente del veredicto
# --------------------------------------------------------------------------
def build_fixture(fixture: dict) -> sqlite3.Connection:
    """La base en memoria de un caso que no puede vivir en `portfolio.db`.

    Dos de los cuatro guards —`WITHOUT ROWID` y la columna que sombrea `rowid`—
    son propiedades del **catálogo**, no del SQL. Medido: cero blanco en
    `portfolio.db`, así que ninguna cadena de SQL contra esa base los alcanza y un
    caso sin fixture sería un caso que no puede fallar.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(fixture["ddl"])
    return conn


def _locate(sql: str, cat: catalog_mod.Catalog, table: str):
    """El scope y el alias donde vive `table` como tabla base.

    Se recorre de afuera hacia adentro y se toma el primero, que es el scope cuya
    fuente de filas define lo que ve el usuario.
    """
    qualified = fanout.qualify_tree(fanout.parse(sql), cat)
    for scope in reversed(traverse_scope(qualified)):
        if not isinstance(scope.expression, exp.Select):
            continue
        for alias, source in scope.sources.items():
            if isinstance(source, exp.Table) and source.name == table:
                return scope.expression, qualified, alias
    raise PreconditionError(f"{table} no aparece como tabla base en ninguna fuente")


def _locate_alias(sql: str, cat: catalog_mod.Catalog, alias: str):
    """El scope donde vive `alias`, sea tabla base o no.

    Existe para el caso de la fuente **no** base: ahí el punto es justamente que
    el alias no es una `exp.Table`, así que `_locate` no lo encontraría.
    """
    qualified = fanout.qualify_tree(fanout.parse(sql), cat)
    for scope in reversed(traverse_scope(qualified)):
        if isinstance(scope.expression, exp.Select) and alias in scope.sources:
            return scope.expression, qualified, scope.sources[alias]
    raise PreconditionError(f"el alias {alias!r} no aparece en ninguna fuente")


def _counts_for_alias(
    conn: sqlite3.Connection, sql: str, cat, alias: str
) -> tuple[int, int, int]:
    """Las tres cuentas, para un alias que puede no ser tabla base."""
    select, root, _source = _locate_alias(sql, cat, alias)
    probe = fanout.row_source(select, root)
    quoted = alias.replace('"', '""')
    probe.set(
        "expressions",
        sqlglot.parse_one(
            f'SELECT COUNT(*), COUNT("{quoted}"."rowid"),'
            f' COUNT(DISTINCT "{quoted}"."rowid")',
            dialect=fanout.DIALECT,
        ).expressions,
    )
    row = conn.execute(probe.sql(dialect=fanout.DIALECT)).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def _counts(conn: sqlite3.Connection, sql: str, cat, table: str) -> tuple[int, int, int]:
    """`COUNT(*)` de la fuente, `COUNT(T.rowid)` y `COUNT(DISTINCT T.rowid)`."""
    select, root, alias = _locate(sql, cat, table)
    probe = fanout.row_source(select, root)
    quoted = alias.replace('"', '""')
    probe.set(
        "expressions",
        sqlglot.parse_one(
            f'SELECT COUNT(*), COUNT("{quoted}"."rowid"),'
            f' COUNT(DISTINCT "{quoted}"."rowid")',
            dialect=fanout.DIALECT,
        ).expressions,
    )
    row = conn.execute(probe.sql(dialect=fanout.DIALECT)).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def measure(conn: sqlite3.Connection, cat, case: dict, metric: str, table: str):
    """El valor medido de una métrica de precondición. Nunca usa `analyze`."""
    sql = case["sql"]

    if metric == "row_multiplier":
        _source, contributing, distinct = _counts(conn, sql, cat, table)
        if contributing == 0:
            raise PreconditionError(
                f"COUNT({table}.rowid) es 0, el multiplicador es indefinido"
            )
        return contributing / distinct

    if metric == "count_t_rowid":
        return _counts(conn, sql, cat, table)[1]

    if metric == "null_rows_t":
        # Filas de la fuente donde el rowid de T viene en NULL. Es exactamente lo
        # que separa `COUNT(*)` de `COUNT(T.rowid)`, y lo que C1 tiene que producir
        # para poder distinguir la fórmula corregida de la original.
        source, contributing, _distinct = _counts(conn, sql, cat, table)
        return source - contributing

    if metric == "rows_returned_gt0_and_count_t_rowid_eq0":
        # La clase de los 17: la query contesta, T no aporta nada, y el usuario ve
        # un número que no es una respuesta.
        returned = len(conn.execute(sql).fetchall())
        if returned <= 0:
            raise PreconditionError(
                f"la query devolvió {returned} filas y el caso exige más de 0"
            )
        return _counts(conn, sql, cat, table)[1]

    if metric == "rowid_query_raises":
        # `WITHOUT ROWID`: la query original corre limpia, así que el motor no
        # avisa. Lo único que delata la tabla es que `T.rowid` no compila.
        try:
            _counts(conn, sql, cat, table)
        except sqlite3.Error:
            return True
        return False

    if metric == "shadowed_row_multiplier":
        # El guard que MIENTE en vez de tronar: con una columna llamada `rowid`,
        # `COUNT(DISTINCT T.rowid)` cuenta valores de la columna del usuario y el
        # multiplicador sale torcido sin ningún error.
        _source, contributing, distinct = _counts(conn, sql, cat, table)
        if distinct == 0:
            raise PreconditionError("COUNT(DISTINCT T.rowid) es 0")
        return contributing / distinct

    if metric == "non_base_count_rowid":
        alias = case["precondition"].get("target_alias", table)
        source, contributing, _distinct = _counts_for_alias(conn, sql, cat, alias)
        if source <= 0:
            raise PreconditionError(
                "la fuente está vacía, así que el caso no prueba la"
                " clasificación silenciosa"
            )
        return contributing

    if metric == "correlated_scopes_in_projection":
        qualified = fanout.qualify_tree(fanout.parse(sql), cat)
        return sum(
            1
            for scope in traverse_scope(qualified)
            if getattr(scope, "is_correlated_subquery", False)
            and fanout._in_projection(scope.expression)
        )

    raise PreconditionError(f"métrica desconocida: {metric!r}")


def check_precondition(conn: sqlite3.Connection, cat, case: dict) -> str:
    """Mide y compara. Levanta PreconditionError si el caso no puede discriminar."""
    precondition = case.get("precondition")
    if not precondition:
        return "sin precondición declarada"

    metric = precondition["metric"]
    table = precondition["target_table"]
    op = precondition["op"]
    expected = precondition["value"]

    got = measure(conn, cat, case, metric, table)

    if isinstance(expected, bool):
        ok = bool(got) is expected
    elif op == "==":
        # Las constantes declaradas vienen con un decimal (39.7, 2.0), así que la
        # comparación se hace con tolerancia y no con `==` de flotantes.
        ok = abs(float(got) - float(expected)) < 1e-9
    elif op == ">":
        ok = float(got) > float(expected)
    else:
        raise PreconditionError(f"operador desconocido: {op!r}")

    if not ok:
        raise PreconditionError(
            f"{metric}({table}) = {got}, se exigía {op} {expected}"
            f" ({precondition['description']})"
        )
    return f"{metric}({table}) = {got} {op} {expected}"


# --------------------------------------------------------------------------
# Comparación del veredicto
# --------------------------------------------------------------------------
def compare(case: dict, result: fanout.FanoutResult) -> list[str]:
    """Todo lo que el caso declara, comparado. Devuelve la lista de desacuerdos."""
    problems = []

    if result.verdict != case["expected_verdict"]:
        problems.append(
            f"veredicto {result.verdict!r}, se esperaba {case['expected_verdict']!r}"
            + (f" (reason={result.reason})" if result.reason else "")
        )

    shapes = sorted({finding.shape for finding in result.findings})
    expected_shape = case["expected_shape"]
    expected_shapes = [expected_shape] if expected_shape else []
    if shapes != expected_shapes:
        problems.append(f"shape {shapes}, se esperaba {expected_shapes}")

    if case["expected_verdict"] == fanout.NOT_ANALYZED:
        if result.reason != case["reason_tag"]:
            problems.append(
                f"reason {result.reason!r}, se esperaba {case['reason_tag']!r}"
            )

    if "subcase" in case:
        if result.subcase != case["subcase"]:
            problems.append(
                f"subcase {result.subcase!r}, se esperaba {case['subcase']!r}"
            )

    return problems


def main() -> int:
    database = db.db_path()
    print(f"sqlglot {sqlglot.__version__}   dialecto {fanout.DIALECT!r}")

    cases: list[dict] = []
    for path in CORPORA:
        corpus = json.loads(path.read_text(encoding="utf-8"))
        declared = corpus["case_count"]
        if len(corpus["cases"]) != declared:
            print(f"{path.name} declara {declared} casos y trae {len(corpus['cases'])}")
            return 2

        # Gate cero, por archivo. Decisión pre-registrada: si el hash no cuadra,
        # se para todo. Un corpus cuya base cambió no es un corpus.
        actual = db_sha256(database)
        if actual != corpus["db_sha256"]:
            print("\nEL HASH DE LA BASE NO CUADRA. Se para todo.")
            print(f"  declarado en {path.name}: {corpus['db_sha256']}")
            print(f"  medido en {database}:     {actual}")
            return 2

        print(f"corpus  {path.relative_to(REPO_ROOT).as_posix()}  ({declared} casos)")
        cases.extend(corpus["cases"])

    print(f"hash de la base CUADRA: {db_sha256(database)[:16]}...")
    print(f"total: {len(cases)} casos\n")

    base_conn = db.connect()
    base_cat = catalog_mod.load(base_conn)

    voided: list[str] = []
    failed: list[str] = []

    for case in cases:
        case_id = case["id"]
        fixture = case.get("fixture")
        if fixture:
            conn = build_fixture(fixture)
            cat = catalog_mod.load(conn)
            where = f" [fixture {fixture['name']}]"
        else:
            conn, cat, where = base_conn, base_cat, ""

        try:
            detail = check_precondition(conn, cat, case)
        except (PreconditionError, sqlite3.Error, fanout.OutOfScope) as exc:
            # Un caso que no puede discriminar FALLA. No pasa, no se salta, no se
            # anota como aviso: falla, porque un verde sobre un caso muerto es peor
            # que un rojo.
            voided.append(case_id)
            print(f"ANULADO  {case_id}  precondición no se cumple{where}")
            print(f"         {type(exc).__name__}: {exc}")
            continue

        result = fanout.analyze(case["sql"], conn, cat)
        problems = compare(case, result)
        if problems:
            failed.append(case_id)
            print(f"FALLA    {case_id}  {detail}{where}")
            for problem in problems:
                print(f"         {problem}")
        else:
            shape = result.findings[0].shape if result.findings else "-"
            multiplier = (
                result.findings[0].row_multiplier if result.findings else None
            )
            extra = f" mult={multiplier}" if multiplier is not None else ""
            reason = f" reason={result.reason}" if result.reason else ""
            print(f"ok       {case_id}  {result.verdict}  shape={shape}{extra}{reason}{where}")
            print(f"         precondición: {detail}")

    print()
    passed = len(cases) - len(failed) - len(voided)
    print(f"{passed} de {len(cases)} pasan")
    if voided:
        print(f"ANULADOS por precondición ({len(voided)}): {', '.join(voided)}")
    if failed:
        print(f"FALLAN ({len(failed)}): {', '.join(failed)}")
    if failed or voided:
        print("\nEl gate NO pasa. El detector no avanza.")
        return 1
    print(f"{len(cases)} de {len(cases)}. El gate pasa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
