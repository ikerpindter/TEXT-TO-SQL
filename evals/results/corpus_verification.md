# Verificación del corpus congelado

**Fecha:** 29 de julio de 2026
**Corpus:** `evals/gold/corpus_sql.json`, 49 SQL distintos de 50 corridas
**Base:** `data/portfolio.db`, sha256 `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762`
**Entorno:** WSL2, Python 3.12, sqlglot 30.14.0, uv 0.11.30
**Costo:** $0. Cero llamadas a API. Todo read-only sobre artefactos existentes.

Este es un archivo de resultados. **No se edita.** Una corrección va como nota
fechada al inicio, nunca como reescritura. Ver el protocolo en `docs/ROADMAP.md`.

Las decisiones de interpretación se pre-registraron en el ROADMAP **antes** de
correr cualquiera de estas mediciones.

---

## Tarea 0 (bloqueante): hash de la base

| | |
|---|---|
| sha256 registrado en los tres `.md` congelados | `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762` |
| sha256 real de `data/portfolio.db` | `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762` |
| Tamaño | 57,344 bytes |

**CUADRA.** El gate pasa y el lote procede. La base que produjo las corridas es la
misma que se midió aquí.

Nota de procedencia: el hash estaba registrado en `baseline_ddl_only.md`,
`ddl_only_n5.md` y `values_text_maxcard20_n5.md`. **No** está en los JSON de
`evals/runs/`, que solo graban `db_path`.

---

## Tarea 1: `qualify` sobre los 49

| | |
|---|---|
| Pasan | **49 de 49** |
| Truenan | **0 de 49** |
| Excepciones por tipo | ninguna |

Corrido con `dialect="sqlite"`, el esquema real desde `PRAGMA table_info`,
`infer_schema=False`, y `validate_qualify_columns` en su default `True`.

**Cobertura de `qualify` sobre este corpus: 100%.** El camino
`not_analyzed`-por-columna-no-resuelta está **vacío** aquí. Eso no significa que el
flag sea inofensivo: significa que este corpus no contiene columnas ambiguas ni
irresolubles. El set adversario de la 1b es el lugar para meterlas a propósito.

Por la decisión pre-registrada 1, `validate_qualify_columns=True` se queda. La
cobertura se publica como dato de alcance.

---

## Tarea 2: la fórmula del multiplicador

Fórmula corregida: `COUNT(T.pk) / COUNT(DISTINCT T.pk)`.
Fórmula original: `COUNT(*) / COUNT(DISTINCT T.pk)`.

### Los tres casos

| Caso | `COUNT(*)` | `COUNT(T.pk)` | `COUNT(DISTINCT T.pk)` | Corregida | Original |
|---|---|---|---|---|---|
| (a) Q4 config B run 1, T=`communities` | 400 | 400 | 10 | **40.0** | 40.0 |
| (b) una sola tabla, T=`communities` | 4 | 4 | 4 | **1.0** | 1.0 |
| (c1) `LEFT JOIN` con ON parcial, T=`homes` | 510 | 510 | 510 | **1.0** | 1.0 |
| (c2) `LEFT JOIN` con ON que no matchea, T=`homes` | 20 | **0** | 0 | **indefinido → `no_rows`** | **división por cero** |

**El caso (a) no dio 41.3. Dio 40.0.** Ver la tarea 2b: eso no es un error de la
fórmula, es que 41.3 nunca fue el multiplicador. Son dos cantidades distintas.

**El caso (c) tuvo que forzarse.** Esta base no tiene huecos naturales:

| | |
|---|---|
| Comunidades sin casas | 0 |
| Compañías sin comunidades | 0 |
| Compañías sin `financials` | 0 |

Sin huecos, ningún `LEFT JOIN` sobre las FKs declaradas produce `T.pk` NULL, así
que las dos fórmulas coinciden siempre. El hueco de (c2) se forzó con
`AND h.status = '__no_existe__'` en el `ON`.

**(c2) es donde la corrección se gana el sueldo:** la fórmula original **divide por
cero y truena**; la corregida da indefinido, que es exactamente la definición
pre-registrada de `no_rows` (`COUNT(T.pk) = 0`). La corrección no solo evita un
falso `inflated`, evita un crash.

### En los 49: ¿dónde difieren `COUNT(*)` y `COUNT(T.pk)`?

**Cero diferencias entre los pares medidos.**

Con la cobertura declarada, porque no fue total:

| | |
|---|---|
| Pares (entrada, tabla) con `COUNT(*) != COUNT(T.pk)` | **0** |
| Entradas con CTE cuyas tablas de CTE se saltaron | 6 — ids 16, 28, 36, 38, 45, 47 |
| Entradas con error al reconstruir la fuente de filas | 3 — ids 17, 36, 47 (`OperationalError`, alias de subconsulta fuera del scope de más afuera) |

