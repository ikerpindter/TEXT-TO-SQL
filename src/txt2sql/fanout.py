"""Detector de fan-out. Rebanada 3.

Marca y explica. **No bloquea.** La respuesta se le sigue mostrando al usuario;
lo que agrega este módulo es una afirmación acotada sobre si un agregado contó
filas repetidas por un join.

DOS PASADAS, Y LA PRIMERA NO DEPENDE DE LA SEGUNDA
---------------------------------------------------
1. **Estática**, sobre el árbol: ¿hay estructura de joins uno-a-muchos **y** un
   agregado sensible a duplicación sobre una columna afectada? Las dos cosas
   juntas son lo que este proyecto llama "forma presente".
2. **Dinámica**, sobre la base: `COUNT(T.rowid) / COUNT(DISTINCT T.rowid)` sobre
   la misma fuente de filas.

**La estática corre SIEMPRE, aunque la dinámica no encuentre nada**, y ése es el
punto entero. Si el hallazgo solo naciera cuando el multiplicador sale mayor a 1,
el veredicto `shape_no_inflation` sería **inemitible por construcción**: los casos
con forma presente y multiplicador 1.0 colapsarían a `clean` y el guardrail diría
"limpio" de una query que infla en cuanto cambien los datos. El par A2 / B1 del
set adversario es exactamente eso: misma estructura de joins salvo un predicado en
el `ON`, y el multiplicador cae de 2.0 a 1.0 **solo por la cardinalidad de los
datos**. La forma es una propiedad del árbol; el multiplicador es una medición.

LA PRECEDENCIA ES POR HALLAZGO, NO POR QUERY
---------------------------------------------
Los cinco veredictos se evalúan en orden y el primero que aplica gana:
`not_analyzed`, `no_contributing_rows`, `clean`, `shape_no_inflation`, `inflated`.
Pero `no_contributing_rows` solo gana cuando **ningún** hallazgo es medible: si uno
se puede medir y otro no, el veredicto sale del medible. Entre los medibles manda
el peor caso, así que un solo hallazgo `inflated` hace `inflated` a la query.

`clean` significa **"sin duplicación de filas medida"**, no "la query es
correcta". Este guardrail mide una sola cosa. Las trampas de `unit_scale` y de año
fiscal producen números mal con veredicto `clean`, y eso es el comportamiento
correcto, no un hoyo. Importa sobre todo para la rebanada 6, donde esto lo consume
un agente: leer `clean` como "confía en el número" es confiar en algo que este
detector nunca miró.

TRES DECISIONES QUE LA ESPECIFICACIÓN NO TRAÍA, TOMADAS EL 2026-07-30
----------------------------------------------------------------------
- **`COUNT(*)` no se atribuye, y si es lo único que había, la query va a
  `not_analyzed`.** No tiene columna, así que no tiene `T` y el multiplicador no es
  calculable. Marcarlo produciría un falso positivo medido sobre
  `COUNT(*) FROM homes JOIN communities`, donde la duplicación de `communities` no
  toca al conteo de casas; callarlo afirmaría `clean` sin haber verificado nada.

  > **Corrección del 2026-07-30, y salió de medir, no de razonar.** La primera
  > versión de esta regla devolvía `clean` y nombraba el agregado en un campo
  > aparte. Corriendo sobre el corpus, eso marcaba `clean` **tres entradas de Q5 en
  > la config B** —ids 45, 46 y 48— que el ROADMAP documenta como portadoras del
  > artefacto de fan-out. Un `clean` sobre la falla que esta rebanada existe para
  > cazar no es un hueco aceptable, es un miss. Ahora, cuando no hay ningún
  > hallazgo y quedó un agregado sin verificar, el veredicto es `not_analyzed` con
  > razón `unattributable_aggregate`.
  >
  > **No basta con volverlo `not_analyzed` siempre**, y eso también se midió: la id
  > 47 trae un `COUNT(*)` **y** un `SUM(financials.backlog_value)` que sí se puede
  > atribuir y que sale inflado 51.5x. Anular la query entera por el `COUNT(*)`
  > tiraría una detección verdadera. Si se pudo medir algo, se reporta, y el
  > agregado no atribuible se nombra al lado.
  >
  > Esto resuelve una tensión real dentro del propio ROADMAP: la definición de
  > "forma presente" —agregado sensible **sobre una columna afectada**— daría
  > `clean`, y el principio de que `not_analyzed` nunca se degrada a `clean` da
  > `not_analyzed`. Gana el principio, porque la definición es una precisión sobre
  > qué cuenta como forma y el principio es sobre qué se puede afirmar.
- **Atribución por posición de VALOR, no por columna presente.** En
  `SUM(CASE WHEN c.name IN (...) THEN f.homes_delivered ELSE 0 END)` —ids 4 y 26 del
  corpus— `c.name` está en posición de predicado y `f.homes_delivered` en posición
  de valor. Atribuir por todas las columnas daría dos hallazgos y uno sería falso.
- **`unexplained` se mide primero.** Los dos shapes reales se emiten desde la
  estática y se miden después; `unexplained` es, por definición, "no encontré la
  forma pero medí duplicación", así que **solo existe si el multiplicador sale
  mayor a 1**. Sin esa asimetría, C2 —el CTE que pre-agrega bien— saldría
  `shape_no_inflation` en vez de `clean`.

REGLA DE IMPORTS
----------------
Solo de `sqlglot` y de `sqlglot.optimizer`. Los nodos se alcanzan por `exp.X`, que
es el único alias permitido. Y no se accede a la estructura de un nodo por el
nombre de su llave en `args` sin verificarlo: la llave del `FROM` es `from_`, con
guion bajo, así que `select.args.get("from")` devuelve `None` **en silencio**.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field

import sqlglot
from sqlglot.optimizer import find_all_in_scope, traverse_scope
from sqlglot.optimizer import qualify as qualify_mod

from txt2sql import catalog as catalog_mod

exp = sqlglot.exp

DIALECT = "sqlite"


def _arg_key(node_type: type, *candidates: str) -> str:
    """La llave real de un argumento, verificada contra `arg_types` al importar.

    **La llave del `FROM` es `from_` y la del `WITH` es `with_`, las dos con guion
    bajo**, así que `args.get("from")` y `args.get("with")` devuelven `None` **en
    silencio** y, peor, `set("with", ...)` es un no-op que no rinde nada y no se
    queja. Ese no-op costó una `OperationalError` en la id 16 del corpus: el cuerpo
    de un CTE que se une a un CTE hermano salía sin cláusula `WITH` y la sonda
    tronaba con `no such table`.

    La lección del repo era "no accedas por el nombre de la llave sin verificarlo".
    Ésta es la versión ejecutable: si un salto de versión mueve el nombre, esto
    **truena al importar** en vez de devolver `None` para siempre.
    """
    for candidate in candidates:
        if candidate in node_type.arg_types:
            return candidate
    raise RuntimeError(
        f"ninguna de las llaves {candidates} existe en {node_type.__name__}.arg_types."
        f" Las que hay: {sorted(node_type.arg_types)}"
    )


WITH_KEY = _arg_key(exp.Select, "with_", "with")

# Las demás llaves que este módulo toca. Se verifican al importar por la misma
# razón: una que deje de existir haría que el detector, por ejemplo, no quitara el
# GROUP BY de la sonda y midiera el multiplicador del primer grupo creyendo que es
# el global.
for _key in (
    "group",
    "having",
    "order",
    "limit",
    "offset",
    "distinct",
    "qualify",
    "sort",
    "cluster",
    "distribute",
    "windows",
    "joins",
    "where",
    "expressions",
):
    _arg_key(exp.Select, _key)
del _key

# --- Los cinco veredictos, en orden de precedencia -------------------------
NOT_ANALYZED = "not_analyzed"
NO_CONTRIBUTING_ROWS = "no_contributing_rows"
CLEAN = "clean"
SHAPE_NO_INFLATION = "shape_no_inflation"
INFLATED = "inflated"

VERDICTS = (NOT_ANALYZED, NO_CONTRIBUTING_ROWS, CLEAN, SHAPE_NO_INFLATION, INFLATED)

# --- Las formas ------------------------------------------------------------
FAN_TRAP = "fan_trap"
CHASM_TRAP = "chasm_trap"
UNEXPLAINED = "unexplained"

# --- Subcasos de no_contributing_rows, nombrados por la FUENTE -------------
# Nombrarlos por la salida era el error: un agregado desnudo sobre cero filas
# emite exactamente una fila, así que "query con filas" describía a los dos.
EMPTY_SOURCE = "empty_source"
T_ABSENT = "t_absent"

# --- Razones de not_analyzed ----------------------------------------------
# Las cinco primeras son las que el documento de criterios lista como
# `out_of_scope`. Las demás son huecos del documento, no errores de etiquetado, y
# la tabla de adjudicación del ROADMAP las enruta distinto a propósito.
REASON_SELF_JOIN = "self_join"
REASON_WINDOW = "window_function"
REASON_SET_OPERATION = "set_operation"
REASON_NON_FK_JOIN = "non_fk_join"
REASON_AMBIGUOUS_COLUMN = "ambiguous_column"

REASON_PARSE_ERROR = "parse_error"
REASON_NOT_A_SELECT = "not_a_select"
REASON_QUALIFY_ERROR = "qualify_error"
REASON_CORRELATED_SUBQUERY = "correlated_subquery"
REASON_NON_BASE_TABLE = "non_base_table"
REASON_WITHOUT_ROWID = "without_rowid"
REASON_ROWID_SHADOWED = "rowid_shadowed"
REASON_PROBE_FAILED = "probe_failed"
REASON_UNATTRIBUTABLE = "unattributable_aggregate"

CRITERIA_REASONS = frozenset(
    {
        REASON_SELF_JOIN,
        REASON_WINDOW,
        REASON_SET_OPERATION,
        REASON_NON_FK_JOIN,
        REASON_AMBIGUOUS_COLUMN,
    }
)

# Agregados sensibles a duplicación. `MAX` y `MIN` no están y no es una excepción
# afinada: duplicar filas no mueve el valor de un máximo. `GROUP_CONCAT` salió del
# alcance de v1 por falta de blanco, cero apariciones en 49 muestras.
_AGGREGATE_CLASSES: tuple[tuple[type, str], ...] = (
    (exp.Sum, "SUM"),
    (exp.Avg, "AVG"),
    (exp.Count, "COUNT"),
)

# `TOTAL` es el alias de `SUM` en SQLite pero sqlglot 30.14.0 NO lo mapea a
# `exp.Sum`: lo parsea como `exp.Anonymous(this='TOTAL')`. Verificado el
# 2026-07-30. Un detector que solo busque `exp.Sum` lo pierde entero.
_TOTAL = "TOTAL"


class OutOfScope(Exception):
    """La query cae fuera de v1. Se convierte en `not_analyzed` con su razón."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class JoinEdge:
    """Un join uno-a-muchos con su dirección ya resuelta contra el catálogo."""

    many_alias: str
    one_alias: str
    many_table: str
    one_table: str
    text: str


