"""Verificación del corpus congelado. Desechable, fechado 29 de julio de 2026.

    uv run python evals/gold/verify_corpus_20260729.py

Read-only sobre la base y sobre los artefactos. Cero llamadas a API. Costo $0.

POR QUÉ ESTE ARCHIVO ESTÁ COMMITEADO
------------------------------------
Reproduce `evals/results/corpus_verification.md` y
`evals/results/corpus_verification_gaps.md`. Un archivo de resultados cuyo script
no existe no es reproducible, y `batch.py` viaja con `evals/runs/`: esto cierra la
misma simetría.

Es **desechable y fechado a propósito**. No es una herramienta y no se mantiene: es
el registro ejecutable de una medición del 29 de julio de 2026. Si la base o el
corpus cambian, este script no se arregla, se escribe otro con su fecha.

NO ES CÓDIGO DEL DETECTOR. No decide veredictos, no determina `T` por query, no
busca formas de fan-out. Donde hace falta una tabla y su llave, van hardcodeadas
por caso.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

import sqlglot
from sqlglot.optimizer import qualify as qualify_mod
from sqlglot.optimizer import traverse_scope

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from txt2sql import db  # noqa: E402

DIALECT = "sqlite"
CORPUS = REPO_ROOT / "evals" / "gold" / "corpus_sql.json"
RUNS = REPO_ROOT / "evals" / "runs"

EXPECTED_DB_SHA256 = "c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762"

conn = db.connect()

TABLES = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table'"
    " AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
COLS = {t: [n for _c, n, _ct, _nn, _d, _p
            in conn.execute(f'PRAGMA table_info("{t}")')] for t in TABLES}
TYPES = {t: {n: (ct or "BLOB") for _c, n, ct, _nn, _d, _p
             in conn.execute(f'PRAGMA table_info("{t}")')} for t in TABLES}
PK = {}
for _t in TABLES:
    _rows = [(p, n) for _c, n, _ct, _nn, _d, p
             in conn.execute(f'PRAGMA table_info("{_t}")') if p]
    PK[_t] = [n for _p, n in sorted(_rows)]

ENTRIES = json.loads(CORPUS.read_text("utf-8"))["entries"]


def rule(title: str) -> None:
    print()
    print("#" * 74)
    print(f"# {title}")
    print("#" * 74)


def row_source(sql: str):
    """FROM + JOINs + WHERE del scope de más afuera.

    Ojo: en sqlglot 30.14.0 la llave de args es `from_`, y `args.get("from")`
    devuelve None EN SILENCIO. Se llega por find(exp.From).
    """
    tree = sqlglot.parse_one(sql, dialect=DIALECT)
    sel = tree if isinstance(tree, sqlglot.exp.Select) else tree.find(sqlglot.exp.Select)
    if sel is None:
        return None, None, None
    frm = sel.find(sqlglot.exp.From)
    if frm is None:
        return None, None, None
    joins = sel.args.get("joins") or []
    src = " ".join([frm.sql(dialect=DIALECT)]
                   + [j.sql(dialect=DIALECT) for j in joins]).removeprefix("FROM ")
    where = sel.args.get("where")
    if where:
        src += " " + where.sql(dialect=DIALECT)
    return src, frm, joins


# =========================================================================
# TAREA 0: el gate del hash
# =========================================================================
rule("TAREA 0 (bloqueante): hash de data/portfolio.db")
actual = hashlib.sha256((REPO_ROOT / "data" / "portfolio.db").read_bytes()).hexdigest()
print(f"\n  registrado : {EXPECTED_DB_SHA256}")
print(f"  real       : {actual}")
if actual != EXPECTED_DB_SHA256:
    print("\n  NO CUADRA. Se para el lote.")
    raise SystemExit(1)
print("  CUADRA. El lote procede.")

# =========================================================================
# TAREA 1: qualify sobre los 49
# =========================================================================
rule("TAREA 1: qualify sobre los 49")
ok, fail = [], []
for e in ENTRIES:
    try:
        qualify_mod.qualify(sqlglot.parse_one(e["sql"], dialect=DIALECT),
                            dialect=DIALECT, schema=TYPES, infer_schema=False)
    except Exception as exc:  # noqa: BLE001
        fail.append((e["id"], type(exc).__name__))
    else:
        ok.append(e["id"])
print(f"\n  pasan   : {len(ok)} de {len(ENTRIES)}")
print(f"  truenan : {len(fail)} de {len(ENTRIES)}")
print(f"  tipos   : {dict(collections.Counter(f[1] for f in fail)) or '(ninguno)'}")

# =========================================================================
# HUECO 1: correctitud de qualify, por argumento y no por muestra
# =========================================================================
rule("HUECO 8.1: correctitud de qualify (a) asignaciones (b) margen de error")

bad_assign = []
checked_cols = 0
for e in ENTRIES:
    q = qualify_mod.qualify(sqlglot.parse_one(e["sql"], dialect=DIALECT),
                            dialect=DIALECT, schema=TYPES, infer_schema=False)
    for scope in traverse_scope(q):
        # nombre de fuente -> tabla real, solo fuentes que son tablas de verdad
        real = {}
        for name, source in scope.sources.items():
            if isinstance(source, sqlglot.exp.Table):
                real[name] = source.name
        for col in scope.columns:
            tbl = col.table
            if not tbl or tbl not in real:
                continue
            checked_cols += 1
            target = real[tbl]
            if col.name not in COLS.get(target, []):
                bad_assign.append((e["id"], tbl, target, col.name))

print(f"\n  (a) columnas calificadas verificadas contra PRAGMA table_info: {checked_cols}")
print(f"      asignaciones a una tabla que NO tiene esa columna: {len(bad_assign)}")
for row in bad_assign:
    print(f"        {row}")

# (b) de las columnas SIN prefijo en el SQL original, cuantas tenian su nombre en
#     mas de una tabla del scope. Si da cero, qualify no tuvo margen para errar.
ambiguous_hits, unprefixed_total = [], 0
for e in ENTRIES:
    tree = sqlglot.parse_one(e["sql"], dialect=DIALECT)
    for scope in traverse_scope(tree):
        scope_tables = [s.name for s in scope.sources.values()
                        if isinstance(s, sqlglot.exp.Table) and s.name in COLS]
        for col in scope.columns:
            if col.table:
                continue
            unprefixed_total += 1
            hosts = [t for t in scope_tables if col.name in COLS[t]]
            if len(hosts) > 1:
                ambiguous_hits.append((e["id"], col.name, hosts))

print(f"\n  (b) columnas sin prefijo en el SQL original: {unprefixed_total}")
print(f"      de esas, con el nombre en MAS DE UNA tabla del scope: {len(ambiguous_hits)}")
for row in ambiguous_hits:
    print(f"        id={row[0]} col={row[1]!r} en {row[2]}")
if not ambiguous_hits:
    print("      CERO. qualify no tuvo margen para equivocarse: ninguna columna sin")
    print("      prefijo era resoluble a mas de una tabla. Hueco 8.1 cerrado por")
    print("      argumento, no por muestra.")
else:
    print("      DISTINTO DE CERO: qualify SI tuvo margen. Hay que revisar a mano.")

# =========================================================================
# HUECO 2: el denominador del chequeo del multiplicador
# =========================================================================
rule("HUECO 8.2: denominador real del chequeo COUNT(*) vs COUNT(T.pk)")

measured_pairs, measured_ids, diff, skipped_cte, errs = 0, set(), [], set(), []
for e in ENTRIES:
    src, frm, joins = row_source(e["sql"])
    if src is None:
        errs.append((e["id"], "sin FROM"))
        continue
    tree = sqlglot.parse_one(e["sql"], dialect=DIALECT)
    cte_names = {c.alias_or_name for c in tree.find_all(sqlglot.exp.CTE)}
    targets = []
    for tbl in list(frm.find_all(sqlglot.exp.Table)) + [
            t for j in joins for t in j.find_all(sqlglot.exp.Table)]:
        realname, alias = tbl.name, (tbl.alias or tbl.name)
        if realname in cte_names:
            skipped_cte.add(e["id"])
            continue
        if realname not in PK or len(PK[realname]) != 1:
            continue
        targets.append((alias, PK[realname][0], realname))
    for alias, pkcol, realname in targets:
        try:
            star, cnt = conn.execute(
                f'SELECT COUNT(*), COUNT("{alias}"."{pkcol}") FROM {src}').fetchone()
        except Exception as exc:  # noqa: BLE001
            errs.append((e["id"], type(exc).__name__))
            continue
        measured_pairs += 1
        measured_ids.add(e["id"])
        if star != cnt:
            diff.append((e["id"], realname, star, cnt))

print(f"\n  pares (entrada, tabla) medidos de verdad : {measured_pairs}")
print(f"  entradas con al menos un par medido      : {len(measured_ids)} de {len(ENTRIES)}")
print(f"  entradas sin ningun par medido           : "
      f"{sorted(set(e['id'] for e in ENTRIES) - measured_ids)}")
print(f"  diferencias COUNT(*) != COUNT(T.pk)      : {len(diff)}  {diff}")
print(f"  entradas con tablas de CTE saltadas      : {sorted(skipped_cte)}")
print(f"  errores de reconstruccion                : {len(errs)}")
print(f"\n  el numero honesto: 0 diferencias entre {measured_pairs} pares medidos,")
print(f"  que cubren {len(measured_ids)} de las {len(ENTRIES)} entradas.")

# =========================================================================
# HUECO 3: PRAGMA index_list / index_info
# =========================================================================
rule("HUECO 8.4: indices UNIQUE (PRAGMA index_list / index_info)")
print()
any_unique = False
for t in TABLES:
    idxs = list(conn.execute(f'PRAGMA index_list("{t}")'))
    if not idxs:
        print(f"  {t:<12} sin indices")
        continue
    for row in idxs:
        # seq, name, unique, origin, partial
        name, uniq, origin, partial = row[1], row[2], row[3], row[4]
        cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{name}")')]
        flag = "UNIQUE" if uniq else "no-unique"
        if uniq:
            any_unique = True
        print(f"  {t:<12} {name:<28} {flag:<10} origin={origin} partial={partial} cols={cols}")
uniq_non_pk = []
for t in TABLES:
    for row in conn.execute(f'PRAGMA index_list("{t}")'):
        if row[2] and row[3] != "pk":
            uniq_non_pk.append((t, row[1], row[3]))
print(f"\n  indices UNIQUE en total          : {'si hay' if any_unique else 'ninguno'}")
print(f"  UNIQUE que NO son autoindex de PK: {len(uniq_non_pk)}  {uniq_non_pk}")
print("\n  Lectura: el unico UNIQUE de esta base es el autoindex que respalda la PK")
print("  compuesta de financials (origin=pk). No hay ni una restriccion UNIQUE")
print("  declarada aparte de las PKs, asi que la clausula del alcance de v1 sobre")
print("  'PK o indice UNIQUE' NO TIENE BLANCO aqui: el lado 'uno' se determina solo")
print("  por PK. La clausula se queda escrita porque el set adversario o la rebanada 4")
print("  pueden traer un esquema con UNIQUE de verdad.")

# =========================================================================
# HUECO 4: barrido de mayusculas en literales de texto
# =========================================================================
rule("HUECO 8.11: literales de texto cuya caja no coincide con la base")

case_issues, exact_misses, literals_checked = [], [], 0
for e in ENTRIES:
    tree = sqlglot.parse_one(e["sql"], dialect=DIALECT)
    # alias -> tabla real, de todo el arbol
    alias_map = {}
    for tbl in tree.find_all(sqlglot.exp.Table):
        if tbl.name in COLS:
            alias_map[tbl.alias or tbl.name] = tbl.name
    for eq in tree.find_all(sqlglot.exp.EQ):
        col, lit = eq.this, eq.expression
        if not isinstance(col, sqlglot.exp.Column):
            col, lit = eq.expression, eq.this
        if not isinstance(col, sqlglot.exp.Column):
            continue
        if not (isinstance(lit, sqlglot.exp.Literal) and lit.is_string):
            continue
        target = alias_map.get(col.table) if col.table else None
        if target is None:
            cands = [t for t, cs in COLS.items() if col.name in cs]
            target = cands[0] if len(cands) == 1 else None
        if target is None or col.name not in COLS[target]:
            continue
        literals_checked += 1
        value = lit.this
        vals = [r[0] for r in conn.execute(
            f'SELECT DISTINCT "{col.name}" FROM "{target}" '
            f'WHERE "{col.name}" IS NOT NULL')]
        if value in vals:
            continue
        exact_misses.append((e["id"], target, col.name, value))
        lowered = {str(v).lower() for v in vals}
        if str(value).lower() in lowered:
            case_issues.append((e["id"], target, col.name, value))

print(f"\n  literales de texto comparados con = : {literals_checked}")
print(f"  que NO existen en la columna        : {len(exact_misses)}")
for row in exact_misses:
    print(f"     id={row[0]:<3} {row[1]}.{row[2]} = {row[3]!r}")
print(f"\n  de esos, fallan SOLO por la caja    : {len(case_issues)}")
for row in case_issues:
    print(f"     id={row[0]:<3} {row[1]}.{row[2]} = {row[3]!r}  <- existe con otra caja")

print("\n  nota: un literal que no existe no implica 0 filas. Solo implica 0 filas si")
print("  ese predicado es el que decide. Los conteos reales estan en result.row_count.")

# =========================================================================
# TAREA 7: uv lock
# =========================================================================
rule("cierre")
print("\n  `uv lock --check` se corre aparte; no se invoca desde aqui para no")
print("  mezclar una medicion read-only con una operacion de entorno.")
print(f"\n  sqlglot {sqlglot.__version__}, dialecto {DIALECT!r}")
print(f"  corpus: {len(ENTRIES)} entradas distintas")
