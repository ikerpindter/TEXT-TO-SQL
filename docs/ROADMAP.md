# Roadmap

Lectura previa obligatoria antes de tocar nada del repo.

## La regla del holdout

**Nada que haga match con `evals/gold/*holdout*` se lee, se abre ni entra a la
construcción del detector hasta la etapa 4. Aplica a archivos que todavía no existen.
Si se abre alguno antes, se dice en voz alta y el holdout queda quemado.**

**Por patrón y no por nombre**, porque un archivo que aún no existe no se puede
proteger por nombre, y ése es justamente el próximo que se va a crear: el de las
etiquetas del holdout. Una regla que nombra `worksheet_holdout.md` deja de cubrir el
día que aparece cualquier otro artefacto del holdout.

Va aquí, en un archivo trackeado, porque hasta hoy vivía solo en `CLAUDE.md`, que
está en `.gitignore`: **el guardrail más importante del proyecto era el único que no
sobrevivía a un clone limpio.** Sigue también en `CLAUDE.md` y en
`evals/gold/LABELING_CRITERIA.md`, con la misma redacción en los tres.

Cobertura del patrón, medida el 29 de julio de 2026 con `pathlib.glob`, `fnmatch` y
el glob del shell, los tres coincidiendo:

| | |
|---|---|
| Cubre hoy | `evals/gold/worksheet_holdout.md` |
| Cubriría | `labels_holdout.md`, `holdout_labels.md`, `fanout_labels_holdout.md` |
| **No** cubre, y así debe ser | `worksheet_dev.md`, `labels_dev.md`, `split_assignment.json`, `worksheet_keymap.json` |

### Las etiquetas viven en las worksheets

**No hay archivo de etiquetas aparte.** `worksheet_dev.md` y `worksheet_holdout.md`
se llenan en su lugar, sobre las líneas `LABEL:` que ya están vacías.

La razón es la evidencia: las worksheets vacías están congeladas en la historia, así
que **el diff del commit de etiquetas muestra exactamente lo que se agregó contra el
papel en blanco**, con fecha y sin nada alrededor. Eso prueba que no se etiquetó
mirando el output del detector mejor que dos archivos que hay que cotejar a mano.

**En cuanto haya una etiqueta escrita, ese archivo queda congelado en forma dura**,
porque a partir de ahí es una medición. Una corrección va como **nota fechada**,
nunca como reescritura. Es el mismo protocolo de `evals/results/`.

Y no depende de que alguien se acuerde:
`evals/gold/make_worksheets_20260729.py` **se niega a escribir** —exit 2, con
mensaje— si el destino ya tiene alguna línea `LABEL:` con valor. Verificado el
29 de julio de 2026 escribiendo una etiqueta de prueba y confirmando la negativa.

No hay nada que la haga cumplir. Es una promesa, igual que el ciego de las
worksheets, y por eso la segunda mitad de la regla importa tanto como la primera: **un
holdout abierto y reportado sigue siendo evidencia de algo; uno abierto en silencio
no.**

## Orden de rebanadas

Actualizado tras cerrar la rebanada 2.

1. **Esqueleto.** CERRADA. Línea base congelada en
   [`evals/results/baseline_ddl_only.md`](../evals/results/baseline_ddl_only.md).
2. **Inyección de valores de columnas de baja cardinalidad al prompt.** CERRADA.
   Medida con N=5 y dos brazos:
   [`evals/results/ddl_only_n5.md`](../evals/results/ddl_only_n5.md) (control) y
   [`evals/results/values_text_maxcard20_n5.md`](../evals/results/values_text_maxcard20_n5.md)
   (experimental).
3. **Detección de fan-out.** Redefinida tras la rebanada 2. Antes decía
   "guardrails" y la pieza central era validación de esquema; **se descartó con
   evidencia**. Ver abajo.
4. **Eval harness** con gold set y N.
5. **Ataques a escala.**
6. **Conectar como tool del agente.**

### Resultado de la rebanada 2

**Las fallas ruidosas se fueron a cero. Las silenciosas se quintuplicaron.**

| Por SQL distinto | DDL puro | Con valores |
|---|---|---|
| Correctas | 0 / 25 | **8 / 24** |
| Ruidosas | 22 / 25 | **0 / 24** |
| Silenciosas | 3 / 25 | **16 / 24** |