@dataclass
class Candidate:
    """Hallazgo estático: forma leída del árbol, todavía sin medir."""

    shape: str
    aggregate: str
    function: str
    table: str
    alias: str
    one_side: str | None
    many_side: str | None
    join_path: tuple[str, ...]
    has_group_by: bool
    columns: tuple[str, ...]
    counts_identity: bool
    select: exp.Select = field(repr=False)
    argument: exp.Expression | None = field(default=None, repr=False)
    node: exp.Expression | None = field(default=None, repr=False)


@dataclass
class StaticScan:
    """Lo que la pasada estática sabe antes de tocar la base."""

    candidates: list[Candidate] = field(default_factory=list)
    unattributed_aggregates: list[str] = field(default_factory=list)
    root: exp.Expression | None = None


# --------------------------------------------------------------------------
# Utilidades de árbol
# --------------------------------------------------------------------------
def _conjuncts(node: exp.Expression | None):
    """Aplana un AND en sus términos. Un OR NO se aplana.

    Una condición de join bajo un `OR` no establece una relación de grano: tratar
    sus igualdades como aristas afirmaría una dirección que el `OR` no garantiza.
    Se devuelve el `OR` entero y ninguna de sus igualdades cuenta como arista.
    """
    if node is None:
        return
    if isinstance(node, exp.And):
        yield from _conjuncts(node.this)
        yield from _conjuncts(node.expression)
    elif isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    else:
        yield node


