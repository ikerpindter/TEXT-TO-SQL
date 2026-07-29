# Rebanada 3: especificación del detector de fan-out

**Especificación como se entregó el 29 de julio de 2026. El `docs/ROADMAP.md` es la
fuente viva. Este archivo no se mantiene; las correcciones van fechadas al inicio,
nunca reescritas.**

---

> **Corrección 2026-07-29: el `"multiplier": 41.3` del JSON de ejemplo de la sección 5
> es un ratio de valor, no el multiplicador que define la sección 2.**
>
> El ejemplo pone `"multiplier": 41.3` junto a `reported_value: 14388050000.0` y
> `deduplicated_value: 348500000.0`, lo que sugiere que el multiplicador es el cociente
> de esos dos. Medido contra `data/portfolio.db` sobre ese mismo caso:
>
> - `COUNT(T.pk) / COUNT(DISTINCT T.pk)`, la fórmula de la sección 2: `400/10` = **40.0**
> - `reported_value / deduplicated_value`: `14,388,050,000 / 348,500,000` = **41.285653**
>
> Difieren porque el ratio de valor está ponderado por `budget_usd`: cada comunidad
> aporta su presupuesto por *su propio* número de casas, y los presupuestos no son
> iguales.
>
> **Consecuencia: `deduplicated_value` no se puede derivar dividiendo `reported_value`
> por el multiplicador.** Esa división da `359,701,250` contra `348,500,000` reales,
> 3.21% de error en una cifra que se vería exacta. Es el sustento numérico del "no se
> aproxima" de la sección 4.
>
> Las secciones 2 y 4 **no cambian**: la fórmula es correcta para lo que mide —probar
> que existe duplicación— y la restricción de `deduplicated_value` al caso angosto era
> ya la decisión correcta. Lo que estaba mal es la etiqueta del campo en el ejemplo.
>
> Medición completa en `evals/results/corpus_verification.md`.

> **Nota 2026-07-29 sobre la sección 2.** La corrección del numerador
> (`COUNT(T.pk)` en lugar de `COUNT(*)`) se verificó sobre el corpus de la etapa 1 y
> resultó **correcta e inerte ahí**: esta base no tiene huecos de FK, así que ningún
> `LEFT JOIN` sobre FKs declaradas produce `T.pk` NULL y las dos fórmulas coinciden en
> los 49. Se queda. Forzando el hueco, la fórmula original **divide por cero**; la
> corregida da indefinido, o sea `no_rows`. La corrección evita un crash además de un
> falso `inflated`.

---

> Este archivo existe porque el prompt original se truncó al pegarse y se perdió todo de
> la tarea 5 en adelante. Se lee desde disco, no se pega. Regla nueva que sale de esto:
> toda especificación larga viaja como archivo, nunca como pegado.
>
> Contenido: los cinco veredictos, la fórmula del multiplicador corregida, el alcance de
> v1, la forma de la salida, las reglas que faltan en `CLAUDE.md`, las etapas, y la lista
> de cierre. Nada de esto es código todavía.

---

## 1. Los cinco veredictos

Cada SQL analizado recibe exactamente un veredicto. Se evalúan **en este orden** y el
primero que aplica gana.

| Orden | Veredicto | Cuándo |
|---|---|---|
| 1 | `not_analyzed` | El detector no pudo analizar la query. Siempre con `reason`. |
| 2 | `no_rows` | La fuente de filas devuelve 0. El multiplicador es indefinido. |
| 3 | `clean` | Analizada, sin forma de fan-out presente. |
| 4 | `shape_no_inflation` | La forma está presente, el multiplicador medido es 1.0. |
| 5 | `inflated` | La forma está presente y el multiplicador medido es mayor a 1.0. |

Reglas sobre los veredictos:

- `not_analyzed` va primero a propósito. Si no podemos analizar, lo decimos y paramos. No
  se degrada a `clean`, que afirmaría algo que no verificamos.
- `no_rows` va antes que `clean` porque el multiplicador no se puede calcular sobre cero
  filas. "Estaba rota por otra razón" y "no hubo inflación" son hechos distintos y no se
  colapsan. Nunca se reporta `shape_no_inflation` sobre una query sin filas.
- Si hay varios hallazgos en la misma query, el veredicto es el peor caso. Un solo
  hallazgo `inflated` hace que la query sea `inflated`.