**Estas proporciones son medición interna y no salen del repo.** Ver
[Para la rebanada 4](#5-las-proporciones-no-se-firman-hasta-que-haya-scoring-automático).

La inyección hizo lo que tenía que hacer: el 80% de las consultas ya no muere
adivinando strings. Y por eso mismo ahora llegan hasta el final, se topan con
las trampas que nunca habían tocado, y devuelven tablas de aspecto profesional
con cifras infladas 41x.

Q4 es la demostración limpia: misma pregunta, misma base, mismo modelo, lo
único que cambió fue el bloque de valores, y el resultado pasó de `NULL` (se
delata solo) a **$14,388,050,000** contra los $348,500,000 reales (no se delata
nunca). 5 de 5 corridas en cada brazo.

Dos cosas que la rebanada 2 **no** arregló, y hay que tenerlas presentes al
diseñar la 3:

- **Inyectar un valor no hace que se use.** Es la lección central de la
  rebanada y tiene su propia sección abajo.
- **Las fallas se volvieron consistentes.** En DDL puro, Q5 se repartía entre
  silenciosa y ruidosa según una mayúscula en un literal. Con los valores
  dados, cada pregunta cae siempre en la misma casilla. Un error reproducible
  es más peligroso que uno intermitente: pasa cualquier prueba de humo que se
  corra dos veces.

### Por qué se adelantó la rebanada 2

Originalmente los guardrails iban antes. Se recorrieron.

En la línea base, **el 80% de las consultas murió adivinando literales de
texto antes de llegar a las trampas del dataset**. El modelo recibe DDL puro:
no tiene forma de saber que `status` vale `closed`/`backlog`/`cancelled`/
`available`, que `state` guarda `'TX'` y no `'Texas'`, ni cuál es el nombre
legal de cada compañía.

Las trampas #1, #3 y #7 solo se pudieron confirmar corriendo las consultas del
modelo con los literales corregidos a mano. Mientras eso siga así, un gold set
mide capacidad de adivinar strings, no capacidad de razonar sobre un esquema.

**Sin la rebanada 2, no se puede medir nada.**

## Lección de la rebanada 2: inyectar no es usar

**Conocer los literales y razonar sobre el esquema son dos problemas distintos.
El segundo no se resuelve dando más contexto.**

Dos columnas entraron completas al prompt de la config B, las dos son la única
fuente en el esquema de la información que hacía falta, y las dos se ignoraron:

| Columna | Valores en el prompt | Corridas que la usaron |
|---|---|---|
| `companies.fiscal_year_end` | `'09-30'`, `'11-30'` | **0 de 5** en Q3 (0 de 25 en toda la config) |
| `financials.unit_scale` | `'millions'`, `'thousands'` | **0 de 5** en Q5 (0 de 25 en toda la config) |

`fiscal_year_end` es el único lugar del esquema donde existe el cierre fiscal de
cada compañía, y estaba listado. Cuatro de las cinco corridas de Q3 no aplicaron
ninguna ventana temporal y la quinta eligió año calendario. `unit_scale` estaba
listado y ninguna corrida de Q5 normalizó, así que las dos escalas salieron lado
a lado leyéndose como 1,120x de diferencia cuando la real es 1.12x.

La rebanada 2 movió la aguja en las trampas de **literales** (#4 status, los
nombres legales, `'TX'`) y no la movió ni un milímetro en las de
**razonamiento** (#1 escalas, #3 calendario fiscal, #7 fan-out).

Consecuencia de diseño: **el arreglo de la rebanada 3 no puede ser más
contexto.** Si poner el dato en el prompt bastara, la #1 y la #3 ya estarían
resueltas. Tiene que ser algo que inspeccione el SQL producido.

## La rebanada 3 es detección de fan-out, no validación de esquema

### La validación de esquema se descarta, y está medido dos veces

**El guardrail que el plan original ponía como pieza central caza cero fallas
reales de este sistema.**

| Rebanada | Falla | ¿La caza una validación de esquema? |
|---|---|---|
| 1 | `WHERE name IN ('Lennar')` | **No.** La tabla existe, la columna existe, el tipo es correcto. **El valor es lo que no existe.** Las cinco consultas de la línea base habrían pasado. |
| 2 | Las 16 fallas silenciosas | **No, ninguna.** Pasarían completas. |

`SUM(budget_usd)` sobre un join con `homes` es SQL perfectamente válido: las
tablas existen, las columnas existen, los tipos cuadran. Lo que está mal es **el
grano de la agregación**, y eso una validación de nombres y tipos no lo ve.

Son dos problemas distintos y no hay que confundirlos. Un verificador de
columnas referenciadas es útil contra otra clase de falla —SQL que alucina una
tabla o una columna— que este sistema no ha producido ni una vez en 55 llamadas
medidas. **Se descarta por falta de blanco, no por dificultad.**

### Qué sí es la rebanada 3

Detección de fan-out, porque **es el modo de falla dominante** y ya pegó dos
veces por puertas distintas:

| Puerta | Cómo pegó | Corridas (config B) |
|---|---|---|
| `communities.budget_usd` (Q4) | `SUM` sobre el lado "uno" de un join a `homes`. **$14,388,050,000 contra $348,500,000 reales, inflado 41.3x** | **5 de 5** |
| `financials` (Q5) | Tabla colgada de un join sin relación de grano real. Cada casa duplicada una vez por año fiscal | **5 de 5** tienen el artefacto; en 1 de 5 infló el conteo a 102/104 contra 51/52 reales |

La lección de la #7 vale repetirla: **el fan-out no depende de que la columna
inflada sea `budget_usd`.** Cualquier tabla colgada de un join sin relación de
grano real multiplica todo lo que esté del otro lado. `financials` es
especialmente peligrosa porque tiene varias filas por compañía y se ve como una
tabla de atributos.

**Es detectable de forma determinista**, desde el texto del SQL más la
estructura de llaves foráneas. No hace falta llamar al modelo, no hace falta
gold set, y no hace falta conocer la respuesta correcta: que una agregación caiga
sobre una columna del lado "uno" de un join uno-a-muchos es una propiedad
sintáctica del query contra el catálogo.

**Marca y explica. No bloquea.** El guardrail emite una advertencia que dice qué
columna se está agregando, por qué join se replicó y cuál es el factor esperado.
Bloquear convertiría una falla silenciosa en una ruidosa, que es mejor, pero
también mataría consultas legítimas —un `SUM(DISTINCT)` o una subconsulta bien
armada— y la rebanada 2 ya mostró que este sistema tiene bastantes formas de
tener razón como para no estrangularlas de entrada.

### Las etapas de la rebanada 3

| Etapa | Qué | Estado |
|---|---|---|
| 1 | Corpus congelado, pin de sqlglot, criterios de etiquetado | **CERRADA** (`8e140b4`, `e111d8f`) |
| 1b | Set adversario escrito a mano, worksheets ciegas de la unión, validador | **CERRADA** (`6712d32`, `e2ba6c2`) |
| 2 | Iker etiqueta a mano, solo la mitad dev | **SALTADA.** Ver la nota de abajo |
| 3 | Detector construido y corrido contra dev | |
| 4 | Se abre el holdout, una sola vez | |

El invariante que no se negocia: **worksheets y etiquetas se commitean antes de que
exista una sola línea del detector.** El orden de los commits es la evidencia de
que no se etiquetó mirando el output.

> **Nota 2026-07-30: el detector se escribió ANTES de que existieran las etiquetas.
> El invariante de arriba queda QUEMADO, y se reporta en lugar de silenciarse.**
>
> Al abrir la etapa 3, `worksheet_dev.md` tenía sus 25 líneas `LABEL:` vacías y no
> existía ningún commit de etiquetas: **la etapa 2 no ocurrió.** Se decidió construir
> el detector de todos modos, a sabiendas.
>
> **Qué se pierde, exactamente.** El orden de los commits era la evidencia de que no
> se etiquetó mirando el output del detector. A partir del primer commit de la etapa 3
> esa evidencia ya no se puede reconstruir: cualquier etiqueta futura se escribe con el
> detector ya en el árbol, y **nada en el repo puede probar que su output no estuvo
> disponible.**
>
> **Qué sobrevive.** Las worksheets vacías siguen congeladas en `e2ba6c2`, así que el
> diff del commit de etiquetas seguirá mostrando exactamente lo que se agregó contra el
> papel en blanco. Y `make_worksheets_20260729.py` sigue negándose —exit 2— a regenerar
> una worksheet que ya tenga etiquetas. Lo que se rompió es la prueba, no
> necesariamente el hecho.
>
> **Consecuencia dura para la etapa 4.** El holdout ya solo puede cachar overfitting
> grueso del detector contra el corpus; **no** puede seguir sosteniendo la afirmación
> "las etiquetas son independientes del detector", porque esa afirmación descansaba en
> el orden y el orden se rompió aquí. Cualquier conteo de acuerdo que se publique
> después lleva esta nota pegada.
>
> Se anota por la misma razón que el ciego y el holdout: **uno roto y reportado sigue
> siendo evidencia de algo; uno roto en silencio no.**
>
> **El holdout NO se tocó.** Nada que haga match con `evals/gold/*holdout*` se leyó ni
> se abrió durante la etapa 3. Esa regla sigue intacta.

### El diseño del detector

Especificado el 29 de julio de 2026, antes de escribir código. La fuente larga
vive en `docs/rebanada-3-especificacion.md`.

#### Los cinco veredictos

Cada SQL analizado recibe **exactamente un** veredicto. Se evalúan **en este orden**
y el primero que aplica gana.

| Orden | Veredicto | Cuándo |
|---|---|---|
| 1 | `not_analyzed` | El detector no pudo analizar la query. Siempre con `reason`. |
| 2 | `no_contributing_rows` | `COUNT(T.rowid) = 0`. El multiplicador es indefinido. |
| 3 | `clean` | Analizada, sin forma de fan-out presente. |
| 4 | `shape_no_inflation` | La forma está presente, el multiplicador medido es 1.0. |
| 5 | `inflated` | La forma está presente y el multiplicador medido es mayor a 1.0. |

> **Corrección 2026-07-29: `no_rows` se renombra a `no_contributing_rows`, y el
> veredicto conserva sus `findings`.**
>
> El nombre viejo describía dos casos y mentía sobre diecisiete. Medido: **19 de 43
> entradas medibles tienen la fuente de filas vacía, y solo 2 devuelven 0 filas al
> usuario.** Las otras 17 **sí devuelven filas** —un agregado desnudo sobre cero
> filas emite exactamente una fila, con un `0` o un `NULL` adentro— así que
> llamarlas "sin filas" es falso desde el punto de vista de quien lee el resultado.
>
> Tres cambios que vienen con el renombre:
>
> 1. **`findings` va poblado.** La especificación solo dice que `findings` va vacío
>    en `clean` y en `not_analyzed`, así que un `no_contributing_rows` lleva su forma
>    detectada estáticamente con `row_multiplier: null`. Sin esto el guardrail se
>    quedaría callado en el 44% del corpus, incluidas las entradas de Q4 con el
>    fan-out de `budget_usd`.
> 2. **Campo `subcase`** que separa los dos. Ver la corrección de nombres abajo.
> 3. **La precedencia pasa a ser POR HALLAZGO, no por query.** Si un hallazgo es
>    medible y otro no, el veredicto sale del medible. `no_contributing_rows` solo
>    gana cuando **ninguno** lo es.

- **`not_analyzed` va primero a propósito.** Si no podemos analizar, lo decimos y
  paramos. No se degrada a `clean`, que afirmaría algo que no verificamos.
- **`no_contributing_rows` va antes que `clean`** porque el multiplicador no se puede
  calcular sobre cero filas. "Estaba rota por otra razón" y "no hubo inflación" son
  hechos distintos y no se colapsan. Nunca se reporta `shape_no_inflation` sobre una
  query cuya `T` no aporta filas.
- Si hay varios hallazgos en la misma query, **el veredicto es el peor caso.** Un
  solo hallazgo `inflated` hace que la query sea `inflated`.

> **Corrección 2026-07-29: los subcasos de `no_contributing_rows` se nombran por la
> FUENTE, no por la salida.**
>
> | Subcase | Definición |
> |---|---|
> | `empty_source` | `COUNT(*)` de la fuente de filas es 0 |
> | `t_absent` | `COUNT(*)` de la fuente es mayor a 0 **y** `COUNT(T.rowid)` es 0 |
>
> Los nombres viejos —`query_sin_filas` y `query_con_filas`— estaban tomados de las
> filas de la **salida**, y ahí estaba el error: un agregado desnudo sobre cero filas
> emite exactamente una fila, así que "query con filas" describía a los dos casos y
> los colapsaba. Por la fuente son distintos.
>
> **No hizo falta agregar ningún caso.** D1 es `empty_source` (fuente 0 filas) y D2
> es `t_absent` (fuente 794, `T` aporta 0). El hueco de cobertura que se creía tener
> **no existía**: era un error de nomenclatura disfrazado de hueco.
>
> **Dato de producto, y pide render distinto:** D1 le muestra al usuario un `NULL` y
> D2 le muestra un **`0`**. El `0` es el peligroso, porque **parece una respuesta**:
> "cero casas en backlog" se lee como un hecho verificado. Un `NULL` al menos se ve
> raro y hace que alguien pregunte.

> **`clean` significa "sin duplicación medida", NO "la query es correcta".**
>
> Este guardrail mide **una sola cosa**: duplicación de filas por joins. Las trampas
> de `unit_scale` y de año fiscal producen números mal **con veredicto `clean`**, y
> eso es el comportamiento correcto, no un hoyo.
>
> Importa sobre todo para la **rebanada 6**, donde esto lo consume un agente: un
> agente que lea `clean` como "confía en el número" va a confiar en números que este
> detector nunca miró. El campo dice qué se midió, no que el resultado sea bueno.

> **La pasada estática de forma corre SIEMPRE, aunque la dinámica no encuentre nada.**
>
> Es lo único que hace emitible a `shape_no_inflation`. Si el hallazgo solo se creara
> cuando `row_multiplier > 1`, ese veredicto sería **inemitible por construcción** y
> los casos con forma presente y multiplicador 1.0 colapsarían a `clean`.
>
> Verificado el 2026-07-29 sobre el par A2 / B1: la estructura de joins es idéntica
> salvo un predicado extra en el `ON`, y el multiplicador cae de 2.0 a 1.0 **solo por
> la cardinalidad de los datos**. La forma es una propiedad estática del árbol; el
> multiplicador es una medición sobre la base. Son dos pasadas y la primera no puede
> depender de la segunda.
- **"Forma presente" significa las dos cosas juntas:** la estructura de joins **y**
  un agregado sensible a duplicación sobre una columna afectada. Una query sin
  agregados no tiene forma, va `clean`.

#### El multiplicador

```
multiplier = COUNT(T.pk) / COUNT(DISTINCT T.pk)
```

Sobre la misma fuente de filas de la query original (FROM, JOINs y WHERE, sin
ORDER BY ni LIMIT), donde `T` es la tabla cuya columna se está agregando y `pk` su
llave primaria.

Consecuencia de la fórmula: **`no_rows` se define como `COUNT(T.pk) = 0`.**

Costo: dos queries de SQLite por hallazgo, sobre la conexión read-only que ya
existe. Cero llamadas a API.

> **Corrección 2026-07-29.** El diseño original decía `COUNT(*)` en el numerador y
> **estaba mal**. Con `LEFT JOIN` las filas sin match traen `T.pk` en NULL:
> `COUNT(*)` las cuenta y `COUNT(DISTINCT T.pk)` no, así que el multiplicador salía
> **inflado sin que existiera inflación** —un falso `inflated`, que es justo el
> error que este guardrail no se puede permitir, porque enseña a desconfiar de las
> advertencias. `COUNT(T.pk)` excluye NULLs igual que el denominador, y queda
> correcta para INNER y para LEFT.
>
> **Medida el 2026-07-29:** la corrección es **correcta e inerte en el corpus de la
> etapa 1.** Cero de los pares medidos difieren, porque esta base no tiene huecos de
> FK —0 comunidades sin casas, 0 compañías sin comunidades, 0 sin `financials`— así
> que ningún `LEFT JOIN` sobre FKs declaradas produce `T.pk` NULL. Se queda por la
> decisión pre-registrada 2. Forzando el hueco con un `ON` que no matchea, la
> fórmula original **divide por cero y truena** y la corregida da indefinido, o sea
> `no_rows`: la corrección evita un crash, no solo un falso `inflated`. Detalle en
> `evals/results/corpus_verification.md`.

> **Corrección 2026-07-29: el multiplicador no es el ratio de valor.** El JSON de
> ejemplo de la especificación pone `"multiplier": 41.3` junto a
> `reported_value: 14388050000.0` y `deduplicated_value: 348500000.0`, dando a
> entender que el multiplicador es el cociente de esos dos. **No lo es.** Medido
> sobre ese mismo caso:
>
> - Multiplicador de **filas**, que es lo que da esta fórmula: `400/10` = **40.0**
> - Ratio de **valor**, `reportado/correcto`: `14,388,050,000 / 348,500,000` = **41.285653**
>
> Difieren porque el ratio de valor está **ponderado por `budget_usd`**: cada
> comunidad aporta su presupuesto por *su propio* número de casas, y los
> presupuestos no son iguales. Coincidirían solo si lo fueran.
>
> **Consecuencia dura: `deduplicated_value` no se puede derivar dividiendo por el
> multiplicador.** `14,388,050,000 / 40.0` da `359,701,250`, contra `348,500,000`
> reales: **3.21% de error** presentado como cifra exacta. Por eso la
> especificación dice que no se aproxima, y ahora hay número en lugar de intuición.
>
> Los dos sirven y miden cosas distintas: el multiplicador de filas **prueba que hay
> duplicación** y es estructural; el ratio de valor **dice cuánto se infló esta
> cifra** y es lo que el render de la CLI quiere nombrar. El `41.3x` de la tabla de
> las dos formas es correcto **como ratio de valor** y así se lee.

#### Dos campos separados que nunca se colapsan

Resolución de la corrección de arriba. Definido el 29 de julio de 2026 en
`docs/rebanada-3-addendum-01.md`.

| Campo | Fórmula | Cuándo existe |
|---|---|---|
| `row_multiplier` | `COUNT(T.rowid) / COUNT(DISTINCT T.rowid)` | Es el factor de duplicación de **filas**. Calculable solo si `T` es tabla base |
| `value_inflation` | `reported_value / deduplicated_value` | **Solo** en el caso angosto donde `deduplicated_value` existe. `null` en cualquier otro caso |

> **Corrección 2026-07-30: `value_inflation` es EXACTAMENTE `row_multiplier` cuando
> el agregado es `COUNT` de la PK o del `rowid` de la tabla afectada.**
>
> Esta tabla decía que `value_inflation` existe **solo** donde exista
> `deduplicated_value`, y dos párrafos más abajo el propio documento ya decía que
> para `COUNT` de la PK de la tabla afectada el multiplicador **sí** es el factor de
> inflación, "exacto por definición". Las dos frases no podían ser ciertas a la vez
> y la etapa 3 se construyó siguiendo la primera, así que A2 salía con
> `value_inflation: null` teniendo un factor exacto disponible.
>
> **Gana la aritmética, porque no depende de la forma ni de los datos:** sobre la
> fuente duplicada `COUNT(T.pk)` cuenta las filas que aportan, deduplicado cuenta
> las filas distintas, y el cociente **es** el multiplicador. Aplica igual a
> `fan_trap`, a `chasm_trap` y a `unexplained`.
>
> Exige que el agregado toque **una sola columna de una sola tabla**, y que esa
> columna sea el `rowid` o una PK de una sola columna. `COUNT(T.x)` de una columna
> cualquiera **no** califica aunque hoy diera el mismo número: si `x` admite nulos,
> numerador y denominador dejan de encogerse a la par.
>
> **Verificado el 2026-07-30 y sin desacuerdos:** en todos los hallazgos donde el
> atajo aritmético y la sonda medida existían a la vez, dieron el mismo número.
> A2 pasa de `null` a **2.0**.

> **Corrección 2026-07-30: el caso angosto de `deduplicated_value` estaba
> demasiado angosto. Disparó 0 de 25 veces.**
>
> Las condiciones eran cuatro: exactamente un agregado marcado, forma `fan_trap`,
> `SUM` o `COUNT` sobre una columna del lado "uno", y sin `GROUP BY`. Corrido sobre
> las 49 entradas del corpus, **el campo salió `null` en los 25 hallazgos**. Una
> regla que nunca aplica no protege de nada: solo hace que el guardrail se calle
> justo donde tenía el dato más útil.
>
> **Se quitan dos condiciones.** Quedan **sin `GROUP BY`** y **`T` es tabla base**.
> Se van "forma `fan_trap`" —la aritmética del deduplicado no depende de qué forma
> explique la duplicación— y "exactamente un agregado" —cada hallazgo se deduplica
> por su cuenta, y varios agregados no se estorban.
>
> `GROUP BY` se queda fuera porque ahí "el valor reportado" no es un número, es una
> columna de números, y el par reportado/deduplicado deja de tener sentido.
>
> **Lo que NO cambia, y es el principio entero: `deduplicated_value` se recalcula
> contra la base, nunca se aproxima dividiendo.** Ensanchar *cuándo* se mide no es
> aflojar *cómo* se mide.
>
> Guard nuevo que vino con el ensanche: la sonda de deduplicado cuenta sus propias
> filas y las compara contra `COUNT(DISTINCT T.rowid)`. Si el valor agregado **no
> está determinado por la fila de `T`** —porque la expresión mira además otra tabla
> que se duplica— el `DISTINCT` deja más de una fila por rowid y el resultado sería
> una cifra torcida. En ese caso el campo se queda en `null`.
>
> **Medido el 2026-07-30: pasa de 0 a 6 de 25 hallazgos.** Y entre esos 6 están las
> ids 40, 41 y 43, que reproducen desde cero la cifra que este proyecto viene
> citando desde la rebanada 2: `reported_value` 14,388,050,000 contra
> `deduplicated_value` 348,500,000, `value_inflation` **41.285653**.

**`value_inflation` no se aproxima nunca con `row_multiplier`.** Medido: dividir por
`row_multiplier` da 359,701,250 contra 348,500,000 reales, 3.21% de error en una
cifra que se vería exacta.

Cuándo sí coinciden, y es el único caso:

| Agregado afectado | ¿`row_multiplier` **es** el factor de inflación? |
|---|---|
| `COUNT` de la PK de la tabla afectada | **Sí**, exacto por definición |
| `SUM`, `AVG`, `TOTAL` de cualquier otra columna | **No.** Solo indica el orden de la duplicación |

Coinciden solo si la columna agregada no correlaciona con el conteo del fan-out, y
en datos reales casi siempre correlaciona.

**Qué cambia en el render.** Cuando existe `value_inflation`, se cita ése y se dice
de dónde sale. Cuando no existe, el texto habla de la duplicación y **nunca afirma
por cuánto está mal el número**:

- Va: *"el presupuesto se sumó una vez por cada casa de la comunidad, alrededor de 40
  casas por comunidad"*.
- No va: *"el presupuesto está inflado 40x"*.

**Ésta es la distinción que es el punto del proyecto.** Un guardrail que reporta un
factor de inflación que no midió está fabricando precisión, que es exactamente la
falla que le medimos al modelo en la rebanada 2.

#### Nota de lenguaje: `inflated` para `AVG`

`inflated` significa **"al menos un agregado está afectado por duplicación de
filas"**. Para `SUM` y `COUNT` el efecto siempre va hacia arriba. Para `AVG` puede ir
en **cualquier dirección**, porque el resultado se vuelve un promedio ponderado.

El veredicto no se renombra, pero **el render para `AVG` dice "distorsionado", no
"inflado"**.

Medido el 2026-07-29 sobre `AVG(c.budget_usd)` con el join a `homes`: el promedio
**bajó**, de 37,162,500 a 37,100,377.83. La dirección no es teórica, en esta base va
para abajo.

#### Corrección: tercera versión de la fórmula, `rowid` en vez de PK

`COUNT(*)` → `COUNT(T.pk)` → **`COUNT(T.rowid)`**.

> **Corrección 2026-07-29.** `COUNT(DISTINCT T.pk)` **es inexpresable en SQLite
> cuando la PK es compuesta**, y `financials` la tiene: `(company_id, fiscal_year)`.
>
> ```
> SELECT COUNT(DISTINCT company_id, fiscal_year) FROM financials
>   -> OperationalError: wrong number of arguments to function COUNT()
> ```
>
> No da un número raro: **no compila.** Y no es hipotético: **5 de las 49 entradas
> agregan una columna de `financials`** (ids 1, 4, 24, 26, 47), o sea el 10% del
> corpus.
>
> **La PK era un proxy de identidad de fila, y era el proxy equivocado.** `rowid` es
> la identidad de fila directamente. Verificado: en las tres tablas de PK simple
> `rowid` **es** la columna `id`, con cero discrepancias, así que el cambio no altera
> ningún número ya medido. Sobre `financials` la fórmula nueva da
> `COUNT(T.rowid)=40 / COUNT(DISTINCT T.rowid)=4` = **10.0**.
>
> **Las dos correcciones de esta fórmula salieron de medición, no de razonamiento.**
> La primera apareció al pensar en `LEFT JOIN`; la segunda apareció al leer
> `PRAGMA table_info`. Ninguna se habría encontrado releyendo la especificación.

**Tres guards obligatorios antes de usar `rowid`:**

1. **`T` tiene que ser tabla base.** Si no lo es, `not_analyzed` con razón. **Y hay
   que verificarlo en el AST**, porque SQLite no ayuda:

   | `T` es… | `T.rowid` | |
   |---|---|---|
   | tabla base | funciona | correcto |
   | CTE | `OperationalError: no such column` | falla **ruidoso**, bien |
   | subconsulta derivada | **resuelve y devuelve `NULL` en cada fila** | falla **silencioso** |

   Medido sobre un derivado de 20 filas: `COUNT(t.rowid) = 0`. Eso es exactamente la
   condición de `no_contributing_rows`, así que una derivada quedaría **clasificada
   silenciosamente** como "T no aporta filas" teniendo filas. Probado con derivada
   simple, con `DISTINCT`, con `GROUP BY`, con `LIMIT` y con `UNION`: **las cinco
   devuelven NULL sin error.**

   **El guard, confirmado por medición:** `isinstance(scope.sources[nombre], exp.Table)`.

   **Cuántas veces pega hoy: cero.** Medido el 2026-07-29 sobre las 49:

   | | total | en dev |
   |---|---|---|
   | Con alguna fuente que no es tabla base (CTE o derivada) | 7 | 3 |
   | De esas, con fuente **derivada**, no CTE declarado | 5 | 2 |
   | **Con un agregado sobre columna de fuente no-base** ← el trap | **0** | 0 |

   O sea: el guard es **necesario pero latente**. Ninguna entrada del corpus real
   agrega sobre una columna que venga de un CTE o de una derivada; las 7 con fuentes
   no-base agregan siempre sobre columnas de tablas base. La id 17, que se citó antes
   como instancia viva del trap, **no lo es**: su `SUM` vive dentro de la subconsulta,
   donde la tabla sí es base, y afuera solo se selecciona la columna sin agregarla.
   El guard se implementa igual, porque el set adversario y la rebanada 4 sí pueden
   producirlo, pero no hay que esperar que dispare sobre este corpus.
2. **`WITHOUT ROWID` va a `not_analyzed`, ruidoso.** Medido: cero tablas
   `WITHOUT ROWID` en esta base, así que este guard **no tiene blanco hoy**.
3. **Ninguna columna puede llamarse `rowid`, `oid` ni `_rowid_`**, o lo sombrea.
   Medido: cero columnas así en las cuatro tablas.

#### La brecha entre los dos campos cambia de signo

| Caso | `row_multiplier` | `value_inflation` | El multiplicador queda… |
|---|---|---|---|
| Q4, config B | 40.0 | 41.285653 | **por debajo** |
| A6, el gemelo de C2 | 39.7 | 39.6336 | **por encima** |

**No es cota superior ni inferior. Queda prohibido en el render cualquier "al menos
Nx" o "a lo mucho Nx".** El multiplicador de filas no acota el error del valor en
ninguna dirección: la relación depende de cómo correlacionen los valores de la
columna agregada con el grado de fan-out de cada fila, y esa correlación puede ir
para cualquier lado.

Ojo con el segundo caso: 39.7 contra 39.6336 son 0.17% de diferencia. **Que la brecha
sea chica es lo que la hace peligrosa**, porque invita a tratarlos como el mismo
número. En Q4 la brecha era 3.2% y saltaba a la vista.

#### Trampas de implementación medidas, para la etapa 3

- **`scope.sources` trae el alias Y el nombre del CTE como entradas separadas.**
  Medido sobre C2: `['c', 'p', 'per_comm']` son **3 entradas para 2 fuentes**.
  Recorrer `sources` sin deduplicar sondea el CTE dos veces.
- **La llave del `FROM` en `Select.args` es `from_`, con guion bajo.**
  `args.get("from")` devuelve `None` **en silencio**. El acceso canónico es
  `select.find(sqlglot.exp.From)`.
- **La raíz del árbol de un `UNION` es `exp.Union`, no `exp.Select`.** Un detector
  que asuma `Select` en la raíz falla antes de decidir nada.

#### Las dos formas

| Forma | Qué es | Caso medido |
|---|---|---|
| `fan_trap` | Se agrega una columna del lado "uno" después de unir al lado "muchos" | Q4, `budget_usd` inflado **41.3x** |
| `chasm_trap` | Dos ramas uno-a-muchos desde un ancestro común, unidas entre sí. Cada rama multiplica a la otra | Q5, casas por 2 años fiscales |

> **Corrección 2026-07-29.** El diseño original comparaba **hijos directos** de un
> ancestro común, y con eso **no caza Q5**, que es uno de los dos casos medidos.
> En este esquema `homes` no tiene FK directa a `companies`: llega vía
> `communities`. Las dos ramas de Q5 salen de `companies` con profundidades
> distintas —una a `financials` en un salto, otra a `homes` en dos, vía
> `communities`— así que **la búsqueda de ramas hermanas tiene que ser a cualquier
> profundidad.**
>
> Esto salió del dato de la etapa 1 de que el esquema tiene exactamente 3 FKs
> (`financials.company_id`, `communities.company_id`, `homes.community_id`): al
> escribirlas se ve que ninguna liga `homes` con `companies`.

#### Alcance de v1

**Dentro:**

- Un solo statement `SELECT`, con o sin CTEs, dialecto sqlite.
- Agregados sensibles a duplicación: `SUM`, `AVG`, `COUNT` sin DISTINCT, `TOTAL`.

  > **Reducción de alcance 2026-07-29: `GROUP_CONCAT` sale de la lista.** Razón:
  > **cero apariciones en 49 muestras de output real del modelo.** No hay blanco. Es
  > la lección 10 aplicada tal cual —se descarta por falta de blanco, no por
  > dificultad— igual que se descartó la validación de esquema. Si aparece en la
  > rebanada 4 o 5, se reintroduce **con su caso de prueba**.
  >
  > **`TOTAL` se queda.** Es el alias de `SUM` en SQLite y comparte camino de código,
  > pero necesita su propio assert: el caso A5 del set adversario existe para eso.
  > Verificado el 2026-07-29 que `TOTAL` y `SUM` dan el mismo valor sobre la fuente
  > duplicada.
- Dirección del join **solo desde FKs declaradas** (`PRAGMA foreign_key_list`). El
  lado "uno" es la tabla referenciada cuando la columna referenciada es PK o tiene
  índice UNIQUE. **Nunca se infiere de los datos.**
- Joins explícitos con `ON`, y joins por coma con igualdad en `WHERE`.
- Análisis por scope con `traverse_scope`, así que **un CTE que pre-agrega bien no
  se marca.**
- Las dos formas de arriba.

**Nunca se marcan, y no es una excepción afinada:**

- Cualquier agregado con `DISTINCT`.
- `MAX` y `MIN`.

Es aritmética, no criterio: duplicar filas no mueve el valor de un máximo ni de un
distinto. No es un hoyo del guardrail, porque no depende de juicio.

**Fuera de v1, van a `not_analyzed` con su `reason`:**

- Self joins.
- Window functions.
- `UNION`, `INTERSECT`, `EXCEPT`.
- Joins sobre columnas que no son una relación de FK declarada, por ejemplo unir
  por `name`.
- Subqueries correlacionadas en la lista del `SELECT`.
- Columnas que `qualify` no resuelve o declara ambiguas. Ya sabemos que lanza
  `OptimizeError`, así que **este camino falla ruidoso y eso está bien.**

**Dentro, pero reportado con salvedad:**

- **`GROUP BY`:** el multiplicador se calcula global sobre la fuente de filas, no
  por grupo. Se reporta con `multiplier_scope: "global"`. No va a `not_analyzed`.

  > **Ajuste de redacción 2026-07-29.** La versión anterior decía que un
  > multiplicador global mayor a 1 "ya prueba que existe duplicación", lo cual se
  > lee como más de lo que es. Preciso: prueba que **existe** duplicación **en algún
  > lugar del resultado**, no que **cada grupo** esté afectado.
  >
  > Suficiente para **marcar y explicar**. Insuficiente para **afirmar algo de una
  > fila específica del output**. Así se redacta el render: no se le dice al usuario
  > que la fila que está mirando está inflada, se le dice que el resultado contiene
  > duplicación.
- **`deduplicated_value`:** solo en el caso angosto —exactamente un agregado
  marcado, forma `fan_trap`, el agregado es `SUM` o `COUNT` sobre una columna de la
  tabla del lado "uno", y sin `GROUP BY`. En cualquier otro caso va `null`. **No se
  aproxima.**

#### Forma de la salida

Estructurado en el JSON de la corrida, más un render corto en la CLI. Los dos:
la rebanada 4 necesita scorear automático, y en la rebanada 6 esto lo consume un
agente, y un agente no lee prosa.

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

`reason` se llena **solo** cuando el veredicto es `not_analyzed`. `findings` va
vacío en `clean` y en `not_analyzed`.

**El render de la CLI nombra la consecuencia, no la mecánica.** Va "el presupuesto
se sumó una vez por cada casa de la comunidad, no una vez por comunidad,
multiplicador medido 41.3x". No va "fan-out detectado en el join". La respuesta se
sigue mostrando siempre: **marca y explica, no bloquea.** El `deduplicated_value`
se muestra etiquetado como diagnóstico, **nunca como la respuesta**.

Sin taxonomía de severidad en v1. El `shape` sí, porque el eval lo necesita.
Severidad no, porque no hay datos todavía para inventar los niveles.

### Etapa 1 de 4: congelar el corpus

Predicciones escritas **antes** de abrir `evals/runs/*.json`, para poder medir
después qué tan mal calibrado estaba el estimador.

Honestidad sobre la primera: **no es ciega.** Este mismo documento la filtra. La
línea de la validación de esquema dice "55 llamadas medidas" y la tabla de
fan-out reporta "5 de 5" corridas por pregunta, de donde el total sale por
aritmética: 5 preguntas × 5 corridas × 2 configs = 50 en `runs/`, más las 5 de la
línea base que viven en `results/`, y no en `runs/`. Las otras dos sí son ciegas:
nada en el ROADMAP dice cuánto colapsa el dedupe ni qué fracción parsea.

| # | Cantidad | Predicción | Rango | ¿Ciega? |
|---|---|---|---|---|
| 1 | SQL totales en `evals/runs/*.json` | **50** | 50 exacto | No, derivada del ROADMAP |
| 2 | Distintos tras dedupe por string con whitespace normalizado | **32** | 24–40 | Sí |
| 3 | De esos distintos, los que `sqlglot` parsea sin excepción | **32** (100%) | 30–32 | Sí |

Razonamiento de la #2: las dos puertas de fan-out pegaron "5 de 5", así que la
*forma* del query es muy estable dentro de cada pregunta. Pero identidad de
string exacto es más frágil que identidad de forma: alias, saltos de línea y
orden de columnas se mueven con el muestreo. Estimo 2–4 strings distintos por
cada par (pregunta, config), o sea ~3 × 5 × 2 ≈ 32.

Razonamiento de la #3: SQL generado por un modelo sobre un esquema de cuatro
tablas casi siempre es sintácticamente válido; el error de sintaxis no es el modo
de falla de este sistema, el grano de la agregación sí. El único camino realista
a una excepción es basura de formato que haya sobrevivido al pipeline —una cerca
de markdown, un prefacio en prosa— y eso sería un hallazgo sobre `generate.py`,
no sobre el modelo. Si fallan más de dos, el bug está en la extracción.

#### Resultado de las predicciones

Las predicciones de arriba no se editan. Esto es lo que salió.

| # | Predicción | Real | |
|---|---|---|---|
| 1 | 50 | **50** | acertada, pero no era ciega |
| 2 | 32 (rango 24–40) | **49** | **fallada, fuera de rango** |
| 3 | 32 de 32 (100%) | **49 de 49 (100%)** | acertada en tasa |

La #2 falló por el lado interesante: el estimador supuso que el string exacto
colapsaría ~36% del corpus y colapsó **1 de 50**. Y el número ya estaba medido en
este mismo documento, en "Agrupar por string exacto de SQL no sirve" —25/25
distintos en la config A, 24/25 en la B— así que la predicción no solo falló, falló
contra evidencia que el repo ya tenía escrita.

Dato nuevo que la rebanada 2 no había medido: **normalizar whitespace no colapsa
nada.** El único grupo repetido del corpus (id 32, config B, Q2, corridas 2 y 3)
es un duplicado byte-idéntico; su flag `whitespace_variants` es `false`. La
normalización de la llave de dedupe es, sobre este corpus, un no-op exacto.

Consecuencia operativa: **la worksheet de etiquetado va a tener 49 filas del
corpus de corridas, no ~32.** El dedupe por string no ahorra trabajo de
clasificación y no hay que presupuestarlo como si lo hiciera.

#### El corpus se queda en las corridas: la línea base no entra

`evals/results/baseline_ddl_only.md` **es evidencia, no fuente de datos.** No se
parsea. Las 5 llamadas de la línea base viven ahí como bloques de markdown y no
entran al corpus: son un archivo de resultados congelado, y además corrieron con
otra variable de esquema, así que fusionarlas ensuciaría la procedencia de cada
entrada.

Por eso el corpus tiene **50 crudos y 49 distintos**, no 55. La diferencia entre
"55 llamadas medidas" y "50 en el corpus" es exactamente la línea base.

#### Las worksheets se mueven a la etapa 1b

Las worksheets **no se generan en la etapa 1.** Viene una etapa 1b con un set de
SQL adversario escrito a mano, en su propio archivo `corpus_sql_adversarial.json`,
y las worksheets se generan **una sola vez** de la unión de los dos archivos.

La razón es el protocolo de archivos congelados: si la worksheet se generara ahora
y el corpus adversario llegara después, habría que editar un archivo congelado o
mantener dos worksheets desalineadas. Generarla una vez de la unión evita las dos
cosas.

**El protocolo no cambia: worksheets y etiquetas se commitean ANTES de que exista
una sola línea del detector.** Solo se mueven una etapa adelante. El orden es lo
que impide que el detector se escriba primero y las etiquetas se acomoden después
para que salga bien.

#### Cuántas entradas caen en `no_rows`

El veredicto está definido arriba, en el diseño del detector. Lo que la etapa 1
aporta es **cuántas entradas del corpus le toca**, y son pocas.

El dato sale de `result.row_count` en los JSON de corridas. No se recalculó
corriendo nada.

| | |
|---|---|
| Distintos que devolvieron 0 filas | **2 de 49** — ids 19 y 24 |
| Procedencia | ambos `ddl_only`, Q4 corrida 4 y Q5 corrida 4 |
| Distintos con >0 filas | 47 |
| Con error de sqlite | 0 |
| Mismo SQL con conteos distintos entre corridas | 0 |

Dos casos no alcanzan para saber si la regla de precedencia de `no_rows` se aplica
bien. **Es un argumento a favor del set adversario de la 1b:** si `no_rows` va a ir
antes que `clean` en el orden de evaluación, conviene tener más de dos entradas que
lo ejerciten.

Ojo con el `row_count` para la 1b: es el dato que define este veredicto, y por eso
mismo **no puede entrar a la worksheet.** Una query que devolvió 4 filas cuando se
pidió un solo total se delata sola, y ver eso mientras etiquetas ya no es etiquetar
el SQL, es leer el resultado.

#### Pendiente de especificar

Cosas que la etapa 1 necesitaba y que no llegaron con el prompt, porque se truncó
al pegarse. Se listan aquí para que la ausencia sea visible en el repo en lugar de
silenciosa. Lo tachado quedó cubierto por
`docs/rebanada-3-especificacion.md` el 29 de julio de 2026.

- ~~**Los nombres y definiciones de cuatro de los cinco veredictos.**~~ Cubierto:
  los cinco están arriba, con orden de precedencia.
- ~~**El alcance de v1 del detector.** Qué reporta, qué no, y dónde se corta.~~
  Cubierto: dentro, nunca-se-marca, fuera-a-`not_analyzed`, y con-salvedad.
- ~~**Las etapas 2, 3 y 4.**~~ Cubierto: la tabla de etapas está arriba, y son
  cinco con la 1b.
- **El formato de la worksheet ciega.** Especificado en la sección 8 de
  `docs/rebanada-3-especificacion.md`, pero **no volcado aquí a propósito**: es
  material de la 1b y se documenta cuando se construya, no antes.
- ~~**Cómo se parte dev y holdout.**~~ Cubierto: 50/50 estratificado por
  `(is_no_rows, has_cte, has_left_join)`, seed `20260729`, congelado en
  `evals/gold/split_assignment.json`. Ver la sección de la partición arriba.
- ~~**El formato de la worksheet ciega.**~~ Cubierto por la sección 8 de
  `docs/rebanada-3-especificacion.md`: id, SQL formateado, `LABEL:`, `SHAPE:`, y en
  el header el DDL completo más el criterio resumido.

Huecos del reporte de cierre que **se quedan abiertos a propósito**, cada uno con la
condición que los cierra:

- **`T` por query (8.3).** Determinar `T` requiere la lógica del detector. **Se cierra
  con la primera salida del detector, no antes.** Cualquier intento de cerrarlo ahora
  sería escribir el detector con otro nombre.
- **Trazar el join path real de Q5 (8.7).** Se cierra cuando el detector corra sobre
  el corpus. El caso A2 del set adversario cubre la forma multi-salto mientras tanto.
- **Joins anidados dentro de CTEs y subconsultas (8.8).** El conteo de 13 `LEFT JOIN`
  es sintáctico y del scope de más afuera. Es un piso, no un total.
- **`generate.py` (8.10).** Se sabe que quita un `;` final en 1 de 50 casos. No se ha
  leído para saber si es intencional ni si quita algo más.
- **La cláusula "PK o índice UNIQUE" del alcance de v1 no tiene blanco.** Medido: el
  único índice UNIQUE de esta base es el autoindex de la PK compuesta de
  `financials`, `origin=pk`. No hay ninguna restricción UNIQUE declarada aparte de las
  PKs, así que hoy **el lado "uno" se determina solo por PK** y esa mitad de la
  cláusula está escrita pero sin probar.
- **`no_rows` subestima la adivinanza de literales.** Medido: **24 literales de texto
  del corpus no existen en su columna, y solo 2 entradas devolvieron 0 filas.** La id
  25 usa `'Backlog'` igual que la id 24 y sí devolvió filas. Contar `no_rows` como
  proxy de "adivinó mal el literal" subestima el fenómeno por un factor de doce. No
  afecta el etiquetado; afecta cualquier conteo de la rebanada 4.
- **La duplicación semántica del corpus sigue sin medir.** El dedupe es **solo por
  string**: dos queries idénticas salvo alias, orden de columnas o nombre de la
  columna de salida son dos entradas distintas de las 49. El propio ROADMAP dice que
  el agrupamiento útil es por resultado o por plan de ejecución, y **ese agrupamiento
  nunca se calculó.**

  **Se mide antes de publicar cualquier precision o recall, porque cambia la N
  efectiva.** Si de las 49 entradas resulta que hay, digamos, 22 queries
  semánticamente distintas, entonces un detector evaluado sobre 49 está reportando
  sobre una muestra con réplicas y su intervalo de confianza es más angosto de lo
  que merece. **No bloquea el etiquetado:** etiquetar 49 strings es correcto y
  necesario; lo que no es correcto es tratar 49 como 49 observaciones independientes
  al calcular métricas.

### La partición dev / holdout

Especificada el 29 de julio de 2026 en `docs/rebanada-3-addendum-01.md`. Faltaba por
completo. **Si se decide después de ver las etiquetas, no es un holdout.**

#### El set adversario no se parte

Va **100% a dev**. Son unit tests con respuesta declarada, no una muestra. **No
entran a la estimación de desempeño de nadie.** Se reportan como pasa o falla por
caso, contra el veredicto esperado declarado.

Razón: son deliberadamente adversarios y **no representan output del modelo**.
Mezclarlos con el corpus real produciría una precision y un recall que no describen
ninguna de las dos poblaciones.

#### El corpus real se parte 50/50, estratificado

- **Estratos:** la tupla `(is_no_rows, has_cte, has_left_join)`, con los flags
  estructurales ya medidos en el lote de verificación. **Son hechos medidos, no
  etiquetas, así que no hay fuga.**
- **Asignación:** dentro de cada estrato, shuffle con seed `20260729` y luego
  alternar dev y holdout. Con 2 entradas de `no_rows`, una a cada lado. Con 6 de CTE,
  tres y tres.
- **Congelado:** la asignación se escribe en `evals/gold/split_assignment.json` y se
  commitea **antes de que exista una sola etiqueta**.
- **Limitación anotada:** los 13 `LEFT JOIN` son un conteo **sintáctico del scope de
  más afuera** y pueden ser un piso. Estratos imperfectos siguen ganándole a un split
  aleatorio con N chica, pero la imperfección queda escrita.

#### Qué puede y qué no puede concluir el holdout

**Puede:** cachar **overfitting grueso**. Si el comportamiento cambia fuerte entre la
mitad que se usó para construir y la que no, eso se ve.

**No puede: producir una tasa publicable.** Son 49 entradas, mitades de 24 y 25, con
tasa de positivos desconocida. **Precision y recall se reportan en conteos, nunca en
porcentajes**, hasta que exista el gold set grande de la rebanada 4.

Y hay una segunda razón para no publicar porcentajes que es independiente del N: la
**duplicación semántica del corpus sigue sin medir**, así que las 49 entradas no son
49 observaciones independientes.

### El congelado empieza en el primer uso, no en el primer commit

Precisión al protocolo de archivos congelados, del 29 de julio de 2026. Es más
general que el caso que la produjo.

**La regla de congelado protege MEDICIONES.** Un archivo de resultados es intocable
porque sobrescribirlo destruye la comparación que hace que el resultado signifique
algo. Ése es el daño concreto que la regla previene.

**Un artefacto que nunca produjo una medición no tiene nada que proteger.** Si un
criterio, una plantilla o un esquema se commitea y después se corrige **antes de que
alguien lo use para medir**, se reescribe en su lugar. Nada se destruye: git guarda
la versión vieja, y no hay ninguna medición cuya interpretación dependa del texto
anterior.

El caso que lo produjo: `LABELING_CRITERIA.md` se commiteó en `e111d8f` y quedó
rancio en cuatro puntos. Tratarlo como congelado habría dejado un documento con
cuatro frases muertas más cuatro notas de corrección, **para que alguien lo lea de
corrido durante una hora de trabajo de etiquetado.** Eso es peor documento y no
protege nada.

En cambio, **en cuanto haya una etiqueta escrita, el congelado aplica en su forma
dura**, porque a partir de ahí sí hay una medición cuya interpretación depende del
texto.

### Regla de adjudicación: etiqueta humana contra veredicto del detector

**Pre-registrada el 29 de julio de 2026, antes de que exista una sola etiqueta.** Ese
es el punto: escrita antes de ver un dato para que ninguna línea pueda ser un rescate
post hoc.

Los dos vocabularios **no comparten ni un token**, así que la comparación nunca puede
hacerse con `==` y hay que pasar por esta tabla a propósito.

| Etiqueta humana | Veredicto del detector | Resultado |
|---|---|---|
| `shape_present` | `inflated` / `shape_no_inflation` / `no_contributing_rows` | **acuerdo** |
| `shape_present` | `clean` | **miss del detector** |
| `shape_absent` | `clean` | **acuerdo** |
| `shape_absent` | `inflated` con forma nombrada | **falso positivo** |
| `shape_absent` | `inflated`, `unexplained`, multiplicador > 1 | **el detector vio algo que yo no. NO es falso positivo** |
| `shape_absent` | `inflated`, `unexplained`, multiplicador = 1.0 | **falso positivo, sin excepción** |
| `out_of_scope` | `not_analyzed` | **acuerdo** |
| `unsure` | cualquiera | **fuera del conteo, reportado aparte** |

**La quinta línea es la única que perdona, y la perdona una medición, no un juicio.**
Un multiplicador medido mayor a 1 es un hecho sobre la base: si el detector encontró
duplicación real donde el humano no vio la estructura, el humano se equivocó. La
sexta línea es la contraparte que impide que esa clemencia se vuelva un comodín: sin
duplicación medida, `unexplained` no compra nada.

#### Las combinaciones restantes

Completadas el 29 de julio de 2026, **también antes de que exista una etiqueta.**

| Etiqueta humana | Veredicto del detector | Resultado |
|---|---|---|
| `shape_present` | `not_analyzed` | **hueco de cobertura CON riesgo.** Se vio estructura peligrosa y v1 no la alcanza. Se enruta por `reason` |
| `shape_absent` | `not_analyzed` | **hueco de cobertura SIN riesgo.** Se enruta por `reason` igual |
| `shape_absent` | `shape_no_inflation` | **falso positivo LATENTE**, pendiente de revisión manual. **No es acuerdo** |
| `shape_absent` | `no_contributing_rows` | **acuerdo sobre fan-out.** El `no_contributing_rows` se reporta en su propia población, no en este conteo |
| `out_of_scope` | cualquiera que no sea `not_analyzed` | **FUGA DEL GUARD DE ALCANCE.** Defecto hasta que se demuestre lo contrario, **nunca acuerdo** |

Con estas cinco, **la matriz queda completa: las 4 etiquetas × 5 veredictos, 20 de 20
combinaciones tienen regla escrita antes de la primera etiqueta.**

Tres que merecen su razón explícita:

- **`shape_absent` + `shape_no_inflation` no es acuerdo**, aunque los dos digan "no
  infla". La estática marcó una forma que el humano no ve, y **solo la medición la
  salvó de ser falso positivo**. Contarla como acuerdo escondería un detector que
  sobre-detecta estructura y se salva por suerte de los datos. Va a revisión manual.
- **`out_of_scope` contra cualquier otro veredicto es defecto por defecto.** El
  detector emitió un veredicto sobre algo que no debía tocar. Un guard de alcance que
  se filtra no es un acierto aunque el veredicto resulte correcto: significa que el
  guard no está haciendo su trabajo, y el acierto fue accidental.
- **`shape_absent` + `no_contributing_rows` es acuerdo sobre fan-out**, y el
  `no_contributing_rows` se cuenta aparte. Son dos poblaciones distintas y mezclarlas
  contaminaría las dos.

#### Enrutado por `reason`, para las dos filas de `not_analyzed`

| `reason` | Lectura |
|---|---|
| En `{self_join, window_function, set_operation, non_fk_join, ambiguous_column}` | Los criterios listan esa razón, así que la etiqueta debió ser `out_of_scope`. **Error de etiquetado del humano.** Se cuenta y se reporta como tal |
| Fuera de esa lista, por ejemplo `non_base_table` | Los criterios nunca dijeron que buscara eso. **Hueco del documento de criterios, no error del humano.** Se reporta como hueco de criterios |

La distinción importa porque las dos se ven igual en los datos —etiqueta que no
coincide con veredicto— y tienen causas opuestas. Una se arregla etiquetando mejor;
la otra se arregla escribiendo mejor los criterios. Confundirlas haría que un
documento incompleto se lea como un etiquetador descuidado.

#### `RECONOCIDA` no excluye, duplica el reporte

Las entradas marcadas `RECONOCIDA: si` **no se sacan del conteo.** Los conteos
primarios se reportan **dos veces**: con todas las entradas, y excluyendo las
reconocidas.

- Si los dos números **difieren fuerte**, el ciego estaba haciendo trabajo.
- Si **no difieren**, el reconocimiento no sesgó mucho.

**Es una medición del efecto del ciego, no un supuesto sobre él.** Descartar las
reconocidas de entrada tiraría justo el dato que permite saber cuánto valía el ciego,
y además reduciría la N sin evidencia de que hiciera falta.

### El ciego y el holdout dependen de disciplina, no de mecanismo

Hay que decirlo en voz alta porque es fácil confundir "está protegido" con "está
anotado".

**El keymap deshace el ciego con un `cat`.** `worksheet_keymap.json` está commiteado
y mapea cada clave opaca a su id del corpus, y de ahí la config sale con una resta:
ids 1–25 son `ddl_only`, 26–49 son `values_text_maxcard20`. Nada impide abrirlo
mientras se etiqueta.

**Es exactamente la misma situación que el holdout.** Todo lo que hace match con
`evals/gold/*holdout*` es intocable hasta la etapa 4 por una promesa, no por un
permiso de archivo.

**Se anota y no se construye nada para eso.** Cifrar el keymap, sacarlo del repo o
meterle un hook sería infraestructura para un problema que en este proyecto tiene un
solo participante, y el alcance dice no agregar lo que la rebanada no pide. Lo que sí
tiene que quedar escrito es que **si alguna vez se abre, se dice en voz alta y se
marca el ciego como quemado**, igual que con el holdout. Un ciego roto y reportado
sigue siendo evidencia de algo; uno roto en silencio no.

Además, el ciego ya era **parcial por construcción**: los literales del SQL delatan
la config a quien conozca el proyecto —`'Lennar'` solo aparece en la config A y
`'Lennar Corporation'` solo en la B— y el SQL no se puede redactar sin destruir la
tarea de etiquetado.

### Regla: todo conteo lleva su denominador

**Un numerador sin denominador no es una medición.**

Va dos veces con el mismo patrón, y las dos las cachó la revisión y no quien
midió: los "99 pares" del lote de verificación y las "422 columnas" del cierre de
huecos. En los dos casos el numerador se reportó solo, y en los dos casos el
denominador resultó ser menor que el universo.

Los denominadores vigentes de este corpus, definidos:

| N | Qué es | Qué queda fuera |
|---|---|---|
| **49** | Entradas distintas en `corpus_sql.json`. El universo. | nada |
| **43** | De esas, las que permiten reconstruir la fuente de filas y ejecutar `COUNT(*)` | **6**: ids 16, 28, 36, 38, 45, 47, las seis con CTE |
| **42** | De esas 43, las que además tienen ≥1 tabla base referenciable por alias | **7**: las 6 con CTE **+ id 17**, por alias de subconsulta no visible en el scope de más afuera |

El delta entre 43 y 42 es **exactamente la id 17**. Y un dato contraintuitivo: **con
la fórmula de `rowid` el denominador sigue siendo 42**, no 43. Yo esperaba que
subiera al desaparecer el filtro de "PK de una columna", y no sube: el problema de
la id 17 es de visibilidad de alias, no de aridad de la PK.

### La clase de los 17: un modo de falla que no tiene guardrail

Medido el 29 de julio de 2026. **17 entradas del corpus tienen la fuente de filas
vacía y aun así devuelven una fila al usuario.**

El mecanismo, probado directo:

```
SELECT COUNT(*) FROM homes WHERE status='Sold'           -> 1 fila, valor (0,)
SELECT community_id, COUNT(*) ... GROUP BY community_id  -> 0 filas
```

**Un agregado desnudo sobre cero filas emite exactamente una fila con un `0` o un
`NULL` adentro.** Las dos únicas entradas del corpus con `row_count = 0` son
precisamente las dos que llevan `GROUP BY`.

La query contesta, `T` no aporta nada, el agregado sale `0` o `NULL`, **y el usuario
ve un número.** Es una falla silenciosa de la misma familia que el fan-out: el
resultado se ve como una respuesta y no lo es.

**Candidato a su propio guardrail en una rebanada posterior. No se construye nada
para ellos ahora.** La rebanada 3 es detección de fan-out y meter esto sería
exactamente el tipo de crecimiento por inercia que el alcance prohíbe. Queda
anotado como hallazgo, con su medición, para que exista cuando toque.

Efecto lateral que sí importa ya: **`row_count = 0` es un proxy pésimo de "no
matcheó nada"**, y cualquier conteo de la rebanada 4 que lo use va a subestimar el
fenómeno por un factor grande.

### Lote de verificación del corpus: decisiones pre-registradas

**Escritas el 29 de julio de 2026, antes de correr una sola medición.** No cambian
con el resultado. Están aquí para que el resultado no pueda renegociar el criterio
después de conocerse, que es la forma más fácil de convertir una medición en una
justificación.

1. **`validate_qualify_columns=True` se queda, salga el número que salga.** Lo que
   `qualify` rechace es `not_analyzed`, y la cobertura se publica como **dato de
   alcance**. No se afloja el flag para que suba el número de queries analizadas.
   Un detector que analiza más porque dejó de validar no analiza mejor.
2. **Si la corrección del multiplicador sale inerte en los 49, se queda**,
   documentada como correcta e inerte en este corpus. No se revierte. Una
   corrección que no cambia nada en el corpus actual sigue siendo correcta para el
   set adversario, que es justamente donde van a vivir los `LEFT JOIN`.
3. **Si un número propagado no cuadra con la base**, va nota de corrección fechada
   en el ROADMAP **y** en la especificación. Nunca una edición silenciosa.
4. **Si el hash de `portfolio.db` no cuadra, se para todo** y se avisa antes de
   seguir con nada. Un corpus cuya base cambió no es un corpus.

Los resultados del lote van a `evals/results/corpus_verification.md`, que es un
archivo de resultados y **no se edita después**.

#### Resultado del lote, en una tabla

| Tarea | Resultado |
|---|---|
| 0 | Hash de la base **CUADRA**. El gate pasó |
| 1 | `qualify` pasa **49 de 49**. Cero excepciones. Cobertura 100% |
| 2 | Multiplicador (a) **40.0** no 41.3, (b) 1.0, (c) hay que forzar el hueco. **0 diferencias** `COUNT(*)` vs `COUNT(T.pk)` entre los pares medidos |
| 2b | **El multiplicador de filas (40.0) no es el ratio de valor (41.285653)** |
| 3 | Los tres números propagados **CUADRAN** |
| 4 | `MAX`, `MIN`, `COUNT(DISTINCT)` no se mueven. `SUM`, `AVG`, `COUNT` sí |
| 5 | La extracción quitó **un punto y coma final**, nada más. Corpus id 37 |
| 6 | Las dos entradas de `no_rows` son **`WHERE` que no matchea**, no joins vacíos |
| 7 | `uv lock --check` exit 0, 20 paquetes |

Dos cosas del lote cambiaron el diseño y están anotadas como correcciones arriba: la
distinción entre multiplicador de filas y ratio de valor, y la confirmación de que la
corrección del numerador es inerte en este corpus pero no equivalente.

### Dependencia congelada: sqlglot 30.14.0

| | |
|---|---|
| Versión fijada | **30.14.0**, pin exacto `==` en `pyproject.toml` |
| Publicada | 27 de julio de 2026 |
| Fijada en este repo | 29 de julio de 2026 |
| Gate | el smoke test de abajo |

El plan de la etapa decía 30.12.0. Ese número venía de un agregador de terceros y
estaba dos MINOR atrasado; `pypi.org/pypi/sqlglot/json` da 30.14.0 del 27 de julio
(la 30.12.0 es del 26 de junio). Se fijó la 30.14.0.

**El changelog de 30.13 y 30.14 NO se verificó línea por línea.** Se leyó por
encima —los cambios rompedores de 30.13.0 se ven como anotaciones de tipos y
refinamientos de parseo, ninguno tocando `scope.py`, la firma de `qualify` ni el
dialecto sqlite— pero eso es una impresión, no una auditoría. **El gate fue el
smoke test, no la lectura del changelog.** Si algo de 30.13/30.14 rompe este
proyecto de una forma que las cuatro partes no ejercitan, no lo vamos a saber por
haber leído el changelog.

Por qué el pin es exacto y no un rango: en sqlglot el MINOR sube cuando hay
cambios que rompen compatibilidad. Un rango deja entrar esos cambios sin que nadie
corra el smoke test.

#### El smoke test: `evals/gold/smoke_sqlglot.py`

Cuatro partes, cada una con assert propio. Resultado del 29 de julio de 2026,
contra sqlglot 30.14.0 y Python 3.12:

| Parte | API | Resultado |
|---|---|---|
| a | `parse_one(sql, dialect="sqlite")` | ok — los 6 fixtures parsean como `Select` |
| b | `build_scope`, `traverse_scope` | ok — CTE (2 scopes, 3 sources), subconsulta en `FROM` (2 scopes, 1 source), subconsulta en `WHERE` (2 scopes, 1 source) |
| c | `qualify` con el esquema real | ok — `SUM(budget_usd)` sin prefijo se resuelve a `communities.budget_usd`, y la columna sigue dentro del `SUM`. Contraprueba: `name` con `companies` y `communities` en el `FROM` es rechazada con `OptimizeError` |
| d | `PRAGMA table_info` / `foreign_key_list` | ok — 4 tablas, las 4 PKs (incluida la compuesta de `financials`) y las 3 FKs |

**Este test no lee `corpus_sql.json`, y correr sin ese archivo es parte de lo que
afirma.** Los seis fixtures están escritos a mano dentro del propio archivo,
contra el esquema real de `portfolio.db`. Dos de ellos son deliberadamente la
forma de las dos puertas de fan-out medidas en la rebanada 2 —agregar sobre el
lado "uno" de un join a `homes`, y colgar `financials` de un join sin relación de
grano real— porque son los árboles que el detector va a tener que leer.

La razón de la separación es una dependencia circular: el gate de la librería no
puede depender del artefacto de datos que se construye usando la librería. Son dos
afirmaciones distintas y viven en dos archivos distintos. **La verificación de que
el SQL del corpus parsea vive en `extract_corpus.py`**, que es donde el corpus se
produce, y si algo no parsea el corpus no se escribe.

La parte (c) es la que justifica el archivo. Es la única API cuya firma no estaba
verificada antes de esta etapa, y trae tres defaults que muerden:

- **`validate_qualify_columns=True`** hace que `qualify` **lance excepción** cuando
  no puede resolver una columna. Sobre SQL generado por un modelo eso es un riesgo
  real: mezclar parse y qualify en el mismo contador inflaría el "no parsea". La
  contraprueba del test existe para detectar si este default deja de validar,
  porque entonces el detector confiaría en una resolución que no ocurrió.
- **`identify=True` y `quote_identifiers=True`** reescriben el SQL con todo
  entrecomillado. Lo que salga de `qualify` no se le muestra al usuario.
- **`schema` e `infer_schema` interactúan.** Con esquema explícito va
  `infer_schema=False`, o inventa columnas que no se le dieron.

El esquema que se le pasa a `qualify` es `{tabla: {columna: TIPO}}` y sale de
`PRAGMA table_info`, igual que el prompt. No hay ningún esquema escrito a mano.

#### Regla de imports para sqlglot

Solo se importa de `sqlglot` y de `sqlglot.optimizer`. Nunca de rutas internas
tipo `sqlglot.expressions.aggregate`: en el 30.x `expressions` está partido en
submódulos, y atarse a una ruta interna nos deja expuestos a un refactor de
upstream en un PATCH.

Un detalle verificado a mano que hay que saber antes de escribir el detector: el
`__init__` de `sqlglot.optimizer` expone `build_scope`, `traverse_scope`,
`find_all_in_scope`, `find_in_scope`, `walk_in_scope`, `Scope`, `optimize` y
`RULES` por un `__getattr__` PEP 562 (`_LAZY_ATTRS`), **pero `qualify` no está en
esa lista.** `from sqlglot.optimizer import qualify` devuelve el **módulo**, no la
función —`callable()` da `False`— y hay que llamar `qualify.qualify(...)`. La doc
renderizada no dice esto; las páginas `sqlglot.com/sqlglot/optimizer/qualify.html`
y `.../scope.html` dan **404**, así que la firma se verificó contra el fuente en el
tag `v30.14.0` y luego contra el paquete instalado con `inspect.signature`.

## Regla de diseño para la rebanada 2

**Los valores de una columna van completos o no van. Nunca una muestra.**

Enseñarle al modelo 10 de 800 valores hace que asuma que ésos son todos. Es el
hallazgo del Proyecto 2: **datos amputados producen invención**. Un listado
parcial es peor que ninguno, porque el modelo no distingue "esto es una
muestra" de "esto es el universo".

Para columnas de alta cardinalidad va una línea que diga:

```
N valores distintos, no listados
```

**Nunca ejemplos.** Ni "por ejemplo", ni "entre otros", ni los tres primeros.

### Las columnas numéricas no se listan nunca

Decidido el 2026-07-28, antes de la primera corrida de la rebanada 2.

Se listan los valores **solo de columnas de tipo texto o fecha**. Las
declaradas `INTEGER`, `REAL` o `NUMERIC` no se listan jamás, sin importar su
cardinalidad: va la línea de conteo. El tipo sale de `PRAGMA table_info`, así
que la regla sigue siendo automática y no depende de conocer el dominio.

**Motivo, y es de medición, no de estética.** `financials` tiene cuatro filas.
Sin esta regla, `revenues`, `net_income`, `backlog_value` y `homes_delivered`
caen todas bajo el umbral y entran completas al prompt. Eso pone `35441452` y
`36801.4` lado a lado en el texto y **mata la trampa #1**: si el modelo acierta
en escalas, ya no hay forma de saber si razonó sobre `unit_scale` o si nada más
vio dos magnitudes absurdamente distintas y dedujo la escala del tamaño del
número. Un acierto que no se puede atribuir no sirve de evidencia.

Y de todos modos adivinar literales es un problema de strings. Nadie escribe
`WHERE revenues = 35441452`. Listar números no aporta al objetivo de la
rebanada y solo mete un confusor.

#### Limitación: esta regla se decidió, no se midió

**No se corrió una configuración con los números listados.** El argumento de
arriba es razonamiento sobre atribución, no evidencia empírica. No se sabe qué
habría hecho el modelo con `revenues` y `backlog_value` completos en el prompt.

Queda como **ablación opcional**, no en el camino crítico. Si algún día se corre,
va en su propio archivo de resultados con su propio nombre
(`values_all_maxcard20_nN.md` o parecido) y **no** reemplaza a
`values_text_maxcard20_n5.md`.

La razón de dejarla fuera del camino crítico: el resultado más probable es que
confirme lo que ya se sabe por la rebanada 2 —que inyectar un valor no hace que
se use— y el costo real no es el dinero, es que un acierto en la trampa #1
dejaría de ser atribuible para siempre en la serie de mediciones.

### Ni llaves primarias ni foráneas, y lo que eso implica

Un id no le sirve al modelo para escribir un literal, así que las columnas de
llave primaria o foránea quedan fuera del listado.

**Consecuencia que hay que tener presente al leer los resultados:**
`financials.fiscal_year` es parte de la llave primaria compuesta, así que 2023
y 2024 **no se listan**. El modelo sigue teniendo que adivinar qué años
existen. La rebanada 2 **no elimina la adivinanza de literales por completo**, y
esto puede explicar fallas residuales aun con los valores prendidos.

## Para la rebanada 4: el eval harness

Cinco cosas que salieron de la rebanada 2 y que hay que meter en el diseño del
harness, no descubrir otra vez.

### 1. Agrupar por string exacto de SQL no sirve

Era la instrucción de la rebanada 2 para no clasificar 50 veces. **No ahorró
nada:** las 25 corridas de la config A dieron **25 SQL distintos**, sin una sola
repetición. La config B dio 24 de 25.

Buena parte de la variación es cosmética —alias distintos, nombres de columna de
salida en español o en inglés— y aun así el string exacto no colisiona nunca.

**El agrupamiento útil es por resultado o por plan de ejecución**, no por texto.
Agrupar por el conjunto de filas devuelto colapsaría las cinco variantes de Q2 de
la config B en un solo grupo, que es lo que se quería.

### 2. Trampas #2 y #6: llevan tres corridas sin probarse

`unit_scale` aplicado a un conteo (#2) y `closing_date` NULL en el backlog (#6)
no se han probado **ni en la línea base, ni en la config A, ni en la config B**.
Tres corridas consecutivas, 55 llamadas, cero evidencia.

No es mala suerte: ninguna de las cinco preguntas obliga al modelo a razonar
sobre ellas. **El gold set debe incluir preguntas dedicadas**, escritas
específicamente para forzarlas, o se van a quedar sin medir para siempre.

### 3. Paráfrasis de Q2 que fuercen la ambigüedad región/estado

La predicción de que el modelo confundiría `region='Texas'` con `state='TX'`
**falló**: las 5 corridas eligieron `state`. Pero la ambigüedad **sigue viva en
los datos**:

| | comunidades | casas |
|---|---|---|
| `region = 'Texas'` | 2 | **79** |
| `state = 'TX'` | 4 | **149** |

Las dos son literales válidos que aparecen textualmente en el prompt de la config
B, las dos devuelven filas y ninguna se delata. Una predicción fallida no es una
hipótesis refutada: se probó con un modelo, una redacción y N=5.

El gold set debe traer paráfrasis que empujen hacia `region` —"en el territorio
de Texas", "en la región de Texas"— para saber si la colisión se dispara cuando
la pregunta la invita.

### 4. `fiscal_year` es un riesgo latente, no un problema resuelto

Por la regla de llaves, `financials.fiscal_year` no se lista. De las 25 corridas
de la config B, **10 tocaron `fiscal_year`** —las 5 de Q1 y las 5 de Q3; Q2, Q4 y
Q5 nunca lo mencionaron— y **las 10 escribieron `fiscal_year = 2024` y le
atinaron**.

Eso es **adivinanza de literal que no falló, no adivinanza eliminada.** Le
atinaron porque 2024 es el año obvio para una pregunta que dice "2024", no porque
el prompt lo dijera. Un gold set con preguntas sobre FY2022 o FY2019 —años que no
existen en la tabla— mediría esto de verdad; las cinco preguntas actuales no
pueden.

### 5. Las proporciones no se firman hasta que haya scoring automático

**El scoring automático contra gold set es lo que permite firmar una
proporción.** Hasta entonces, los agregados de la rebanada 2 —"22 ruidosas a 0",
"3 silenciosas a 16"— son **medición interna**: una sola persona clasificando 49
SQL contra criterios escritos antes, sin segunda opinión ni verificación
mecánica.

Regla que sale de esto: **las proporciones de las rebanadas 1 y 2 no van a un
README ni a nada de cara afuera.** Los casos individuales sí aguantan, porque
cada uno es una cifra verificable contra la base: Q4 devolvió $14,388,050,000
contra $348,500,000 reales, y eso lo reproduce cualquiera corriendo el SQL
guardado en `evals/runs/`.

Citar el caso, no el porcentaje.

## Protocolo de archivos congelados

Un archivo de resultados es un registro de una medición que ya ocurrió. No es
documentación viva.

### La regla

**Un archivo de resultados nunca se edita.** Si cambia cualquier variable
—modelo, prompt, contenido del esquema, esfuerzo de razonamiento, temperatura,
las preguntas, el gold set— el resultado va en un **archivo nuevo**.

Sobrescribir un archivo de resultados destruye la comparación que hace que el
resultado signifique algo.

### Cuando se detecta un error de metadatos

Ejemplo real: los precios de la línea base se tomaron de páginas públicas de
terceros, no de una factura. Si resultan estar mal, el costo reportado está
mal por un factor constante.

En ese caso:

- Va una **nota de corrección fechada al inicio del archivo**.
- **Nunca** una reescritura silenciosa.
- **Los resultados medidos no se tocan jamás.** La nota corrige la
  interpretación; los números se quedan exactamente como se midieron.

Formato de la nota:

```markdown
> **Corrección 2026-08-15.** El precio de salida aplicado en este archivo
> ($1.25/Mtok) resultó ser el del tier estándar; esta cuenta está en tier X.
> Los costos en dólares de abajo están inflados 1.4x. Los conteos de tokens
> vienen del campo `usage` de la API y son correctos.
```

La razón: un archivo de resultados con una corrección visible sigue siendo
evidencia. Un archivo reescrito no es evidencia de nada, porque no hay forma
de saber qué más cambió.