def _base_sources(scope) -> dict[str, exp.Table]:
    """Fuentes que son tabla base, deduplicadas.

    `scope.sources` trae el alias **y** el nombre del CTE como entradas separadas:
    medido sobre C2, `['c', 'p', 'per_comm']` son 3 entradas para 2 fuentes.
    Recorrerlo sin deduplicar sondearía el CTE dos veces.

    Y el filtro `isinstance(..., exp.Table)` es el guard que el ROADMAP exige en el
    AST: sobre una subconsulta derivada, `T.rowid` **resuelve a NULL sin error**, y
    `COUNT` da 0, que es exactamente la condición de `no_contributing_rows`. Una
    derivada quedaría clasificada en silencio como "T no aporta filas" teniendo
    filas.
    """
    out: dict[str, exp.Table] = {}
    seen: set[int] = set()
    for name, source in scope.sources.items():
        if not isinstance(source, exp.Table) or id(source) in seen:
            continue
        seen.add(id(source))
        out[name] = source
    return out


def _source_arity(select: exp.Select) -> int:
    """Cuántas fuentes tiene la fuente de filas: el FROM más los JOINs.

    El acceso al FROM va por `find(exp.From)` y **no** por `args.get("from")`: la
    llave es `from_`, con guion bajo, así que la versión sin verificar devuelve
    `None` en silencio y un detector escrito así trataría todas las queries como si
    no tuvieran FROM sin quejarse una sola vez.
    """
    return (1 if select.find(exp.From) is not None else 0) + len(
        select.args.get("joins") or []
    )


def _enclosing_with(node: exp.Expression) -> exp.With | None:
    """El `WITH` que define las fuentes visibles desde este nodo, si lo hay."""
    current = node.parent
    while current is not None:
        if isinstance(current, exp.With):
            return current
        if isinstance(current, exp.Select):
            with_clause = current.args.get(WITH_KEY)
            if with_clause is not None:
                return with_clause
        current = current.parent
    return None


def _in_projection(node: exp.Expression) -> bool:
    """¿El nodo cuelga de la lista del SELECT de algún ancestro?"""
    current = node
    while current is not None and current.parent is not None:
        if current.arg_key == "expressions" and isinstance(current.parent, exp.Select):
            return True
        current = current.parent
    return False


def _pretty(node: exp.Expression, alias_table: dict[str, str]) -> str:
    """El agregado como se lee en un mensaje: `SUM(communities.budget_usd)`.

    `qualify` corre con `identify=True`, así que lo que trae el árbol es
    `SUM("c"."budget_usd")`. Ni el alias ni las comillas le sirven a nadie que lea
    la advertencia, así que se reescribe con el nombre real de la tabla.
    """
    copy = node.copy()
    for column in copy.find_all(exp.Column):
        table = alias_table.get(column.table, column.table)
        column.set("this", exp.to_identifier(column.name, quoted=False))
        column.set("table", exp.to_identifier(table, quoted=False) if table else None)
    return copy.sql(dialect=DIALECT)


def _value_columns(node: exp.Expression | None) -> list[exp.Column]:
    """Columnas en posición de VALOR, saltando las de posición de predicado.

    `SUM(CASE WHEN c.name IN (...) THEN f.homes_delivered ELSE 0 END)`: lo que se
    suma es `f.homes_delivered`; `c.name` decide *si* se suma. Atribuir el agregado
    a las dos tablas produce un hallazgo de más, y ese hallazgo sería falso: que
    `companies` se duplique no infla una suma cuyos sumandos son filas de
    `financials`.
    """
    if node is None:
        return []
    if isinstance(node, exp.Column):
        return [node]
    if isinstance(node, exp.Case):
        # `this` es el operando del CASE simple y va en posición de predicado.
        out: list[exp.Column] = []
        for branch in node.args.get("ifs") or []:
            out.extend(_value_columns(branch.args.get("true")))
            out.extend(_value_columns(branch.args.get("false")))
        out.extend(_value_columns(node.args.get("default")))
        return out
    if isinstance(node, exp.If):
        return _value_columns(node.args.get("true")) + _value_columns(
            node.args.get("false")
        )

    out = []
    for value in node.args.values():
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, exp.Expression):
                out.extend(_value_columns(item))
    return out


def _aggregates(scope):
    """Los agregados sensibles del scope, sin cruzar a subscopes.

    Devuelve `(nodo, nombre_de_función, argumento)`. El argumento es `None` cuando
    la función no tiene exactamente un argumento.
    """
    for node in find_all_in_scope(
        scope.expression, tuple(cls for cls, _name in _AGGREGATE_CLASSES)
    ):
        for cls, name in _AGGREGATE_CLASSES:
            if isinstance(node, cls):
                yield node, name, node.this
                break

    for node in find_all_in_scope(scope.expression, exp.Anonymous):
        if str(node.this).upper() != _TOTAL:
            continue
        args = node.expressions or []
        yield node, _TOTAL, (args[0] if len(args) == 1 else None)