El método fue reconstruir la fuente de filas del **scope de más afuera** (FROM +
JOINs + WHERE, sin GROUP BY / ORDER BY / LIMIT) y comparar `COUNT(*)` contra
`COUNT(alias.pk)` para cada tabla real. **Es una reconstrucción cruda y no cubre
CTEs ni alias de subconsulta**, que es análisis por scope y es trabajo de la etapa
3. Así que el "cero" es sobre lo medible con este método, no sobre los 49 completos.

**Por la decisión pre-registrada 2, la corrección se queda:** es correcta e
**inerte en este corpus**. Inerte porque la base no tiene huecos de FK, no porque la
fórmula sea equivalente. En el set adversario de la 1b, donde los `LEFT JOIN` con
filas sin match van a escribirse a propósito, deja de ser inerte.

Dato de contexto: **13 de los 49 usan `LEFT JOIN`** (ids 16, 17, 18, 19, 20, 24, 40,
41, 42, 43, 47, 48, 49). La forma está presente en el corpus; lo que no está son los
huecos que la harían morder.

---

## Tarea 2b: el multiplicador de FILAS no es el ratio de VALOR

**Éste es el hallazgo principal del lote.**

Sobre el mismo caso Q4 de la config B:

| Cantidad | Valor |
|---|---|
| Multiplicador de **filas**, `COUNT(T.pk)/COUNT(DISTINCT T.pk)` | 400/10 = **40.000000** |
| Ratio de **valor**, `reportado/correcto` | 14,388,050,000 / 348,500,000 = **41.285653** |
| Diferencia | 1.285653 |

**No son el mismo número, y no pueden serlo.** El multiplicador de filas es el
promedio simple de casas por comunidad. El ratio de valor es el promedio
**ponderado por `budget_usd`**: cada comunidad aporta su presupuesto multiplicado
por *su propio* número de casas. Coinciden solo si todos los presupuestos son
iguales, y no lo son:

| `communities.id` | `budget_usd` | casas |
|---|---|---|
| 11 | 44,100,000 | 41 |
| 12 | 30,700,000 | 29 |
| 13 | 53,900,000 | 49 |
| 14 | 27,600,000 | 42 |
| 15 | 41,300,000 | 50 |
| 16 | 22,850,000 | 33 |
| 17 | 39,750,000 | 40 |
| 18 | 36,200,000 | 40 |
| 19 | 34,800,000 | 41 |
| 20 | 17,300,000 | 35 |

### Consecuencia para el diseño

**`deduplicated_value` no se puede derivar dividiendo por el multiplicador.**
Medido:

```
14,388,050,000 / 40.0  =  359,701,250      <- lo que daría la división
                          348,500,000      <- el valor correcto real
                           11,201,250      <- error, 3.21%
```

Un 3.21% de error presentado como "el valor correcto" es peor que no dar valor: es
una cifra que se ve exacta y no lo es. La especificación ya dice que
`deduplicated_value` solo se calcula en el caso angosto y que **no se aproxima**;
esta medición es la razón numérica de por qué, y ahora está medida en lugar de
supuesta.

Los dos números miden cosas distintas y los dos sirven:
- **El multiplicador de filas prueba que existe duplicación.** Es estructural, no
  depende de los valores de la columna agregada, y es lo que el veredicto necesita.
- **El ratio de valor dice cuánto se infló esta cifra.** Depende de la correlación
  entre los valores y el grado de fan-out por fila, y es lo que el render de la CLI
  quiere nombrar.

---

## Tarea 3: los números propagados contra la base

Los tres se copiaron del ROADMAP a las secciones nuevas del diseño sin verificarse.
Verificados ahora, read-only:

| Afirmado | Real | Veredicto |
|---|---|---|
| 14,388,050,000 | 14,388,050,000.00 | **CUADRA** |
| 348,500,000 | 348,500,000.00 | **CUADRA** |
| 41.3x | 41.285653 → 41.3 | **CUADRA** como ratio de valor |

El valor reportado sale del SQL literal del modelo (config B, Q4, corrida 1) contando
400 casas. El correcto sale de la misma selección sin el join a `homes`.

**Los tres números cuadran. Lo que no cuadra es la etiqueta:** la especificación los
presenta en un JSON de ejemplo donde `"multiplier": 41.3` acompaña a esos dos
valores, y con la fórmula pre-registrada el multiplicador de ese caso es **40.0**.
Ver la nota de corrección en `docs/ROADMAP.md` y en
`docs/rebanada-3-especificacion.md`.

---

## Tarea 4: `MAX`, `MIN` y `COUNT(DISTINCT)` bajo duplicación conocida

Misma selección de 10 comunidades, con y sin el join que las multiplica a 400 filas:

| Agregado | Sin duplicar | Duplicada | ¿Se movió? |
|---|---|---|---|
| `MAX(budget_usd)` | 53,900,000.00 | 53,900,000.00 | **No** |
| `MIN(budget_usd)` | 17,300,000.00 | 17,300,000.00 | **No** |
| `COUNT(DISTINCT budget_usd)` | 10 | 10 | **No** |
| `COUNT(DISTINCT id)` | 10 | 10 | **No** |
| `SUM(budget_usd)` | 348,500,000.00 | 14,388,050,000.00 | **Sí** |
| `AVG(budget_usd)` | 34,850,000.00 | 35,970,125.00 | **Sí** |
| `COUNT(id)` | 10 | 400 | **Sí** |

