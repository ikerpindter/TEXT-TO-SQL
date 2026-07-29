# Criterios de etiquetado del gold set de fan-out

Escrito el 29 de julio de 2026, en la etapa 1 de la rebanada 3. **Antes de que
exista una sola línea del detector.**

Ese orden es el punto entero de este archivo. Si el detector se escribe primero,
los criterios se acomodan —sin mala intención y sin que nadie lo note— para que
el detector salga bien. Escribirlos antes es lo que hace que las etiquetas sean
una medición y no un reflejo del código.

## Qué se etiqueta

El corpus congelado en `corpus_sql.json`: **49 SQL distintos**, salidos de las 50
llamadas de `evals/runs/*.json`.

En la etapa 1b se le va a unir un set de SQL adversario escrito a mano
(`corpus_sql_adversarial.json`), y **la worksheet se genera una sola vez de la
unión de los dos archivos.** Por eso no hay worksheet todavía: generarla ahora
obligaría a editarla después, y un archivo congelado no se edita.

La línea base (`evals/results/baseline_ddl_only.md`) **no entra.** Es evidencia,
no fuente de datos.

## Qué es fan-out, para efectos de etiquetar

Una agregación que cae sobre una columna del lado "uno" de un join uno-a-muchos.
El join replica esa fila una vez por cada fila del lado "muchos", y la agregación
suma el mismo valor varias veces.

Es una propiedad **sintáctica** del query contra el catálogo. No hace falta
conocer la respuesta correcta de la pregunta para etiquetarla, y eso es
deliberado: el etiquetador no está juzgando si el query contesta bien, está
juzgando si el query infla.

Las dos puertas ya medidas en la rebanada 2, como calibración:

| Puerta | Forma | Efecto medido |
|---|---|---|
| `communities.budget_usd` (Q4) | `SUM` sobre el lado "uno" de un join a `homes` | $14,388,050,000 contra $348,500,000 reales, **inflado 41.3x** |
| `financials` (Q5) | tabla colgada de un join sin relación de grano real; cada casa duplicada una vez por año fiscal | conteo 102/104 contra 51/52 reales |

La lección que hay que traer al etiquetado: **el fan-out no depende de que la
columna inflada sea `budget_usd`.** Cualquier tabla colgada de un join sin
relación de grano real multiplica todo lo que esté del otro lado.

## Los veredictos

### `no_rows`

La query devolvió **0 filas**. El multiplicador es **indefinido (0/0), no 1.0**.

**Nunca se reporta `shape_no_inflation` sobre una query sin filas.** "Estaba rota
por otra razón" y "no hubo inflación" son hechos distintos y no se colapsan. Una
query que no devuelve nada no es evidencia de que la detección funcionó; es
evidencia de que no hubo nada que medir. Colapsar los dos casos convertiría una
entrada sin información en un acierto del detector.

En el corpus actual son **2 de 49**: ids 19 y 24, ambos de `ddl_only`, Q4 corrida 4
y Q5 corrida 4. El dato sale de `result.row_count` en los JSON de corridas.

### `shape_no_inflation`

Nombrado, **no definido todavía.** Ver el hueco abajo.

### Los otros tres

**No especificados.** El diseño habla de cinco veredictos; en este repo solo están
`no_rows` (definido arriba) y `shape_no_inflation` (solo el nombre). Los otros tres
no se inventan aquí.

Consecuencia práctica: **el etiquetado no puede empezar todavía.** No es un
bloqueo real porque las worksheets se movieron a la etapa 1b de todos modos, pero
el vocabulario completo tiene que existir antes de generarlas.

## Reglas de procedimiento

1. **Ciego.** El etiquetador no ve la config que produjo el SQL. Si la ve, el
   etiquetado deja de ser una medición independiente de la variable que la
   rebanada 2 estaba probando.
2. **Los criterios se escriben antes de las etiquetas, y las etiquetas antes del
   detector.** Los tres archivos se commitean en ese orden.
3. **Una vez commiteadas, las etiquetas no se editan.** Si un criterio cambia, es
   un archivo nuevo. Aplica el protocolo de archivos congelados de
   `docs/ROADMAP.md`: una corrección va como nota fechada al inicio, nunca como
   reescritura silenciosa.
4. **La procedencia no se pierde.** Cada entrada del corpus trae `sources[]` con
   archivo, config, pregunta y número de corrida, así que cualquier etiqueta se
   puede rastrear a la llamada que la produjo.
5. **Un desacuerdo se registra, no se promedia.** Si dos etiquetadores discrepan,
   las dos etiquetas quedan y la discrepancia es el dato.

## Lo que este archivo no decide

- El formato de la worksheet: columnas, y qué campos se le ocultan al etiquetador
  más allá de la config.
- El alcance de v1 del detector.
- Los nombres y definiciones de tres de los cinco veredictos.