# --------------------------------------------------------------------------
# Aristas de join, con la dirección resuelta contra el catálogo
# --------------------------------------------------------------------------
def _edges_for_scope(scope, cat: catalog_mod.Catalog) -> list[JoinEdge]:
    """Aristas uno-a-muchos del scope. Levanta OutOfScope si un join no es de FK.

    Un join entre dos tablas base cuya igualdad no corresponde a una FK declarada
    va a `not_analyzed`: sin FK no se puede determinar cuál lado es el "uno", y
    adivinarlo desde los datos está prohibido por el alcance de v1.

    Un join contra un CTE o una derivada **no** es un `non_fk_join`. No es que no
    haya FK: es que no hay tabla contra la cual buscarla, y afirmar que el join es
    inválido sería tan falso como afirmar que es válido. Sin arista, el caso baja a
    medición y, si duplica, sale como `unexplained`.
    """
    select = scope.expression
    if not isinstance(select, exp.Select):
        return []

    base = _base_sources(scope)
    joins = select.args.get("joins") or []
    where = select.args.get("where")
    where_conditions = list(_conjuncts(where.this if where else None))

    edges: list[JoinEdge] = []

    for join in joins:
        on = join.args.get("on")
        # Join por coma: sqlglot lo trae como Join sin `on`, y la igualdad que lo
        # ata vive en el WHERE.
        conditions = list(_conjuncts(on)) if on is not None else where_conditions

        target = join.this
        target_alias = target.alias_or_name if isinstance(target, exp.Table) else None

        touches_base_pair = False
        found_fk_for_target = False

        for condition in conditions:
            if not isinstance(condition, exp.EQ):
                continue
            left, right = condition.this, condition.expression
            if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                continue
            if left.table not in base or right.table not in base:
                continue

            if target_alias in (left.table, right.table):
                touches_base_pair = True

            edge = _fk_edge(left, right, base, cat)
            if edge is None:
                continue
            edges.append(edge)
            if target_alias in (left.table, right.table):
                found_fk_for_target = True

        if target_alias is not None and touches_base_pair and not found_fk_for_target:
            raise OutOfScope(
                REASON_NON_FK_JOIN,
                f"el join de {base[target_alias].name} no sigue ninguna FK declarada",
            )

    # Dedup preservando el orden: el mismo par puede aparecer en varias ramas.
    unique: list[JoinEdge] = []
    for edge in edges:
        if edge not in unique:
            unique.append(edge)
    return unique


def _fk_edge(
    left: exp.Column,
    right: exp.Column,
    base: dict[str, exp.Table],
    cat: catalog_mod.Catalog,
) -> JoinEdge | None:
    """La arista que corresponde a `left = right`, en la dirección que diga la FK."""
    left_table = base[left.table].name
    right_table = base[right.table].name

    for child_col, child_alias, child_table, parent_col, parent_alias, parent_table in (
        (left.name, left.table, left_table, right.name, right.table, right_table),
        (right.name, right.table, right_table, left.name, left.table, left_table),
    ):
        fk = cat.one_side_fk(child_table, child_col, parent_table, parent_col)
        if fk is not None:
            return JoinEdge(
                many_alias=child_alias,
                one_alias=parent_alias,
                many_table=child_table,
                one_table=parent_table,
                text=fk.text,
            )
    return None


# --------------------------------------------------------------------------
# Las dos formas
# --------------------------------------------------------------------------
def _reachable(edges: list[JoinEdge], start: str, blocked: str) -> set[str]:
    """Alias alcanzables desde `start` sin pasar por `blocked`, sin dirección."""
    neighbours: dict[str, set[str]] = {}
    for edge in edges:
        neighbours.setdefault(edge.many_alias, set()).add(edge.one_alias)
        neighbours.setdefault(edge.one_alias, set()).add(edge.many_alias)

    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in sorted(neighbours.get(node, ())):
            if neighbour == blocked or neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append(neighbour)
    return seen


def _path_texts(edges: list[JoinEdge], src: str, dst: str) -> list[str]:
    """Los joins del camino más corto entre dos alias, en orden."""
    if src == dst:
        return []
    adjacency: dict[str, list[tuple[str, JoinEdge]]] = {}
    for edge in edges:
        adjacency.setdefault(edge.many_alias, []).append((edge.one_alias, edge))
        adjacency.setdefault(edge.one_alias, []).append((edge.many_alias, edge))

    previous: dict[str, tuple[str, JoinEdge]] = {}
    seen = {src}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        for neighbour, edge in sorted(adjacency.get(node, ()), key=lambda pair: pair[0]):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            previous[neighbour] = (node, edge)
            if neighbour == dst:
                queue.clear()
                break
            queue.append(neighbour)

    if dst not in previous:
        return []
    texts: list[str] = []
    cursor = dst
    while cursor != src:
        parent, edge = previous[cursor]
        texts.append(edge.text)
        cursor = parent
    return list(reversed(texts))


def _shape_for(alias: str, edges: list[JoinEdge], alias_table: dict[str, str]):
    """La forma que explica por qué `alias` se puede duplicar en este scope.

    Precedencia: `fan_trap`, luego `chasm_trap`, luego `unexplained`. El fan trap
    va primero porque es la explicación directa —la tabla agregada ES el lado
    "uno" de un join presente— y nombrarla es lo que hace accionable el mensaje.
    """
    children: dict[str, list[JoinEdge]] = {}
    for edge in edges:
        children.setdefault(edge.one_alias, []).append(edge)

    # fan_trap: se agrega una columna del lado "uno" después de unir al "muchos".
    if alias in children:
        edge = sorted(children[alias], key=lambda e: (e.many_table, e.text))[0]
        return FAN_TRAP, alias_table[alias], edge.many_table, (edge.text,)

    # chasm_trap: dos ramas uno-a-muchos desde un ancestro común, unidas entre sí.
    # Las ramas pueden tener CUALQUIER profundidad: en este esquema `homes` no
    # tiene FK a `companies`, llega vía `communities`, así que un detector que solo
    # compare hijos directos no caza Q5, que es uno de los dos casos medidos.
    for ancestor in sorted(children):
        kids = sorted({edge.many_alias for edge in children[ancestor]})
        if len(kids) < 2:
            continue
        branches = {kid: _reachable(edges, kid, ancestor) for kid in kids}
        mine = [kid for kid in kids if alias in branches[kid]]
        others = [kid for kid in kids if kid not in mine]
        if not mine or not others:
            continue
        sibling = others[0]
        path = _path_texts(edges, ancestor, alias) + _path_texts(edges, ancestor, sibling)
        seen: list[str] = []
        for text in path:
            if text not in seen:
                seen.append(text)
        return CHASM_TRAP, alias_table[ancestor], alias_table[sibling], tuple(seen)

    return UNEXPLAINED, None, None, ()


