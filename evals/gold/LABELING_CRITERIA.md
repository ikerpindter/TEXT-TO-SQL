# Criterios de etiquetado del gold set de fan-out

> **Reescrito el 29 de julio de 2026, en su lugar.** La versión anterior es de la
> etapa 1 y quedó superada en cuatro puntos: llamaba `no_rows` a lo que ahora es
> `no_contributing_rows`, decía que tres veredictos estaban sin especificar, decía
> que no había worksheet todavía, y decía que la worksheet saldría de la unión del
> corpus con el set adversario. Lo último se revirtió: **el set adversario nunca
> entra a una worksheet.**
>
> Se reescribe en lugar de ir a archivo nuevo porque **nunca produjo una medición.**
> La regla de congelado protege mediciones; un artefacto que no generó ninguna no
> tiene nada que proteger, y git guarda la versión vieja. Ver el principio general
> en `docs/ROADMAP.md`.

Escrito **antes de que exista una sola línea del detector**, y ése es el punto
entero. Si el detector se escribe primero, los criterios se acomodan —sin mala
intención y sin que nadie lo note— para que el detector salga bien. El orden es lo
que hace que las etiquetas sean una medición y no un reflejo del código.

---

## Qué estás etiquetando

Las dos worksheets ciegas: `worksheet_dev.md` (25 casos) y `worksheet_holdout.md`
(24), sacadas de las 49 entradas distintas de `corpus_sql.json`.

**No etiquetas el set adversario.** Los 21 casos de `corpus_sql_adversarial.json`
traen su respuesta declarada por diseño: son unit tests del detector, no una muestra.
Nunca entran a una worksheet.

**No etiquetas la línea base.** `evals/results/baseline_ddl_only.md` es evidencia, no
fuente de datos.

## Qué estás juzgando, exactamente

**Si la ESTRUCTURA del SQL permite que la duplicación de filas infle un número.**

No si de hecho infla: eso depende de los datos y se mide aparte, corriendo la query.
Tampoco si el query contesta bien la pregunta: no sabes cuál era la pregunta, y es a
propósito.

Fan-out es una agregación que cae sobre una columna del lado "uno" de un join
uno-a-muchos. El join replica esa fila una vez por cada fila del lado "muchos", y la
agregación suma el mismo valor varias veces.

Las dos puertas ya medidas en la rebanada 2, como calibración:

| Puerta | Forma | Efecto medido |
|---|---|---|
| `communities.budget_usd` (Q4) | `SUM` sobre el lado "uno" de un join a `homes` | $14,388,050,000 contra $348,500,000 reales |
| `financials` (Q5) | tabla colgada de un join sin relación de grano real; cada casa duplicada una vez por año fiscal | conteo 102/104 contra 51/52 reales |

**El fan-out no depende de que la columna inflada sea `budget_usd`.** Cualquier tabla
colgada de un join sin relación de grano real multiplica todo lo que esté del otro
lado.

---

## Las cuatro etiquetas

| Etiqueta | Cuándo |
|---|---|
| `shape_present` | Hay join **más** agregado tal que la duplicación **PODRÍA** inflar un número. No afirma que pase, solo que la estructura lo permite. |
| `shape_absent` | La estructura no lo permite: sin join, o agregado inmune, o el CTE pre-agrega bien. |
| `out_of_scope` | Self join, window function, `UNION`/`INTERSECT`/`EXCEPT`, join que no sigue una FK declarada, o columna ambigua. |
| `unsure` | No se puede decidir desde el SQL. **Respuesta válida, no un fracaso.** |

### Por qué estas cuatro y no los veredictos del detector

El detector emite cinco veredictos —`inflated`, `shape_no_inflation`,
`no_contributing_rows`, `clean`, `not_analyzed`— y **ninguno coincide con estas
cuatro etiquetas. Cero tokens compartidos, a propósito.**

Tres de esos cinco **no son determinables desde el SQL**: `inflated` y
`shape_no_inflation` exigen el multiplicador medido, y `no_contributing_rows` exige
`COUNT(T.rowid)` sobre la base. Tú estás etiquetando a ciegas, sin correr nada.

Los casos A2 y B1 del set adversario son la demostración: SQL casi idéntico,
veredictos distintos, y **lo único que los separa es el multiplicador medido.** Si
etiquetaras `inflated` adivinando la cardinalidad, la etiqueta dejaría de ser
independiente de lo que el detector va a medir, y comparar detector contra etiqueta
ya no significaría nada.

