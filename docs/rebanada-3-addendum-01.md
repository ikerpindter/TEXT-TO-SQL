# Rebanada 3, addendum 01. Fechado 29 de julio de 2026

**Artefacto como se entregó el 29 de julio de 2026. El `docs/ROADMAP.md` es la fuente
viva. Este archivo no se mantiene; las correcciones van fechadas al inicio, nunca
reescritas.**

---

> **Corrección 2026-07-29: el caso C1 de la sección 3 no ejercita lo que dice
> ejercitar.**
>
> C1 se declara como "la prueba de que la corrección de la fórmula sirve", y su
> rationale dice que "las comunidades sin casas canceladas producen filas con `h.id`
> en NULL". **Medido contra `data/portfolio.db`: hay cero comunidades sin casas
> canceladas.** Las 20 tienen al menos una.
>
> Con lo cual, sobre el SQL exacto de C1:
>
> ```
> COUNT(*) = 54    COUNT(h.id) = 54    COUNT(DISTINCT h.id) = 54
> fórmula corregida  54/54 = 1.0
> fórmula original   54/54 = 1.0        <- idéntica, no hay falso positivo
> ```
>
> **Las dos fórmulas dan el mismo resultado, así que C1 no puede detectar una
> regresión de la fórmula.** El `expected_verdict: clean` **es correcto**; lo que no
> se cumple es la función del caso. Y C1 es uno de los dos casos declarados no
> negociables.
>
> Lo mismo pasa con cualquier `ON` basado en `status` o en un `IS NULL`: las 20
> comunidades tienen al menos una casa de cada uno de los cuatro estados, y también
> con `closing_date IS NULL` y con `sale_price IS NULL`. Esta base no tiene huecos de
> FK ni huecos de categoría.
>
> **Arreglo verificado**, pendiente de decisión: cambiar el `ON` a un umbral de
> precio. Con `h.sale_price > 750000`:
>
> ```
> COUNT(*) = 32    COUNT(h.id) = 14    COUNT(DISTINCT h.id) = 14    filas NULL = 18
> fórmula corregida  14/14 = 1.0        -> clean, correcto
> fórmula original   32/14 = 2.2857     -> inflated, falso positivo
> ```
>
> Eso sí hace lo que C1 dice hacer. Ver el reporte de la etapa 1b.

---

> Complemento de `rebanada-3-especificacion.md`, que no se reescribe. Aquí hay tres cosas:
> una corrección al significado del multiplicador, la especificación de la partición
> dev/holdout que faltaba, y el set adversario completo.
>
> El ROADMAP sigue siendo la fuente viva. Este archivo tampoco se mantiene.

---

## 1. Corrección: el multiplicador no es el factor de inflación

La especificación traía `"multiplier": 41.3` en el JSON de ejemplo, junto a
`reported_value: 14388050000.0` y `deduplicated_value: 348500000.0`. Está mal.

- 41.3 es el **ratio de valor**: 14,388,050,000 / 348,500,000.
- 40.0 es el **multiplicador de filas** medido: 400 casas entre 10 comunidades.

Difieren porque la suma con fan-out es `Σ(budget_c × n_c)` y la correcta es `Σ(budget_c)`.
El ratio entre las dos es el promedio de `n_c` ponderado por presupuesto. El multiplicador
de filas es el promedio de `n_c` sin ponderar. Coinciden solo si la columna agregada no
correlaciona con el conteo del fan-out, y en datos reales casi siempre correlaciona.

**La regla:**

| Agregado afectado | ¿El multiplicador de filas es el factor de inflación? |
|---|---|
| `COUNT` de la PK de la tabla afectada | Sí, exacto por definición |
| `SUM`, `AVG`, `TOTAL` de cualquier otra columna | No. Solo indica el orden de la duplicación |

### Qué cambia en la salida

Dos campos separados que nunca se colapsan:

- `row_multiplier`: `COUNT(T.pk) / COUNT(DISTINCT T.pk)`. Siempre calculable. Es el factor
  de duplicación de filas, no una afirmación sobre el número reportado.
- `value_inflation`: `reported_value / deduplicated_value`. Solo en el caso angosto donde
  `deduplicated_value` existe. `null` en cualquier otro caso, y no se aproxima con
  `row_multiplier`.

### Qué cambia en el render

Cuando existe `value_inflation`, se cita ése y se dice de dónde sale.