# --------------------------------------------------------------------------
# Guards de alcance y pasada estática
# --------------------------------------------------------------------------
def _counts_identity(
    function: str,
    aliases: list[str],
    own_columns: list[exp.Column],
    table: str,
    cat: catalog_mod.Catalog,
) -> bool:
    """¿El agregado es `COUNT` de la identidad de fila de `T`?

    Es el único caso donde `row_multiplier` **es** el factor de inflación del
    valor, y no por una coincidencia de los datos sino por aritmética: sobre la
    fuente duplicada `COUNT(T.pk)` cuenta exactamente las filas que aportan, y
    deduplicado cuenta las filas distintas, así que el cociente **es** el
    multiplicador, por definición y con cualquier dato.

    Exige que el agregado toque una sola columna de una sola tabla. `COUNT(T.x)`
    de una columna cualquiera **no** califica aunque hoy diera lo mismo: si `x`
    admite nulos, numerador y denominador dejan de encogerse a la par.
    """
    if function != "COUNT" or len(aliases) != 1 or len(own_columns) != 1:
        return False
    name = own_columns[0].name.lower()
    if name in catalog_mod.ROWID_ALIASES:
        return True
    primary_key = cat.primary_keys.get(table, [])
    return len(primary_key) == 1 and name == primary_key[0].lower()


def _guard_statement(tree: exp.Expression) -> None:
    """Lo que se decide del árbol completo, antes de calificar nada."""
    # `exp.SetOperation` es la clase base de Union, Intersect y Except en 30.14.0,
    # verificado el 2026-07-30. `find(exp.Union)` habría dejado dos de las tres
    # operaciones afuera, que era el `NO VERIFICADO` anotado en el caso E4.
    if isinstance(tree, exp.SetOperation) or tree.find(exp.SetOperation) is not None:
        raise OutOfScope(REASON_SET_OPERATION, "UNION / INTERSECT / EXCEPT")
    if not isinstance(tree, exp.Select):
        raise OutOfScope(REASON_NOT_A_SELECT, type(tree).__name__)
    if tree.find(exp.Window) is not None:
        raise OutOfScope(REASON_WINDOW, "función de ventana")


def _guard_scope(scope, cat: catalog_mod.Catalog) -> None:
    """Lo que se decide por scope, ya con las fuentes resueltas."""
    if getattr(scope, "is_correlated_subquery", False) and _in_projection(
        scope.expression
    ):
        raise OutOfScope(
            REASON_CORRELATED_SUBQUERY, "subconsulta correlacionada en el SELECT"
        )

    by_table: dict[str, list[str]] = {}
    for alias, source in _base_sources(scope).items():
        by_table.setdefault(source.name, []).append(alias)
    for table, aliases in sorted(by_table.items()):
        if len(aliases) > 1:
            raise OutOfScope(
                REASON_SELF_JOIN, f"{table} aparece {len(aliases)} veces en el mismo scope"
            )


def parse(sql: str) -> exp.Expression:
    try:
        tree = sqlglot.parse_one(sql, dialect=DIALECT)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de parseo es la misma decisión
        raise OutOfScope(REASON_PARSE_ERROR, f"{type(exc).__name__}: {exc}") from exc
    if tree is None:
        raise OutOfScope(REASON_PARSE_ERROR, "parse_one devolvió None")
    return tree


def qualify_tree(tree: exp.Expression, cat: catalog_mod.Catalog) -> exp.Expression:
    """Resuelve cada columna a su tabla. Falla ruidoso, y eso está bien.

    `validate_qualify_columns=True` es el default y se queda: lo que `qualify`
    rechace es `not_analyzed`, y la cobertura se publica como dato de alcance. Un
    detector que analiza más porque dejó de validar no analiza mejor.
    """
    try:
        return qualify_mod.qualify(
            tree.copy(),
            dialect=DIALECT,
            schema=cat.qualify_schema(),
            # Con esquema explícito va `infer_schema=False`, o inventa columnas que
            # no se le dieron.
            infer_schema=False,
        )
    except Exception as exc:  # noqa: BLE001 - sqlglot lanza OptimizeError y parientes
        name = type(exc).__name__
        reason = (
            REASON_AMBIGUOUS_COLUMN if "Optimize" in name else REASON_QUALIFY_ERROR
        )
        raise OutOfScope(reason, f"{name}: {exc}") from exc


def static_scan(sql: str, cat: catalog_mod.Catalog) -> StaticScan:
    """La pasada estática completa. No toca la base ni ejecuta nada.

    Levanta `OutOfScope` para todo lo que cae fuera de v1.
    """
    tree = parse(sql)
    _guard_statement(tree)
    qualified = qualify_tree(tree, cat)

    scan = StaticScan(root=qualified)

    for scope in traverse_scope(qualified):
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue

        _guard_scope(scope, cat)

        base = _base_sources(scope)
        alias_table = {alias: source.name for alias, source in base.items()}
        edges = _edges_for_scope(scope, cat)
        # Un scope con una sola fuente no puede duplicar filas por join, así que no
        # hay forma que buscar y tampoco hay nada que verificar contra la base.
        #
        # **No se cuenta con `scope.sources`**, y esto costó un falso
        # `not_analyzed`: `sources` incluye los CTEs DECLARADOS aunque el FROM no
        # los use. La id 38 declara dos CTEs y consume uno, así que `sources` decía
        # 2 fuentes donde el FROM tiene 1, el scope parecía tener join, y el
        # agregado sobre el CTE disparaba el guard de tabla no-base. La aridad real
        # de la fuente de filas es FROM más JOINs y nada más.
        single_source = _source_arity(select) < 2
        has_group_by = bool(select.args.get("group"))

        for node, function, argument in _aggregates(scope):
            pretty = _pretty(node, alias_table)

            # Inmunes por aritmética, no por criterio: duplicar filas no mueve el
            # valor de un DISTINCT.
            if isinstance(argument, exp.Distinct):
                continue

            if isinstance(argument, exp.Star):
                if not single_source:
                    scan.unattributed_aggregates.append(pretty)
                continue

            if argument is None:
                scan.unattributed_aggregates.append(pretty)
                continue

            columns = _value_columns(argument)
            aliases = sorted({column.table for column in columns if column.table})
            if not aliases:
                # `SUM(1)` y parientes: no hay columna a la que atribuir nada.
                if not single_source:
                    scan.unattributed_aggregates.append(pretty)
                continue

            if single_source:
                continue

            for alias in aliases:
                source = scope.sources.get(alias)
                if not isinstance(source, exp.Table):
                    # El guard del AST. Sobre una derivada `rowid` resuelve a NULL
                    # sin error, así que dejarlo pasar sería fallar en silencio.
                    raise OutOfScope(
                        REASON_NON_BASE_TABLE,
                        f"el agregado {pretty} cae sobre {alias}, que no es tabla base",
                    )
                guard = cat.rowid_is_safe(source.name)
                if guard is not None:
                    raise OutOfScope(guard, source.name)

                own_columns = [column for column in columns if column.table == alias]
                shape, one_side, many_side, path = _shape_for(alias, edges, alias_table)
                scan.candidates.append(
                    Candidate(
                        shape=shape,
                        aggregate=pretty,
                        function=function,
                        table=source.name,
                        alias=alias,
                        one_side=one_side,
                        many_side=many_side,
                        join_path=path,
                        has_group_by=has_group_by,
                        # Solo las columnas de ESTA tabla: es lo que el render
                        # necesita para nombrar qué se sumó de más.
                        columns=tuple(
                            sorted({f"{source.name}.{c.name}" for c in own_columns})
                        ),
                        counts_identity=_counts_identity(
                            function, aliases, own_columns, source.name, cat
                        ),
                        select=select,
                        argument=argument,
                        node=node,
                    )
                )

    return scan