- "Forma presente" significa las dos cosas juntas: la estructura de joins **y** un
  agregado sensible a duplicación sobre una columna afectada. Una query sin agregados no
  tiene forma, va `clean`.

---

## 2. El multiplicador

```
multiplier = COUNT(T.pk) / COUNT(DISTINCT T.pk)
```

Sobre la misma fuente de filas de la query original (FROM, JOINs y WHERE, sin ORDER BY ni
LIMIT), donde `T` es la tabla cuya columna se está agregando y `pk` su llave primaria.

**Corrección respecto al diseño original.** La fórmula decía `COUNT(*)` en el numerador y
está mal. Con `LEFT JOIN`, las filas sin match traen `T.pk` en NULL: `COUNT(*)` las cuenta
y `COUNT(DISTINCT T.pk)` no, así que el multiplicador sale inflado sin que exista
inflación. `COUNT(T.pk)` excluye NULLs igual que el denominador. Correcta para INNER y para
LEFT.

Consecuencia: `no_rows` se define como `COUNT(T.pk) = 0`.

Costo: dos queries de SQLite por hallazgo, sobre la conexión read-only que ya existe. Cero
llamadas a API.

---

## 3. Las dos formas

| Forma | Qué es | Caso medido |
|---|---|---|
| `fan_trap` | Se agrega una columna del lado "uno" después de unir al lado "muchos" | Q4, `budget_usd` inflado 41.3x |
| `chasm_trap` | Dos ramas uno a muchos desde un ancestro común, unidas entre sí. Cada rama multiplica a la otra | Q5, casas por 2 años fiscales |

**Las ramas del chasm trap pueden tener más de un salto.** En este esquema `homes` no tiene
FK directa a `companies`, llega vía `communities`. Las dos ramas de Q5 salen de `companies`
con profundidades distintas: una a `financials` (un salto) y otra a `homes` (dos saltos, vía
`communities`). Un detector que solo compare hijos directos de un ancestro no caza Q5, que
es uno de los dos casos medidos. La búsqueda de ramas hermanas tiene que ser a cualquier
profundidad.

---

## 4. Alcance de v1

### Dentro

- Un solo statement SELECT, con o sin CTEs, dialecto sqlite.
- Agregados sensibles a duplicación: `SUM`, `AVG`, `COUNT` sin DISTINCT, `TOTAL`,
  `GROUP_CONCAT`.
- Dirección del join solo desde FKs declaradas (`PRAGMA foreign_key_list`). El lado "uno"
  es la tabla referenciada cuando la columna referenciada es PK o tiene índice UNIQUE.
  Nunca se infiere de los datos.
- Joins explícitos con ON, y joins por coma con igualdad en WHERE.
- Análisis por scope con `traverse_scope`, así que un CTE que pre-agrega bien no se marca.
- Las dos formas de la sección 3.

### Nunca se marcan, y no es excepción afinada

- Cualquier agregado con DISTINCT.
- `MAX` y `MIN`.

Es aritmética, no criterio: duplicar filas no mueve el valor de un máximo ni de un
distinto. Esto no es un hoyo del guardrail en el sentido de la lección 4, porque no
depende de juicio.

### Fuera de v1, van a `not_analyzed` con su `reason`

- Self joins.
- Window functions.
- UNION, INTERSECT, EXCEPT.
- Joins sobre columnas que no son una relación de FK declarada, por ejemplo unir por
  `name`.
- Subqueries correlacionadas en la lista del SELECT.
- Columnas que `qualify` no resuelve o declara ambiguas. Ya sabemos que lanza
  `OptimizeError`, así que este camino falla ruidoso y eso está bien.

### Dentro, pero reportado con salvedad

- `GROUP BY`: el multiplicador se calcula global sobre la fuente de filas, no por grupo.
  Se reporta con `multiplier_scope: "global"`. No va a `not_analyzed`, porque un
  multiplicador global mayor a 1 ya prueba que existe duplicación.
- `deduplicated_value`: solo en el caso angosto. Exactamente un agregado marcado, forma
  `fan_trap`, el agregado es `SUM` o `COUNT` sobre una columna de la tabla del lado "uno",
  y sin GROUP BY. En cualquier otro caso va `null`. No se aproxima.

---

## 5. Forma de la salida