Cuando no existe, el texto habla de la duplicación y **nunca afirma por cuánto está mal el
número**. Va: "el presupuesto se sumó una vez por cada casa de la comunidad, alrededor de
40 casas por comunidad". No va: "el presupuesto está inflado 40x".

Esta distinción es el punto del proyecto. Un guardrail que reporta un factor de inflación
que no midió está fabricando precisión, que es la misma falla que le medimos al modelo.

### Nota de lenguaje sobre `inflated`

`inflated` significa "al menos un agregado está afectado por duplicación de filas". Para
`SUM` y `COUNT` el efecto siempre es hacia arriba. Para `AVG` puede ir en cualquier
dirección, porque el resultado se vuelve un promedio ponderado. El veredicto no se
renombra, pero el render para `AVG` dice "distorsionado", no "inflado".

### Reducción de alcance

`GROUP_CONCAT` sale de la lista de agregados sensibles de v1. Razón: cero apariciones en 49
muestras de output real del modelo. No hay blanco. Lección 10 aplicada tal cual. Si aparece
en la rebanada 4 o 5, se reintroduce con su caso de prueba.

`TOTAL` se queda. Es el alias de `SUM` en SQLite y comparte camino de código, pero necesita
su assert.

### Ajuste de redacción en la salvedad de GROUP BY

La especificación decía que un multiplicador global mayor a 1 ya prueba duplicación. Preciso:
prueba que **existe** duplicación en algún lugar del resultado, no que cada grupo esté
afectado. Suficiente para marcar y explicar, insuficiente para afirmar algo de una fila
específica del output. Así se redacta.

---

## 2. La partición dev/holdout

Faltaba por completo. Si se decide después de ver las etiquetas, no es un holdout.

### El set adversario no se parte

Va 100% a dev. Son unit tests con respuesta declarada, no una muestra. Entran a la
estimación de desempeño de nadie. Se reportan como pasa o falla por caso, contra el
veredicto esperado declarado en la sección 3.

Razón: son deliberadamente adversarios y no representan output del modelo. Mezclarlos con
el corpus real produciría una precision y un recall que no describen ninguna de las dos
poblaciones.

### El corpus real se parte 50/50, estratificado

- **Estratos**: la tupla `(is_no_rows, has_cte, has_left_join)`, usando los flags
  estructurales ya medidos en el lote de verificación. Son hechos medidos, no etiquetas, así
  que no hay fuga.
- **Asignación**: dentro de cada estrato, shuffle con seed `20260729` y luego alternar dev
  y holdout. Con 2 entradas de `no_rows`, una a cada lado. Con 6 de CTE, tres y tres.
- **Congelado**: la asignación se escribe en `evals/gold/split_assignment.json` y se
  commitea **antes** de que exista una sola etiqueta.
- **Limitación documentada**: los 13 `LEFT JOIN` son un conteo sintáctico del scope de más
  afuera y pueden ser un piso. Estratos imperfectos siguen ganándole a un split aleatorio
  con N chica, pero la imperfección se anota.

### Qué puede y qué no puede concluir el holdout

Puede: cachar overfitting grueso. Si el comportamiento cambia fuerte entre la mitad que se
usó para construir y la que no, eso se ve.

No puede: producir una tasa publicable. Son 49 entradas, mitades de 24 y 25, con tasa de
positivos desconocida. Precision y recall se reportan **en conteos, nunca en porcentajes**,
hasta que exista el gold set grande de la rebanada 4.

---

## 3. Set adversario: 19 casos

Van a `evals/gold/corpus_sql_adversarial.json`. Cada caso lleva: `id`, `sql`,
`expected_verdict`, `expected_shape` (o null), `reason_tag` (para los `not_analyzed`), y
`rationale`.

**Estos casos NO se etiquetan a ciegas.** Traen su respuesta declarada por diseño. Van en su
propio archivo, jamás en las worksheets ciegas.

**Limitación honesta:** las respuestas esperadas las escribí yo razonando sobre la
especificación. Si mi razonamiento está mal, el test codifica mi error. Por eso cada caso
lleva su `rationale`: una expectativa equivocada queda auditable en vez de invisible.

### Deben salir `inflated`

**A1. Fan trap clásico. La forma de Q4.**
```sql
SELECT SUM(c.budget_usd) FROM communities c JOIN homes h ON h.community_id = c.id
```
`shape: fan_trap`. `budget_usd` vive en el lado uno y se suma una vez por casa.
`row_multiplier` esperado 39.7 (794/20). `deduplicated_value` sí se calcula, caso angosto.