# --------------------------------------------------------------------------
# La sonda dinámica
# --------------------------------------------------------------------------
# Todo lo que no forma parte de la fuente de filas. El multiplicador se mide
# sobre FROM, JOINs y WHERE: ni ORDER BY ni LIMIT cambian cuántas veces aparece
# una fila de T, y GROUP BY colapsa justo lo que queremos contar.
_STRIP_KEYS = (
    "group",
    "having",
    "order",
    "limit",
    "offset",
    "distinct",
    "qualify",
    "sort",
    "cluster",
    "distribute",
    "windows",
)


def row_source(select: exp.Select, root: exp.Expression | None) -> exp.Select:
    """La fuente de filas de un scope, lista para colgarle otra lista de SELECT.

    Es público a propósito: el gate del set adversario mide sus precondiciones
    sobre esta misma fuente de filas, pero con sus propias consultas y contra sus
    propias constantes declaradas. Si el gate reconstruyera la fuente por su
    cuenta estaría probando otra query, y si midiera llamando a `analyze` un
    detector roto podría hacer pasar sus propias precondiciones.

    Si el scope vive dentro de un CTE, copiarlo lo desprende del `WITH` que define
    sus fuentes, así que hay que volver a colgárselo. Un CTE de más en la cláusula
    no cuesta nada: SQLite ignora los que no se usan.

    **El `WITH` se busca subiendo por los padres del nodo original**, no en el
    argumento `root`. Costó una `OperationalError` en la id 38 del corpus: el
    cuerpo de un CTE que se une a otro CTE hermano quedaba sin la cláusula y la
    sonda tronaba con `no such table`. Subir por el árbol funciona sin importar qué
    sea la raíz; `root` queda como respaldo.
    """
    probe = select.copy()
    for key in _STRIP_KEYS:
        if probe.args.get(key) is not None:
            probe.set(key, None)
    if probe.args.get(WITH_KEY) is None:
        with_clause = _enclosing_with(select)
        if with_clause is None and isinstance(root, exp.Select):
            with_clause = root.args.get(WITH_KEY)
        if with_clause is not None:
            probe.set(WITH_KEY, with_clause.copy())
    return probe


def _quoted(alias: str) -> str:
    return alias.replace('"', '""')


def _probe_counts(
    conn: sqlite3.Connection,
    select: exp.Select,
    root: exp.Expression | None,
    alias: str,
) -> tuple[int, int, int]:
    """`COUNT(*)` de la fuente, `COUNT(T.rowid)` y `COUNT(DISTINCT T.rowid)`.

    El numerador es `COUNT(T.rowid)` y **no** `COUNT(*)`. Con `LEFT JOIN`, las
    filas sin match traen el rowid en NULL: `COUNT(*)` las cuenta y el DISTINCT
    no, así que el multiplicador saldría inflado sin que exista inflación. Un
    falso `inflated` es justo el error que este guardrail no se puede permitir,
    porque enseña a desconfiar de las advertencias. Forzando el hueco, además, la
    fórmula original divide entre cero.

    El `COUNT(*)` va aparte porque es lo único que separa los dos subcasos de
    `no_contributing_rows`: fuente vacía contra `T` que no aporta.
    """
    probe = row_source(select, root)
    alias_sql = _quoted(alias)
    probe.set(
        "expressions",
        sqlglot.parse_one(
            f'SELECT COUNT(*), COUNT("{alias_sql}"."rowid"),'
            f' COUNT(DISTINCT "{alias_sql}"."rowid")',
            dialect=DIALECT,
        ).expressions,
    )
    row = conn.execute(probe.sql(dialect=DIALECT)).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def _reported_value(
    conn: sqlite3.Connection,
    select: exp.Select,
    root: exp.Expression | None,
    node: exp.Expression,
):
    """El valor del agregado tal como salió: sobre la fuente con duplicación."""
    probe = row_source(select, root)
    probe.set("expressions", [node.copy()])
    return conn.execute(probe.sql(dialect=DIALECT)).fetchone()[0]