Estructurado en el JSON de la corrida, más un render corto en la CLI. Los dos, porque la
rebanada 4 necesita scorear automático y en la rebanada 6 esto lo consume un agente, y un
agente no lee prosa.

```json
"fanout": {
  "verdict": "inflated",
  "reason": null,
  "findings": [{
    "shape": "fan_trap",
    "aggregate": "SUM(communities.budget_usd)",
    "one_side": "communities",
    "many_side": "homes",
    "join_path": ["homes.community_id = communities.id"],
    "multiplier": 41.3,
    "multiplier_scope": "global",
    "reported_value": 14388050000.0,
    "deduplicated_value": 348500000.0
  }]
}
```

`reason` se llena solo cuando el veredicto es `not_analyzed`. `findings` va vacío en
`clean` y en `not_analyzed`.

El render de la CLI nombra la consecuencia, no la mecánica. Va "el presupuesto se sumó una
vez por cada casa de la comunidad, no una vez por comunidad, multiplicador medido 41.3x".
No va "fan-out detectado en el join". La respuesta se sigue mostrando siempre: marca y
explica, no bloquea. El `deduplicated_value` se muestra etiquetado como diagnóstico, nunca
como la respuesta.

Sin taxonomía de severidad en v1. El `shape` sí, porque el eval lo necesita. Severidad no,
porque no hay datos todavía para inventar los niveles.

---

## 6. Reglas para `CLAUDE.md` (que no se commitea)

Las tres que ya pusiste se quedan, están bien. Agrega estas tres:

4. `fanout_labels_holdout.md` es intocable hasta la etapa 4. No lo leas, no lo abras, no lo
   uses para nada mientras construyes el detector. Si necesitas un caso de prueba, sale del
   dev o se escribe a mano.
5. sqlglot va pineado exacto, siempre. Nunca un rango. En este proyecto un salto de MINOR
   rompe compatibilidad.
6. `corpus_sql.json` y `corpus_sql_adversarial.json` quedan congelados en cuanto se
   commitean. Variable nueva significa archivo nuevo con la variable en el nombre, nunca
   una edición. Si se detecta un error de metadatos, va una nota de corrección fechada al
   inicio.

Y una séptima que se ganó este episodio:

7. Especificaciones largas se leen desde un archivo en disco, no desde un pegado. El
   pegado se trunca en silencio y el truncamiento no se nota hasta que algo falta.

---

## 7. Las etapas de la rebanada 3

| Etapa | Qué | Estado |
|---|---|---|
| 1 | Corpus congelado, pin de sqlglot, criterios de etiquetado | CERRADA (`8e140b4`, `e111d8f`) |
| 1b | Set adversario escrito a mano, worksheets ciegas de la unión, validador | Siguiente |
| 2 | Iker etiqueta a mano, solo la mitad dev | |
| 3 | Detector construido y corrido contra dev | |
| 4 | Se abre el holdout, una sola vez | |

El invariante que no se negocia: **worksheets y etiquetas se commitean antes de que exista
una sola línea del detector.** El orden de los commits es la evidencia de que no se
etiquetó mirando el output.

---

## 8. Lo que NO puede entrar a la worksheet

Además de la pregunta, el id de pregunta, la config y la categoría, ahora sabemos que los
JSON traen `result.row_count`. **Ese campo tampoco entra.** Una query que devolvió 4 filas
cuando se pidió un solo total se delata sola, y ver eso mientras etiquetas ya no es
etiquetar el SQL, es leer el resultado.

La worksheet lleva: id, SQL formateado, `LABEL:`, `SHAPE:`. En el header, el DDL completo
y el criterio resumido. Nada más.

---

## 9. Lista de cierre (las ocho cosas)

Al cerrar cualquier etapa, reporta:

1. Tus predicciones contra lo que salió, marcando explícitamente cuáles fallaste.
2. Versiones instaladas y la URL de doc oficial donde verificaste cada punto.
3. La forma real de los datos que leíste, sin asumirla.
4. Conteos: totales, distintos después de dedupe, cuántos colapsaron.
5. Resultado de los tests, con la excepción completa si algo truena.
6. Conteos de los splits, cuando apliquen.
7. Hashes de los commits y estado del árbol.
8. Explícitamente qué NO verificaste.

De la etapa 1 ya contestaste 5, 7 y parte de 4. Faltan 1, 2, 3 y 8.