**A2. Chasm trap multi-salto. La forma de Q5. EL CASO CRÍTICO.**
```sql
SELECT COUNT(h.id) FROM companies co
JOIN financials f ON f.company_id = co.id
JOIN communities c ON c.company_id = co.id
JOIN homes h ON h.community_id = c.id
```
`shape: chasm_trap`. Dos ramas desde `companies` con profundidades distintas: una a
`financials` (un salto), otra a `homes` (dos saltos vía `communities`). `row_multiplier`
esperado 2.0, y como es `COUNT` de la PK afectada, `value_inflation` también 2.0.

Un detector que solo compare hijos directos de un ancestro **falla este caso**, y es uno de
los dos medidos en la rebanada 2. Si A2 no pasa, el detector no sirve.

**A3. Fan trap con AVG.**
```sql
SELECT AVG(c.budget_usd) FROM communities c JOIN homes h ON h.community_id = c.id
```
`shape: fan_trap`. El promedio se vuelve ponderado por casas. Render dice "distorsionado",
no "inflado". `deduplicated_value` va null: el caso angosto es solo `SUM` y `COUNT`.

**A4. Fan trap con GROUP BY.**
```sql
SELECT c.id, SUM(c.budget_usd) FROM communities c
JOIN homes h ON h.community_id = c.id GROUP BY c.id
```
`shape: fan_trap`, `multiplier_scope: "global"`. Prueba la salvedad de GROUP BY con su
redacción corregida.

**A5. Fan trap con TOTAL.**
```sql
SELECT TOTAL(c.budget_usd) FROM communities c JOIN homes h ON h.community_id = c.id
```
Mismo camino que `SUM`. Existe para que `TOTAL` deje de ser supuesto (hueco 8.5).

### Debe salir `shape_no_inflation`

**B1. El falso positivo que predije como dominante.**
```sql
SELECT COUNT(h.id) FROM companies co
JOIN financials f ON f.company_id = co.id AND f.fiscal_year = 2024
JOIN communities c ON c.company_id = co.id
JOIN homes h ON h.community_id = c.id
```
Idéntico a A2 salvo el filtro de año fiscal. La forma de chasm trap está, pero `financials`
queda en una fila por compañía y `row_multiplier` sale 1.0. Un detector estático puro marca
esto como `inflated`. El multiplicador medido es lo único que lo distingue de A2.

### Deben salir `clean`

**C1. Regression test de la fórmula corregida. IMPORTANTE.**
```sql
SELECT SUM(h.sale_price) FROM communities c
LEFT JOIN homes h ON h.community_id = c.id AND h.status = 'cancelled'
```
`T = homes`. Las comunidades sin casas canceladas producen filas con `h.id` en NULL.

- Fórmula corregida `COUNT(h.id)/COUNT(DISTINCT h.id)` da 1.0 → `clean`. Correcto.
- Fórmula original `COUNT(*)/COUNT(DISTINCT h.id)` da más de 1.0 → `inflated`. Falso
  positivo.

Este caso es la prueba de que la corrección sirve. Si sale `inflated`, la fórmula vieja
sobrevivió en algún lado.

**C2. CTE que pre-agrega bien.**
```sql
WITH per_comm AS (SELECT community_id, COUNT(*) AS n FROM homes GROUP BY community_id)
SELECT SUM(c.budget_usd) FROM communities c JOIN per_comm p ON p.community_id = c.id
```
Correcta. `communities` no se duplica porque `per_comm` tiene una fila por comunidad. Un
detector que no analice por scope marca esto. Prueba `traverse_scope`.

**C3. COUNT con DISTINCT.**
```sql
SELECT COUNT(DISTINCT c.id) FROM communities c JOIN homes h ON h.community_id = c.id
```
Inmune por aritmética.

**C4. MAX del lado uno.**
```sql
SELECT MAX(c.budget_usd) FROM communities c JOIN homes h ON h.community_id = c.id
```
Duplicar filas no mueve un máximo.

**C5. Una sola tabla.**
```sql
SELECT SUM(budget_usd) FROM communities
```
Sin joins no hay forma.

**C6. Agregado solo del lado muchos.**
```sql
SELECT SUM(h.sale_price) FROM communities c JOIN homes h ON h.community_id = c.id
```
Cada casa liga con exactamente una comunidad, así que `homes` no se duplica.