def _deduplicated_value(
    conn: sqlite3.Connection,
    select: exp.Select,
    root: exp.Expression | None,
    alias: str,
    argument: exp.Expression,
    function: str,
):
    """El mismo agregado contando cada fila de `T` una sola vez.

    **No se aproxima dividiendo por el multiplicador**, y hay número detrás de la
    prohibición: sobre Q4 esa división da 359,701,250 contra 348,500,000 reales,
    3.21% de error presentado como cifra exacta. Se recalcula contra la base.

    `DISTINCT rowid, valor` deja exactamente una fila por fila de `T`, porque el
    rowid ya es único. Las filas sin match de un `LEFT JOIN` colapsan en una sola
    con NULL, y `SUM` y `COUNT` la ignoran igual que ignoran cualquier NULL.
    """
    inner = row_source(select, root)
    with_clause = inner.args.get(WITH_KEY)
    if with_clause is not None:
        # El `WITH` se sube al query de afuera en vez de quedarse dentro del
        # paréntesis, para no depender de que el motor acepte una cláusula `WITH`
        # dentro de una subconsulta.
        inner.set(WITH_KEY, None)

    alias_sql = _quoted(alias)
    rowid_column = sqlglot.parse_one(
        f'SELECT "{alias_sql}"."rowid" AS "__rid"', dialect=DIALECT
    ).expressions[0]
    value_column = exp.alias_(argument.copy(), "__value", quoted=True)
    inner.set("expressions", [rowid_column, value_column])
    inner.set("distinct", exp.Distinct())

    prefix = f"{with_clause.sql(dialect=DIALECT)} " if with_clause is not None else ""
    # El `COUNT(*)` de afuera **no es decoración**: si el valor no está determinado
    # por la fila de `T` —porque la expresión también mira otra tabla que se
    # duplica— el `DISTINCT` deja más de una fila por rowid y el agregado saldría
    # mal. Quien llama compara este conteo contra `COUNT(DISTINCT T.rowid)` y, si
    # no cuadran, deja el valor en `null` en vez de reportar una cifra torcida.
    sql = (
        f'{prefix}SELECT COUNT(*), {function}("__value")'
        f' FROM ({inner.sql(dialect=DIALECT)})'
        f' WHERE "__rid" IS NOT NULL'
    )
    row = conn.execute(sql).fetchone()
    return int(row[0]), row[1]


# --------------------------------------------------------------------------
# El resultado
# --------------------------------------------------------------------------
@dataclass
class Finding:
    """Un hallazgo ya medido.

    `row_multiplier` y `value_inflation` **nunca se colapsan**. El primero es
    duplicación de FILAS y es estructural; el segundo dice cuánto se infló ESTA
    cifra y solo existe cuando se pudo recalcular el valor deduplicado.

    Y el multiplicador de filas **no acota** al de valor en ninguna dirección: en
    Q4 queda por debajo (40.0 contra 41.285653) y en A6 por encima (39.7 contra
    39.6336). Por eso el render tiene prohibido cualquier "al menos Nx" o "a lo
    mucho Nx".
    """

    shape: str
    aggregate: str
    aggregate_function: str
    table: str
    one_side: str | None
    many_side: str | None
    join_path: tuple[str, ...]
    columns: tuple[str, ...]
    row_multiplier: float | None
    multiplier_scope: str
    grouped: bool
    source_rows: int
    contributing_rows: int
    distinct_rows: int
    subcase: str | None = None
    reported_value: float | None = None
    deduplicated_value: float | None = None
    value_inflation: float | None = None

    def to_dict(self) -> dict:
        return {
            "shape": self.shape,
            "aggregate": self.aggregate,
            "aggregate_function": self.aggregate_function,
            "table": self.table,
            "one_side": self.one_side,
            "many_side": self.many_side,
            "join_path": list(self.join_path),
            "columns": list(self.columns),
            "row_multiplier": self.row_multiplier,
            "multiplier_scope": self.multiplier_scope,
            "grouped": self.grouped,
            "source_rows": self.source_rows,
            "contributing_rows": self.contributing_rows,
            "distinct_rows": self.distinct_rows,
            "subcase": self.subcase,
            "reported_value": self.reported_value,
            "deduplicated_value": self.deduplicated_value,
            "value_inflation": self.value_inflation,
        }


@dataclass
class FanoutResult:
    verdict: str
    reason: str | None = None
    reason_detail: str | None = None
    subcase: str | None = None
    findings: list[Finding] = field(default_factory=list)
    unattributed_aggregates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "reason_detail": self.reason_detail,
            "subcase": self.subcase,
            "findings": [finding.to_dict() for finding in self.findings],
            "unattributed_aggregates": list(self.unattributed_aggregates),
        }


def _round(value: float | None) -> float | None:
    """Recorta el ruido de punto flotante sin mover el valor medido."""
    return None if value is None else round(value, 6)


