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
- **`COUNT(*)` no se atribuye.** No tiene columna, así que no tiene `T` y el
  multiplicador no es calculable. Por la letra del ROADMAP —"agregado sensible
  sobre una columna afectada"— eso es *sin forma*, o sea `clean`. Pero un `clean`
  mudo ahí afirmaría de más, así que el agregado se nombra en
  `unattributed_aggregates` y el render lo dice. Toca **12 de las 49** entradas del
  corpus. Las dos alternativas se descartaron con razón: callarlo es afirmar
  `clean` sin verificarlo, y marcarlo produce un falso positivo medido sobre
  `COUNT(*) FROM homes JOIN communities`, donde la duplicación de `communities` no
  toca al conteo de casas.
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

from collections import deque
from dataclasses import dataclass, field

import sqlglot
from sqlglot.optimizer import find_all_in_scope, traverse_scope
from sqlglot.optimizer import qualify as qualify_mod

from txt2sql import catalog as catalog_mod

exp = sqlglot.exp

DIALECT = "sqlite"

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
        single_source = len({id(source) for source in scope.sources.values()}) < 2
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
                        select=select,
                        argument=argument,
                        node=node,
                    )
                )

    return scan