**C7. Sin agregados.**
```sql
SELECT c.id, h.status FROM communities c JOIN homes h ON h.community_id = c.id
```
Sin agregado no hay nada que inflar. Prueba la definición de "forma presente".

### Debe salir `no_rows`

**D1. Precedencia sobre shape_no_inflation.**
```sql
SELECT SUM(c.budget_usd) FROM communities c
JOIN homes h ON h.community_id = c.id WHERE h.status = 'sold'
```
`'sold'` no existe en `homes.status` (los valores son available, backlog, cancelled,
closed). Cero filas, multiplicador indefinido. La forma de fan trap está presente, y el
veredicto tiene que ser `no_rows`, **no** `shape_no_inflation`. Si sale
`shape_no_inflation`, la regla de precedencia no se implementó.

### Deben salir `not_analyzed`

Todos con su `reason`.

**E1. Self join.** `reason_tag: self_join`
```sql
SELECT COUNT(*) FROM homes h1 JOIN homes h2 ON h1.community_id = h2.community_id
```

**E2. Join sobre columnas que no son FK.** `reason_tag: non_fk_join`
```sql
SELECT SUM(c.budget_usd) FROM communities c JOIN companies co ON co.name = c.state
```
Sintácticamente válido, semánticamente absurdo. No hay relación de FK, así que no se puede
determinar el lado uno.

**E3. Window function.** `reason_tag: window_function`
```sql
SELECT SUM(budget_usd) OVER (PARTITION BY company_id) FROM communities
```

**E4. Operación de conjuntos.** `reason_tag: set_operation`
```sql
SELECT SUM(budget_usd) FROM communities WHERE company_id = 1
UNION ALL
SELECT SUM(budget_usd) FROM communities WHERE company_id = 2
```

**E5. Columna ambigua.** `reason_tag: ambiguous_column`
```sql
SELECT COUNT(id) FROM communities c JOIN homes h ON h.community_id = c.id
```
`id` existe en las dos tablas del scope. `qualify` con `validate_qualify_columns=True` debe
lanzar `OptimizeError`. Prueba que el camino de excepción llega a `not_analyzed` con razón,
y no a una atribución silenciosa.

### Cobertura

| Veredicto | Casos |
|---|---|
| `inflated` | A1 a A5 |
| `shape_no_inflation` | B1 |
| `clean` | C1 a C7 |
| `no_rows` | D1 |
| `not_analyzed` | E1 a E5 |

Los dos que no se negocian: **A2**, porque es la forma multi-salto medida en la rebanada 2,
y **C1**, porque es la prueba de la corrección de la fórmula.

---

## 4. Huecos del punto 8 que se cierran ahora

Todo read-only, cero API.

1. **Correctitud de `qualify` (8.1), cerrada por argumento, no por muestra.** Dos
   verificaciones automáticas sobre los 49: (a) toda columna calificada existe en la tabla
   que se le asignó, según `PRAGMA table_info`; (b) de las columnas sin prefijo en el SQL
   original, cuántas tenían su nombre en más de una tabla del scope. Si (b) da cero,
   `qualify` no tuvo margen para equivocarse y el hueco queda cerrado completo.
2. **Denominador del chequeo del multiplicador (8.2).** Cuántos pares se midieron de
   verdad, de 49. El número honesto es "0 diferencias entre N medidos" con N explícito.
3. **`PRAGMA index_list` e `index_info` (8.4).** El alcance de v1 dice que el lado uno es la
   tabla referenciada cuando la columna es PK o tiene índice UNIQUE, y solo se leyeron PKs.
4. **Barrido de mayúsculas (8.11).** Cuántas de las 49 usan literales de texto cuya caja no
   coincide con ningún valor de la columna. Puede haber más `no_rows` latentes.
5. **El script del lote, commiteado** como desechable fechado, para que
   `corpus_verification.md` sea reproducible desde el repo.

Se quedan abiertos a propósito, anotados en el ROADMAP:

- **`T` por query (8.3).** Determinar `T` requiere la lógica del detector. Se cierra con la
  primera salida del detector, no antes.
- **Trazar el join path real de Q5 (8.7).** Se cierra cuando el detector corra sobre el
  corpus. A2 cubre la forma mientras tanto.
- **Duplicación semántica del corpus (7 del reporte anterior).** Se mide antes de publicar
  cualquier conteo de precision o recall, porque cambia la N efectiva.
- **`generate.py` (8.10)** y **joins anidados en CTEs (8.8).**