def analyze(
    sql: str,
    conn: sqlite3.Connection,
    cat: catalog_mod.Catalog | None = None,
) -> FanoutResult:
    """El detector completo: estática para la forma, dinámica para el multiplicador.

    Dos consultas de SQLite por hallazgo sobre la conexión read-only que ya
    existe, más dos opcionales en el caso angosto. Cero llamadas a API.
    """
    cat = cat if cat is not None else catalog_mod.load(conn)

    try:
        scan = static_scan(sql, cat)
    except OutOfScope as exc:
        # `not_analyzed` va primero a propósito: si no podemos analizar, lo decimos
        # y paramos. No se degrada a `clean`, que afirmaría algo sin verificarlo.
        return FanoutResult(
            verdict=NOT_ANALYZED, reason=exc.reason, reason_detail=exc.detail
        )

    findings: list[Finding] = []
    pairs: list[tuple[Candidate, Finding]] = []
    for candidate in scan.candidates:
        try:
            source_rows, contributing, distinct = _probe_counts(
                conn, candidate.select, scan.root, candidate.alias
            )
        except sqlite3.Error as exc:
            return FanoutResult(
                verdict=NOT_ANALYZED,
                reason=REASON_PROBE_FAILED,
                reason_detail=f"{type(exc).__name__}: {exc}",
            )

        if contributing == 0:
            # Sin filas que aporten, el multiplicador es indefinido. Para
            # `unexplained` eso significa que no hay nada que reportar: esa forma
            # SOLO existe cuando la medición encontró duplicación.
            if candidate.shape == UNEXPLAINED:
                continue
            finding = _make_finding(
                candidate,
                row_multiplier=None,
                subcase=EMPTY_SOURCE if source_rows == 0 else T_ABSENT,
                source_rows=source_rows,
                contributing=contributing,
                distinct=distinct,
            )
        else:
            multiplier = contributing / distinct
            if candidate.shape == UNEXPLAINED and multiplier <= 1.0:
                continue
            finding = _make_finding(
                candidate,
                row_multiplier=multiplier,
                subcase=None,
                source_rows=source_rows,
                contributing=contributing,
                distinct=distinct,
            )

        findings.append(finding)
        pairs.append((candidate, finding))

    _fill_values(conn, scan, pairs)

    if not findings and scan.unattributed_aggregates:
        # Nada que reportar Y un agregado sensible que no se pudo verificar. El
        # veredicto NO puede ser `clean`: `clean` afirma que se midió y no se
        # encontró duplicación, y sobre este agregado no se midió nada.
        #
        # **La regla se corrigió con evidencia, el 2026-07-30.** La primera versión
        # dejaba pasar estas queries como `clean` nombrando el agregado aparte, y
        # medido sobre el corpus eso escondía **tres entradas de Q5 en la config B**
        # —ids 45, 46 y 48— que el ROADMAP documenta como portadoras del artefacto
        # de fan-out. Un `clean` sobre la falla que esta rebanada existe para cazar
        # es exactamente el "degradar a clean lo que no verificamos" que la
        # especificación prohíbe.
        return FanoutResult(
            verdict=NOT_ANALYZED,
            reason=REASON_UNATTRIBUTABLE,
            reason_detail=(
                "sin columna a la que atribuir la duplicación: "
                + ", ".join(scan.unattributed_aggregates)
            ),
            unattributed_aggregates=scan.unattributed_aggregates,
        )

    if not findings:
        verdict = CLEAN
    elif any(f.row_multiplier is not None and f.row_multiplier > 1.0 for f in findings):
        # Si hay varios hallazgos, el veredicto es el peor caso.
        verdict = INFLATED
    elif any(f.row_multiplier is not None for f in findings):
        verdict = SHAPE_NO_INFLATION
    else:
        # La precedencia es POR HALLAZGO: `no_contributing_rows` solo gana cuando
        # NINGUNO se pudo medir. Con uno medible y otro no, gana el medible.
        verdict = NO_CONTRIBUTING_ROWS

    return FanoutResult(
        verdict=verdict,
        subcase=findings[0].subcase if verdict == NO_CONTRIBUTING_ROWS else None,
        # `findings` va POBLADO en `no_contributing_rows`, con el multiplicador en
        # null. Sin eso el guardrail se quedaría callado en el 44% del corpus,
        # incluidas las entradas de Q4 con el fan-out de `budget_usd`.
        findings=findings,
        unattributed_aggregates=scan.unattributed_aggregates,
    )


def _make_finding(
    candidate: Candidate,
    row_multiplier: float | None,
    subcase: str | None,
    source_rows: int,
    contributing: int,
    distinct: int,
) -> Finding:
    return Finding(
        shape=candidate.shape,
        aggregate=candidate.aggregate,
        aggregate_function=candidate.function,
        table=candidate.table,
        one_side=candidate.one_side,
        many_side=candidate.many_side,
        join_path=candidate.join_path,
        columns=candidate.columns,
        row_multiplier=_round(row_multiplier),
        # El multiplicador se calcula global sobre la fuente de filas, nunca por
        # grupo. Con GROUP BY eso prueba que EXISTE duplicación en algún lugar del
        # resultado, no que cada grupo esté afectado.
        multiplier_scope="global",
        grouped=candidate.has_group_by,
        source_rows=source_rows,
        contributing_rows=contributing,
        distinct_rows=distinct,
        subcase=subcase,
    )


def _fill_values(
    conn: sqlite3.Connection,
    scan: StaticScan,
    pairs: list[tuple[Candidate, Finding]],
) -> None:
    """Valor reportado y valor deduplicado, para cada hallazgo que los admita.

    > **Corrección 2026-07-30: el caso angosto estaba demasiado angosto.**
    >
    > Las condiciones originales eran cuatro —exactamente un agregado marcado,
    > forma `fan_trap`, `SUM` o `COUNT` sobre una columna del lado "uno", y sin
    > `GROUP BY`— y **medido sobre el corpus dispararon 0 de 25 veces.** Una regla
    > que nunca aplica no protege de nada. Se quitan las dos primeras: quedan
    > **sin `GROUP BY`** y **`T` es tabla base**.
    >
    > Lo que **no** cambia es el principio: `deduplicated_value` se **recalcula
    > contra la base**, nunca se aproxima dividiendo. Ensanchar cuándo se mide no
    > es lo mismo que aflojar cómo se mide.

    `GROUP BY` se queda fuera porque ahí "el valor reportado" no es un número, es
    una columna de números, y el par reportado/deduplicado deja de tener sentido.
    """
    for candidate, finding in pairs:
        if finding.row_multiplier is None or candidate.has_group_by:
            continue

        # `COUNT` de la identidad de fila: aquí `value_inflation` es exacto por
        # aritmética y **no depende de medir nada más**, así que se llena antes de
        # tocar la base y sobrevive aunque las sondas de valor fallen.
        if candidate.counts_identity:
            finding.value_inflation = finding.row_multiplier

        if candidate.node is None:
            continue
        try:
            finding.reported_value = _reported_value(
                conn, candidate.select, scan.root, candidate.node
            )
        except sqlite3.Error:
            continue

        if candidate.argument is None:
            continue
        try:
            rows, value = _deduplicated_value(
                conn,
                candidate.select,
                scan.root,
                candidate.alias,
                candidate.argument,
                candidate.function,
            )
        except sqlite3.Error:
            continue

        if rows != finding.distinct_rows:
            # El valor no está determinado por la fila de `T`, así que no hay un
            # "mismo agregado sin duplicación" que calcular. Se deja en `null`.
            continue
        finding.deduplicated_value = value

        reported = finding.reported_value
        if (
            finding.value_inflation is None
            and isinstance(reported, (int, float))
            and isinstance(value, (int, float))
            and value
        ):
            finding.value_inflation = _round(reported / value)