Los nombres no se comparten para que nadie compare etiqueta contra veredicto con
`==` y parezca que funciona. **La adjudicación entre los dos vocabularios está
pre-registrada en `docs/ROADMAP.md`, escrita antes de que existiera una sola
etiqueta.**

---

## Reglas que no dependen de juicio

- Cualquier agregado con `DISTINCT` es **inmune**. También `MAX` y `MIN`. Medido:
  duplicar filas no movió ninguno de los tres.
- Sensibles a duplicación: `SUM`, `AVG`, `COUNT` sin DISTINCT, `TOTAL`.
- Una query **sin agregados** no tiene forma: va `shape_absent`.
- `shape_present` exige **las dos cosas juntas**: la estructura de joins **y** un
  agregado sensible sobre una columna afectada. La estructura sola no basta.
- Un CTE que pre-agrega a **una fila por llave** no duplica. Uno que no pre-agrega,
  sí.

## Los campos de cada bloque

```
LABEL:        una de las cuatro. Obligatoria.
SHAPE:        opcional, solo para shape_present.
RECONOCIDA:   `si` o vacía.
NOTA:         texto libre.
```

**`SHAPE:` es opcional y déjala vacía sin culpa.** Nombrar `fan_trap` contra
`chasm_trap` es un segundo juicio que puede fallar independiente del primero, y el
primario es el binario. Los valores son `fan_trap` (se agrega una columna del lado
"uno" tras unir al "muchos"), `chasm_trap` (dos ramas uno-a-muchos desde un ancestro
común, unidas entre sí, **y las ramas pueden tener más de un salto**) y `unexplained`
(hay estructura duplicadora pero no encaja limpio en ninguna).

**`RECONOCIDA: si`** si reconoces la query de nuestras conversaciones. No descarta el
caso: se reporta aparte, porque el ciego sobre esa entrada ya no vale, y eso es un
dato sobre la etiqueta y no un defecto de ella.

Valida con:

```
uv run python evals/gold/validate_labels.py evals/gold/worksheet_dev.md
```

Reporta y no arregla nada. Cualquier línea con forma `PALABRA:` que no reconozca la
señala: un `RECONOCIDO:` mal tecleado tiene que ser visible.

---

## Reglas de procedimiento

1. **Ciego.** El etiquetador no ve la config que produjo el SQL, ni la pregunta, ni
   el resultado ejecutado, ni el `row_count`, ni el id del corpus.

   **El ciego es parcial y depende de disciplina.** Los literales delatan la config a
   quien conozca el proyecto: `'Lennar'` solo existe en una y `'Lennar Corporation'`
   solo en la otra. Y `worksheet_keymap.json` lo deshace con un `cat`. Si alguna vez
   se abre, **se dice en voz alta y se marca el ciego como quemado**: uno roto y
   reportado sigue siendo evidencia de algo, uno roto en silencio no.
2. **Criterios, luego etiquetas, luego detector.** En ese orden y en commits
   separados. El orden de los commits es la evidencia de que no se etiquetó mirando
   el output.
3. **Las etiquetas viven en estas worksheets, no en archivos aparte.** Se llenan en
   su lugar, sobre las líneas `LABEL:` que ya están vacías.

   La razón es la evidencia: las worksheets vacías están congeladas en la historia de
   git, así que **el diff del commit de etiquetas muestra exactamente lo que
   agregaste contra el papel en blanco.** Eso prueba que no se etiquetó mirando el
   output del detector mejor que dos archivos que hay que cotejar.

   **En cuanto escribas una etiqueta, ese archivo queda congelado en forma dura**,
   porque a partir de ahí es una medición. Una corrección va como **nota fechada**,
   nunca como reescritura.

   `make_worksheets_20260729.py` se niega a regenerar una worksheet que ya tenga
   alguna línea `LABEL:` con valor. No depende de que te acuerdes.
4. **Nada que haga match con `evals/gold/*holdout*` se lee, se abre ni entra a la
   construcción del detector hasta la etapa 4. Aplica a archivos que todavía no
   existen. Si se abre alguno antes, se dice en voz alta y el holdout queda
   quemado.**

   Por patrón y no por nombre: un archivo que aún no existe no se puede proteger por
   nombre. Misma redacción en `docs/ROADMAP.md` y en `CLAUDE.md`.
5. **La procedencia no se pierde.** Cada entrada del corpus trae `sources[]` con
   archivo, config, pregunta y número de corrida.
6. **Un desacuerdo se registra, no se promedia.** Si dos etiquetadores discrepan, las
   dos etiquetas quedan y la discrepancia es el dato.