Confirma la lista de "nunca se marcan" del alcance de v1: `MAX`, `MIN` y cualquier
agregado con `DISTINCT` son insensibles a la duplicación. Era aritmética; ahora está
medida.

Confirma también que `AVG` **sí** pertenece a la lista de sensibles, y por una razón
que vale nombrar: se movió solo 3.21% —de 34.85M a 35.97M— contra el 4,029% de `SUM`.
**Un `AVG` inflado es mucho más difícil de notar a ojo que un `SUM` inflado**, porque
sigue estando en el orden de magnitud correcto.

---

## Tarea 5: el record donde `sql != raw`

Uno de los 50: config `values_text_maxcard20`, Q3, corrida 3. **Corpus id 37.**

| | |
|---|---|
| `len(raw)` | 310 |
| `len(sql)` | 309 |
| Diferencia exacta | `';'` |

**La extracción le quitó el punto y coma final.** Nada más. No hubo cerca de
markdown, ni prefacio en prosa, ni reescritura.

Consecuencia real, y es una nota al pie: **la entrada 37 del corpus no es el output
crudo del modelo byte por byte**, le falta un carácter. Es benigno —un `;` final no
cambia el árbol ni el resultado— pero el docstring de `extract_corpus.py` dice que
guarda "el texto crudo, byte por byte como salió del modelo", y para 1 de las 49 eso
es falso: es byte por byte como salió de `generate.py`.

El campo `raw` de `evals/runs/` sí trae el original, así que nada se perdió.

Relacionado: la normalización del dedupe **no toca el punto y coma**, y está
documentado así a propósito. Si lo tocara, este caso habría colapsado con otro y no
lo habríamos visto.

---

## Tarea 6: por qué las 2 entradas de `no_rows` dan 0 filas

**Las dos son un `WHERE` que no matchea. Ninguna es un join vacío.**

| | id 19 | id 24 |
|---|---|---|
| Procedencia | `ddl_only` Q4 corrida 4 | `ddl_only` Q5 corrida 4 |
| Filas con la query completa | 0 | 0 |
| Filas del join **sin** el `WHERE` | **794** | **1588** |
| Predicado que falla | `co.name = 'D.R. Horton'` → 0 | `h.status = 'Backlog'` → 0 |
| Valor real en la base | `'D.R. Horton, Inc.'` | `'backlog'` (minúscula) |

Valores reales: `companies.name` es `['D.R. Horton, Inc.', 'Lennar Corporation']`.
`homes.status` es `['available', 'backlog', 'cancelled', 'closed']`.

### Consecuencia para la regla de precedencia

**En este corpus, `no_rows` nunca significa "no hubo fan-out". Significa "el literal
estaba mal".** Las dos entradas son la trampa #1 —adivinar literales— y las dos
vienen de `ddl_only`, la config sin valores en el prompt. Una es un sufijo corporativo
faltante, la otra es sensibilidad a mayúsculas en `=` de SQLite.

Esto **valida la decisión de poner `no_rows` antes que `clean`**, y con evidencia
concreta: las dos queries tienen la forma de fan-out presente —id 19 agrega
`SUM(c.budget_usd)` sobre un `LEFT JOIN` a `homes`, id 24 agrega
`SUM(f.backlog_value)` sobre un join a `financials`— y si el veredicto se calculara
sobre 0 filas, las dos se reportarían como `shape_no_inflation`. Serían dos falsos
"el guardrail verificó que está bien" sobre dos queries que están rotas.

Ese es exactamente el colapso que la regla prohíbe, y ocurre en 2 de 49 casos reales,
no en un ejemplo inventado.

---

## Tarea 7: `uv lock --check`

```
$ uv lock --check
Resolved 20 packages in 51ms
exit=0
```

El lock está consistente con `pyproject.toml`. `sqlglot==30.14.0` pineada exacta.

---

## Hallazgo lateral: `args["from"]` devuelve `None` en silencio

No estaba en el lote, salió al escribir el script de la tarea 2.

En sqlglot 30.14.0 las llaves de `Select.args` son:

```
['distinct', 'exclude', 'expressions', 'from_', 'hint', 'joins', 'kind',
 'limit', 'operation_modifiers', 'where']
```

La llave es **`from_`**, con guion bajo. `select.args.get("from")` devuelve `None`
**sin lanzar excepción**, y `select.args["from"]` lanza `KeyError`. La primera forma
es la peligrosa: un detector escrito con `args.get("from")` trataría todas las
queries como si no tuvieran `FROM` y no se quejaría.

**Acceso canónico:** `select.find(sqlglot.exp.From)`, que es estable y no depende del
nombre de la llave.

Esto es la justificación empírica de la regla nueva de `CLAUDE.md`: la verificación
canónica de una API es el fuente en el tag pineado más `inspect.signature` sobre lo
instalado. El sitio de doc no menciona `from_`, y dos de sus páginas del optimizer
dan 404.
