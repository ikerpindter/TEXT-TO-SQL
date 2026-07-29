# Cierre de huecos del lote de verificación

**Fecha:** 29 de julio de 2026
**Script:** `evals/gold/verify_corpus_20260729.py` (commiteado, desechable, fechado)
**Base:** `data/portfolio.db`, sha256 `c710b635…d762` — **gate pasado**
**Entorno:** WSL2, Python 3.12, sqlglot 30.14.0, uv 0.11.30
**Costo:** $0. Read-only.

Cierra los huecos 1 a 5 de la sección 4 de `docs/rebanada-3-addendum-01.md`.
Continuación de `corpus_verification.md`, que está congelado y no se edita.

Este archivo también es de resultados. **No se edita.**

---

## Hueco 8.1: correctitud de `qualify`, cerrado por argumento

### (a) Toda columna calificada existe en la tabla que se le asignó

| | |
|---|---|
| Columnas calificadas verificadas contra `PRAGMA table_info` | **422** |
| Asignadas a una tabla que no tiene esa columna | **0** |

Método: `qualify` sobre las 49, luego `traverse_scope`, y por cada scope se resuelve
el nombre de fuente a su tabla real vía `scope.sources`. Para cada columna con
prefijo se comprueba que la tabla destino realmente tenga esa columna.

### (b) Margen de error: columnas sin prefijo resolubles a más de una tabla

| | |
|---|---|
| Columnas sin prefijo en el SQL original | **20** |
| De esas, con el nombre presente en **más de una** tabla del scope | **0** |

**CERO.** Ninguna columna sin prefijo del corpus era resoluble a dos tablas
distintas. `qualify` **no tuvo margen para equivocarse**: no hubo ninguna decisión
ambigua que tomar.

**El hueco 8.1 queda cerrado completo, por argumento y no por muestra.** El
reporte anterior decía que "pasa 49/49" solo significaba "no lanzó" y que no se
había verificado corrección. Ahora sí: las 422 asignaciones son correctas, y las 20
columnas sin prefijo tenían destino único. No es que `qualify` acertara 49 veces; es
que no había nada que errar.

Esto **no** dice que `qualify` sea correcto en general. Dice que sobre este corpus no
tuvo oportunidad de fallar. El caso E5 del set adversario existe justamente para
meter la ambigüedad a propósito.

---

## Hueco 8.2: el denominador del chequeo del multiplicador

El reporte anterior dijo "0 diferencias" sin denominador. El número honesto:

| | |
|---|---|
| Pares (entrada, tabla) medidos de verdad | **99** |
| Entradas con al menos un par medido | **42 de 49** |
| Entradas sin ningún par medido | 7 — ids **16, 17, 28, 36, 38, 45, 47** |
| Diferencias `COUNT(*) != COUNT(T.pk)` | **0** |
| Entradas con tablas de CTE saltadas | 6 — ids 16, 28, 36, 38, 45, 47 |
| Errores de reconstrucción | 6 |

**La afirmación correcta es: 0 diferencias entre 99 pares medidos, que cubren 42 de
las 49 entradas.** Las 7 restantes son las que tienen CTE o alias de subconsulta,
que esta reconstrucción cruda del scope de más afuera no alcanza. Resolverlas es
análisis por scope, o sea trabajo del detector.

---

## Hueco 8.4: índices UNIQUE

```
companies    sin índices
financials   sqlite_autoindex_financials_1  UNIQUE  origin=pk  cols=['company_id','fiscal_year']
communities  sin índices
homes        sin índices
```

| | |
|---|---|
| Índices UNIQUE en total | 1 |
| UNIQUE que **no** son autoindex de PK | **0** |

El único índice UNIQUE de esta base es el **autoindex que respalda la PK compuesta
de `financials`**, con `origin=pk`. No hay ni una restricción UNIQUE declarada
aparte de las llaves primarias.

**Consecuencia para el alcance de v1: la cláusula "PK o índice UNIQUE" no tiene
blanco en esta base.** El lado "uno" se determina solo por PK. La cláusula se queda
escrita porque el set adversario o la rebanada 4 pueden traer un esquema con UNIQUE
de verdad, pero **hoy no está ejercitada por nada**, y eso hay que saberlo antes de
creer que está probada.

---

## Hueco 8.11: barrido de mayúsculas en literales de texto

| | |
|---|---|
| Literales de texto comparados con `=` | **57** |
| Que **no existen** en la columna | **24** |
| De esos, que fallan **solo por la caja** | **3** |

Los tres de caja:

| id | Predicado | Valor real |
|---|---|---|
| 15 | `homes.status = 'Closed'` | `'closed'` |
| 24 | `homes.status = 'Backlog'` | `'backlog'` |
| 25 | `homes.status = 'Backlog'` | `'backlog'` |

Los 24 que no existen, agrupados por literal: `'Texas'` en `communities.state` (ids
6–10, el valor real es `'TX'`), `'Sold'` / `'sold'` en `homes.status` (ids 6–10, no
existe en ninguna caja), `'Lennar'` en `companies.name` (ids 11–15, el real es
`'Lennar Corporation'`), `'D.R. Horton'` en `name` y en `ticker` (ids 16–20),
`'Closed'` (id 15) y `'Backlog'` (ids 24, 25).

### Lo importante de este hueco

**24 literales inexistentes, pero solo 2 entradas devolvieron 0 filas.** Un literal
que no existe **no implica** 0 filas: solo implica 0 filas si ese predicado es el que
decide. En el resto está dentro de un `OR`, o convive con otros predicados que sí
matchean, o el literal fallido no restringe la fila que se cuenta.

**Hallazgo nuevo: la id 25 usa `'Backlog'` igual que la id 24, y sí devolvió filas.**
Dos queries con el mismo error de caja y resultados distintos. Eso significa que
`no_rows` en este corpus no es un buen proxy de "adivinó mal el literal": el error de
literal es **doce veces más común** que el `no_rows`, y casi siempre queda enmascarado.

Para el etiquetado no cambia nada —el etiquetador juzga la forma del SQL, no si el
literal existe— pero para la rebanada 4 es un aviso: **contar `no_rows` subestima
masivamente la tasa de adivinanza fallida de literales.**

---

## Hueco 5: el script commiteado

`evals/gold/verify_corpus_20260729.py` queda en el repo. Reproduce este archivo y
las tareas 0, 1, 2 y 7 de `corpus_verification.md`.

Es **desechable y fechado a propósito**: no es una herramienta, es el registro
ejecutable de una medición. Si la base o el corpus cambian, no se arregla, se
escribe otro con su fecha. `batch.py` viaja con `evals/runs/`; esto cierra la misma
simetría para `evals/results/`.

No contiene lógica del detector: no decide veredictos, no determina `T` por query y
no busca formas de fan-out. Donde hace falta una tabla y su llave, van hardcodeadas.

---

## `uv lock --check`

```
$ uv lock --check
Resolved 20 packages in 3ms
exit=0
```

---

## Qué sigue abierto, y a propósito

Del reporte anterior, anotado en el ROADMAP:

- **`T` por query (8.3).** Requiere la lógica del detector. Se cierra con su primera
  salida.
- **Trazar el join path real de Q5 (8.7).** Se cierra cuando el detector corra sobre
  el corpus. El caso A2 del set adversario cubre la forma mientras tanto.
- **Duplicación semántica del corpus.** Se mide antes de publicar cualquier conteo de
  precision o recall, porque cambia la N efectiva.
- **`generate.py` (8.10)** y **joins anidados en CTEs (8.8).**
