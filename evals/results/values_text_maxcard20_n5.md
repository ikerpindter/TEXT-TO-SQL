# Config B: valores de columnas de texto, umbral 20, N=5

**Este archivo está congelado. No se edita nunca.** Si cambia cualquier
variable —modelo, prompt, contenido del esquema, umbral de cardinalidad,
esfuerzo de razonamiento, temperatura, las preguntas— el resultado va en un
archivo nuevo.

Es el brazo experimental de la rebanada 2. Se compara contra
[`ddl_only_n5.md`](ddl_only_n5.md), que corrió las mismas cinco preguntas, el
mismo modelo, el mismo N y la misma base. **La única diferencia entre los dos
archivos es el bloque de valores anexado al esquema.** El DDL que recibe el
modelo es byte por byte idéntico en las dos configuraciones; verificado con
`cmp` antes de correr.

---

## Configuración exacta

| | |
|---|---|
| Fecha de la corrida | 2026-07-28 |
| Rebanada | 2 (inyección de valores) — brazo experimental |
| Configuración | `values_text_maxcard20` |
| Umbral de cardinalidad | **20** |
| Modelo solicitado | `gpt-5.4-nano` |
| API | Responses API (`client.responses.create`) |
| Esfuerzo de razonamiento | **default de la API** — no se fijó `reasoning={"effort": ...}` |
| `store` | `False` |
| Temperatura | no se fijó |
| `max_output_tokens` | no se fijó |
| N | **5 corridas por pregunta**, 25 llamadas |
| Reintentos | ninguno |
| Base de datos | `data/portfolio.db`, sha256 `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762` |
| Filas | companies 2, financials 4, communities 20, homes 794 |
| Esquema enviado | 2,800 chars — 980 de DDL + 1,820 del bloque de valores |

## La regla de inyección

Por cada columna que **no** sea llave primaria ni foránea:

1. **Completos o nada. Nunca una muestra.** Si tiene 20 valores distintos o
   menos, van **todos**. Si tiene más, va una línea que dice
   `N valores distintos, no listados`. Ni un ejemplo, ni "entre otros", ni los
   tres primeros. Es la regla de diseño del ROADMAP: datos amputados producen
   invención, porque el modelo no distingue una muestra de un universo.
2. **Solo columnas de texto o fecha.** Las declaradas `INTEGER`, `REAL` o
   `NUMERIC` no se listan nunca, sin importar su cardinalidad.
3. **Ni llaves primarias ni foráneas.** Un id no le sirve al modelo para
   escribir un literal.

Las tres son automáticas: el tipo y las llaves salen de `PRAGMA table_info` y
`PRAGMA foreign_key_list`. Ninguna depende de conocer el dominio.

### Por qué las numéricas no se listan

Decidido antes de la primera corrida. **El motivo es de medición, no de
estética.**

`financials` tiene cuatro filas, así que `revenues`, `net_income`,
`backlog_value` y `homes_delivered` caen todas bajo el umbral de 20 y
entrarían completas al prompt. Eso pondría `35441452` y `36801.4` lado a lado
en el texto y **mataría la trampa #1**: si el modelo acertara en escalas, no
habría forma de saber si razonó sobre `unit_scale` o si nada más vio dos
magnitudes absurdamente distintas y dedujo la escala del tamaño del número. Un
acierto que no se puede atribuir no sirve de evidencia.

Y de todos modos adivinar literales es un problema de strings. Nadie escribe
`WHERE revenues = 35441452`. Listar números no aporta al objetivo de la
rebanada y solo mete un confusor.

Efecto medido de la regla: el bloque bajó de 2,119 a **1,820 chars**, y seis
columnas —`revenues`, `net_income`, `homes_delivered`, `backlog_value`,
`lot_count`, `budget_usd`— pasaron de listado completo a línea de conteo.

### Esto NO elimina la adivinanza de literales

`financials.fiscal_year` es parte de la llave primaria compuesta, así que por
la regla 3 **2023 y 2024 no se listan**. El modelo sigue teniendo que adivinar
qué años existen en la tabla.

Se anota antes de correr porque puede explicar fallas residuales de adivinanza
de literales aun con los valores prendidos, y no quiero atribuirlas a otra cosa
después.

## Bloque exacto que se anexó

```
-- Valores de companies:
--   name (2 valores): 'D.R. Horton, Inc.', 'Lennar Corporation'
--   ticker (2 valores): 'DHI', 'LEN'
--   fiscal_year_end (2 valores): '09-30', '11-30'

-- Valores de financials:
--   revenues: 4 valores distintos, no listados
--   net_income: 4 valores distintos, no listados
--   homes_delivered: 4 valores distintos, no listados
--   backlog_value: 4 valores distintos, no listados
--   unit_scale (2 valores): 'millions', 'thousands'

-- Valores de communities:
--   name (20 valores): 'Alder Point', 'Ashton Grove', 'Bayard Commons', 'Bexar Landing', 'Cardinal Point', 'Copper Ridge', 'Cypress Bend', 'Highland Ranch', 'Magnolia Farms', 'Marbella Reserve', 'Palmetto Grove', 'Prairie Crossing', 'Rosewood Trails', 'Sierra Vista', 'Silver Sage', 'Sterling Farms', 'Truckee Meadows', 'Vancouver Heights', 'Wexford Crossing', 'Willow Bank'
--   region (9 valores): 'Central', 'East', 'North', 'Northwest', 'South Central', 'Southeast', 'Southwest', 'Texas', 'West'
--   state (14 valores): 'AZ', 'CA', 'CO', 'FL', 'GA', 'IL', 'NC', 'NJ', 'NV', 'PA', 'SC', 'TN', 'TX', 'WA'
--   opened_date (20 valores): '2021-02-22', '2021-04-19', '2021-05-17', '2021-08-30', '2021-09-01', '2021-11-08', '2022-02-14', '2022-03-14', '2022-06-20', '2022-07-11', '2022-09-26', '2022-11-07', '2023-01-23', '2023-02-13', '2023-04-03', '2023-05-08', '2023-08-29', '2023-10-02', '2024-01-15', '2024-03-11'
--   lot_count: 20 valores distintos, no listados
--   budget_usd: 20 valores distintos, no listados

-- Valores de homes:
--   list_price: 367 valores distintos, no listados
--   sale_price: 305 valores distintos, no listados
--   contract_date: 472 valores distintos, no listados
--   closing_date: 381 valores distintos, no listados
--   status (4 valores): 'available', 'backlog', 'cancelled', 'closed'
```

---

## Criterios de clasificación

**Escritos y guardados en disco antes de lanzar la primera llamada**, y
palabra por palabra los mismos que en [`ddl_only_n5.md`](ddl_only_n5.md). Un
criterio que cambia entre los dos brazos no mide nada.

Tres categorías, excluyentes.

**Correcto.** El SQL corre sin error, devuelve al menos una fila, y todas las
cifras coinciden con la referencia bajo alguna de las lecturas admitidas.

**Falla ruidosa.** El resultado se delata solo, sin necesidad de saber la
respuesta. Cualquiera de: error de SQLite, cero filas, todas las columnas
agregadas en `NULL`, o un `0` donde la referencia dice que sí hay filas.

**Falla silenciosa.** El SQL corre, devuelve filas con valores no nulos, nada
en la salida indica que haya problema, y al menos una cifra no coincide con la
referencia.

**Desempate.** Si un resultado califica como ruidosa y silenciosa a la vez
—una fila con un `NULL` en una columna y una cifra mal en otra— gana
**ruidosa**. Lo que define la categoría es si el resultado se delata, y un
`NULL` se delata.

### Lecturas admitidas y cifras de referencia

Fijadas antes de correr. Las cifras salen de consultas escritas a mano contra
la misma base y el mismo sha256. **No son un gold set** —eso es la rebanada
4— sino el aritmético mínimo sin el cual el criterio no es decidible.

**Q1 — "¿Cuánto vendieron en total Lennar y D.R. Horton juntos en su año
fiscal 2024?"** Ambigua entre ingresos y casas. **Las dos lecturas se
admiten.**
- Ingresos: **$72,242,852,000**. Exige aplicar `unit_scale` (Lennar en
  `thousands`, D.R. Horton en `millions`). Sumar `35441452 + 36801.4` sin
  normalizar es falla.
- Casas: **169,900**. Exige NO aplicarle `unit_scale` a `homes_delivered`,
  que es un conteo (trampa #2).
- Que los dos FY2024 cubran periodos distintos (trampa #3) **no se penaliza
  aquí**: la pregunta pide explícitamente "su año fiscal 2024" de cada una. Se
  anota, no se descuenta.

**Q2 — "¿Cuántas casas se han vendido en Texas?"**
- **Texas es `state='TX'`.** `region='Texas'` es una etiqueta de territorio
  comercial que colisiona con el nombre del estado y cubre un conjunto
  distinto. Filtrar por `region` es falla.
- "Vendidas" admite dos lecturas: `status='closed'` → **97**, o
  `status IN ('closed','backlog')` → **113**. Un contrato firmado es una venta
  y una casa entregada también.
- Incluir `cancelled` o `available`, o contar las 149 filas de TX sin filtrar
  status, es falla.

**Q3 — "¿Precio promedio de venta de las casas cerradas en el año fiscal 2024
de Lennar?"**
- FY2024 de Lennar = **2023-12-01 a 2024-11-30** (`fiscal_year_end` = `'11-30'`).
- Referencia: **459,127.12 sobre 118 casas**.
- Exige `sale_price` y no `list_price`, `status='closed'`, ventana sobre
  `closing_date`, y restringir a comunidades de Lennar.
- Sin ventana fiscal da **455,129.41 sobre 255 casas**: es el resultado de la
  línea base y es falla silenciosa.

**Q4 — "¿Presupuesto total de las comunidades de D.R. Horton y cuántas casas
tienen?"**
- Referencia: **$348,500,000** y **400 casas**.
- "Cuántas casas tienen" = todas las filas de `homes` de esas comunidades, sin
  filtro de status.
- Cualquier `SUM(budget_usd)` calculado sobre un join con `homes` infla por
  fan-out (trampa #7) y es falla.

**Q5 — "¿Cuántas casas tiene cada compañía en backlog y cuál es su valor?"**
- Conteo: **Lennar 51, D.R. Horton 52**. Cualquier otro número —102/104, por
  ejemplo— es falla por fan-out.
- "Su valor" es ambiguo y admite dos lecturas:
  - **Sintética:** `SUM(sale_price)` de esas casas → Lennar **23,798,000**,
    D.R. Horton **21,791,000**.
  - **Reportada:** `financials.backlog_value`. Exige elegir **un** año fiscal
    explícito y aplicar `unit_scale`. FY2024 normalizado: Lennar
    **$5,372,784,000**, D.R. Horton **$4,770,300,000**.
- `MAX(backlog_value)` sin filtro de año elige FY2023 en las dos compañías y
  es falla.
- Poner el conteo sintético y el valor reportado en la misma fila sin
  normalizar `unit_scale` es exactamente la falla de la línea base y sigue
  siendo falla.

### Agrupación antes de clasificar

Las 25 corridas se agrupan por **string exacto de SQL** antes de clasificar. Se
clasifica una vez por SQL distinto, no 25 veces. El número de SQL distintos por
pregunta se reporta como resultado por derecho propio.

---

## Predicciones escritas antes de correr

### Predicción 1 — Iker (Claude chat)

Versión original, antes de ver el análisis de Q2:

> Correctas de 1 a 2, ruidosas de 4 a 1, silenciosas de 1 a 2 o 3. Tesis: el
> sistema se vuelve más útil y más peligroso al mismo tiempo.

Actualizada tras leer la predicción 2 y alineada con ella: **1 o 2 correctas,
0 o 1 ruidosas, 3 o 4 silenciosas.**

### Predicción 2 — Claude Code (esta sesión)

**1 correcta, 0 o 1 ruidosa, 3 o 4 silenciosas.**

Las ruidosas se van a ~0, no a 1. Cada literal que la línea base adivinó mal
—`'Lennar Corporation'`, `'TX'`, `'closed'`, `'DHI'`— ahora está en el prompt
textual. No queda de qué morirse temprano.

Y eso deja las consultas llegando **por primera vez** a las trampas #7
(fan-out, Q4), #3 (calendario fiscal, Q1 y Q3) y #1 (`unit_scale`, Q5). Las
tres tienen un modo de falla silencioso por construcción: devuelven un número
de aspecto sano.

### Predicción 3 — la de Q2, y es la que más me interesa

**La inyección de valores crea una ambigüedad nueva que el DDL puro no tenía.**

Q2 pregunta por Texas. Ahora el modelo ve las dos columnas al mismo tiempo:

| | comunidades | casas |
|---|---|---|
| `region = 'Texas'` | **2** | **79** |
| `state = 'TX'` | **4** | **149** |

Las dos son literales válidos que aparecen textualmente en el prompt, las dos
devuelven filas, y ninguna devuelve `NULL` ni cero. En la línea base esto era
**imposible**: `'Texas'` no existía en ninguna columna visible, el modelo
escribió `state = 'Texas'` y la consulta murió en cero. La falla se delataba
sola.

**Predigo que al menos una de las 5 corridas de Q2 en config B agarra
`region`**, y devuelve una tabla de aspecto perfectamente sano con el conjunto
equivocado.

Si eso pasa, la conclusión es más fuerte que la tesis de la predicción 1: no es
solo que el sistema se vuelva más útil y más peligroso al mismo tiempo. Es que
**la inyección de valores es ella misma una fuente nueva de fallas silenciosas**,
no nada más un destapador de las que ya estaban. El arreglo introduce una clase
de falla que el problema original no tenía.

---

## Marcador

Todo lo de aquí para abajo se escribió después de correr. Los criterios, las
cifras de referencia y las predicciones de arriba ya estaban en disco.

**Por pregunta: 2 correctas, 0 ruidosas, 3 silenciosas.**

**Por SQL distinto (24 de 25): 8 correctas, 0 ruidosas, 16 silenciosas.**

| # | SQL distintos | Categoría | Devolvió |
|---|---|---|---|
| 1 | 5 de 5 | **correcta ×4**, silenciosa ×1 | `169900` ×4 |
| 2 | 4 de 5 | **correcta ×4 (5/5 corridas)** | `97` |
| 3 | 5 de 5 | silenciosa ×5 | `455129.41` ×4, `458981.31` ×1 |
| 4 | 5 de 5 | silenciosa ×5 | `14388050000`, `400` |
| 5 | 5 de 5 | silenciosa ×5 | ver abajo |

### Contra el brazo de control

| | config A (DDL puro) | config B (con valores) |
|---|---|---|
| Correctas (por pregunta) | 0 | **2** |
| Ruidosas | 4 | **0** |
| Silenciosas | 1 | **3** |
| Correctas (por SQL distinto) | 0 / 25 | **8 / 24** |
| Ruidosas | 22 / 25 | **0 / 24** |
| Silenciosas | 3 / 25 | **16 / 24** |

**Las fallas ruidosas se fueron a cero. Las silenciosas se quintuplicaron.**

---

## El marcador de predicciones

| | Correctas | Ruidosas | Silenciosas | ¿Acertó? |
|---|---|---|---|---|
| Iker, original | 1–2 | 1 | 2–3 | 2 de 3 |
| Iker, actualizada | 1–2 | 0–1 | 3–4 | **3 de 3** |
| Claude Code | 1 | 0–1 | 3–4 | 2 de 3 |
| **Medido** | **2** | **0** | **3** | |

La predicción actualizada de Iker acertó las tres casillas. La mía subestimó
las correctas: dije 1, fueron 2. La tesis de fondo —"el sistema se vuelve más
útil y más peligroso al mismo tiempo"— quedó confirmada en la dirección y en la
magnitud.

### La predicción 3 falló

**Las 5 corridas de Q2 usaron `state = 'TX'`. Ninguna usó `region = 'Texas'`.**

Predije que al menos una agarraría `region` y produciría una falla silenciosa
nueva. No pasó, y Q2 fue la única pregunta que salió **correcta en las 5
corridas**, con el conteo de 97 exacto.

Vale la pena decir por qué falló, porque el razonamiento estaba invertido. Yo
supuse que meter `'Texas'` en el prompt como valor de `region` crearía una
competencia con `state`. Lo que pasó es lo contrario: el bloque de valores
**resolvió** el mapeo Texas→TX, que es justo donde config A moría
(`state = 'Texas'`, cero filas, 5/5). Ver `'TX'` listado bajo una columna
llamada `state` es una señal más fuerte que ver `'Texas'` listado bajo una
llamada `region`.

Lo que **no** se puede concluir es que la ambigüedad no exista. Sigue ahí en la
estructura de los datos —`region='Texas'` son 79 casas y `state='TX'` son
149— y no se disparó con este modelo, esta redacción y N=5. Es una predicción
fallida, no una hipótesis refutada.

---

## Hallazgo 1 — Q4: la misma pregunta, de ruidosa a silenciosa

**Es la demostración más limpia de todo el experimento.** Misma pregunta, mismo
modelo, misma base, mismo N. Lo único que cambió fue el bloque de valores.

| | config A | config B |
|---|---|---|
| Corridas | 5 | 5 |
| Presupuesto reportado | `NULL` (o cero filas) | **$14,388,050,000** |
| Casas reportadas | `0` | **400** |
| Presupuesto real | $348,500,000 | $348,500,000 |
| Categoría | **ruidosa 5/5** | **silenciosa 5/5** |

El error es de **41.3x**, que es exactamente el promedio de casas por comunidad
de D.R. Horton (40 casas, 10 comunidades): el fan-out de la trampa #7 replicando
`budget_usd` una vez por casa.

En config A el modelo escribía `SUM(c.budget_usd)` sobre un `LEFT JOIN homes`
—o sea, el fan-out ya estaba— pero el `WHERE co.name = 'D.R. Horton'` no
casaba con nada y todo se caía a `NULL`. **La adivinanza del literal estaba
tapando la trampa.** Al arreglar el literal, la trampa quedó expuesta y el
resultado dejó de delatarse.

Esto es exactamente lo que la línea base había predicho por reconstrucción
manual: corrió el SQL del modelo con el nombre corregido a mano y obtuvo
$14,388,050,000. Config B lo produjo de verdad, sin intervención, 5 de 5 veces.

Las 400 casas, en cambio, están bien. La consulta devuelve una cifra correcta y
una inflada 41x, lado a lado, sin nada que las distinga.

## Hallazgo 2 — Q3: el valor estaba en el prompt y no se usó

`companies.fiscal_year_end` es TEXT con 2 valores distintos, así que entró
completo al prompt: `'09-30'`, `'11-30'`. Es **el único lugar del esquema donde
existe la información del cierre fiscal**, y estaba ahí, listado.

**Ninguna de las 5 corridas lo usó.**

| Corridas | Ventana aplicada | Resultado | Correcto |
|---|---|---|---|
| 4 de 5 | ninguna | 455,129.41 sobre todos los años | 459,127.12 |
| 1 de 5 | año calendario 2024 | 458,981.31 | 459,127.12 |

La corrida 1 llegó a escribir `h.closing_date >= '2024-01-01' AND < '2025-01-01'`:
entendió que hacía falta una ventana temporal, y eligió el año calendario
teniendo `'11-30'` listado en el prompt. Las otras cuatro colgaron un
`JOIN financials ... WHERE f.fiscal_year = 2024` que no filtra ni una casa,
solo multiplica filas.

**Inyectar el valor no hizo que se usara.** La trampa #3 sobrevivió intacta a
la rebanada 2. Es la evidencia más clara de que el problema de los literales y
el problema del razonamiento sobre el esquema son dos cosas distintas, y que
esta rebanada solo resuelve el primero.

Las tres cifras se parecen: 455,129 / 458,981 / 459,127. Menos de 1% de
diferencia entre la peor y la correcta. Ninguna se delata.

## Hallazgo 3 — Q5: el fan-out y `unit_scale` siguen intactos

Las 5 corridas fallaron, todas en silencio, por dos vías:

**Tres corridas (2, 4, 5) y la 1** acertaron el conteo —51 y 52— pero
devolvieron **cuatro filas**, dos por compañía, una por año fiscal, sin columna
de año:

```
company              backlog_homes  backlog_value
Lennar Corporation   51             5372784.0
Lennar Corporation   51             6633750.0
D.R. Horton, Inc.    52             4770.3
D.R. Horton, Inc.    52             5923.3
```

Sin `unit_scale` aplicado. Lennar está en miles y D.R. Horton en millones: se
leen como 1,120x de diferencia cuando la real es 1.12x. **Trampa #1 intacta.**
Y sin saber qué fila es de qué año, no se puede ni elegir. `unit_scale` tiene 2
valores distintos y entró completo al prompt (`'millions'`, `'thousands'`);
ninguna corrida lo tocó.

**La corrida 3** hizo fan-out puro:

```
company              backlog_homes_count  backlog_value
D.R. Horton, Inc.    104                  556067.2
Lennar Corporation   102                  612333234.0
```

102 y 104 son 51×2 y 52×2: cada casa duplicada por las dos filas de
`financials`. Y `SUM(backlog_value)` sobre el mismo fan-out da 51 × (6,633,750
+ 5,372,784) = 612,333,234 y 52 × (5,923.3 + 4,770.3) = 556,067.2. Verificado
contra la base. Es la misma falla de la línea base, con dos filas limpias y
ordenadas alfabéticamente.

## Hallazgo 4 — la única falla silenciosa de Q1

Cuatro corridas dieron 169,900, que es correcto bajo la lectura de casas. La
quinta (corrida 4) colgó `homes` de `financials`:

```
ticker  fiscal_year  total_vendido
DHI     2024         129435000.0
LEN     2024         139856000.0
```

Verificado: ésos son los `SUM(sale_price)` de **todas** las casas de cada
compañía, de todos los años y todos los status, presentados bajo la etiqueta
`fiscal_year = 2024`. El `WHERE f.fiscal_year = 2024` no filtró ninguna casa.

Es la trampa #8 en vivo: cruzó la muestra sintética de ~800 casas con la tabla
de cifras reportadas al regulador. La cifra de $139.9M para Lennar contra los
$35.4 mil millones reales del 10-K difiere por un factor de 253, y nada en la
salida lo dice.

## Hallazgo 5 — la inestabilidad no bajó

| Pregunta | SQL distintos config A | config B |
|---|---|---|
| Q1 | 5 / 5 | 5 / 5 |
| Q2 | 5 / 5 | **4 / 5** |
| Q3 | 5 / 5 | 5 / 5 |
| Q4 | 5 / 5 | 5 / 5 |
| Q5 | 5 / 5 | 5 / 5 |

24 SQL distintos en 25 corridas. Q2 fue la única donde dos corridas coincidieron
byte por byte, y es también la única que salió correcta 5/5: es la pregunta con
menos grados de libertad una vez que los literales están dados.

**Pero la categoría sí se estabilizó.** En config A, Q5 se repartió 3
silenciosas / 2 ruidosas según una mayúscula. En config B las 25 corridas caen
en una sola categoría por pregunta (salvo Q1, 4 correctas / 1 silenciosa). Con
los literales dados, el modelo deja de tener de qué caerse por accidente y sus
fallas se vuelven **consistentes**. Un error reproducible es más peligroso que
uno intermitente: pasa cualquier prueba de humo que se corra dos veces.

---

## Qué significa

**La rebanada 2 hizo exactamente lo que tenía que hacer y el resultado es peor
de lo que se veía.**

Cumplió su objetivo declarado: el 80% de las consultas ya no muere adivinando
strings. De 22 fallas ruidosas sobre 25 SQL distintos se pasó a 0. El sistema
ahora contesta.

Y por eso mismo: **de 3 fallas silenciosas se pasó a 16.** Las consultas que
antes morían temprano ahora llegan hasta el final, se topan con las trampas que
nunca habían tocado, y devuelven tablas de aspecto profesional con cifras
infladas 41x, promedios corridos por medio año fiscal y valores en dos escalas
monetarias distintas presentados como si fueran comparables.

Un usuario que hubiera corrido config A habría visto `NULL` cuatro de cinco
veces y no habría confiado en el sistema. Uno que corra config B recibe cinco
respuestas, dos correctas y tres con números convincentes y equivocados, y no
tiene forma de distinguirlas.

**Esto es lo que justifica la rebanada 3.** Y confirma la nota del ROADMAP sobre
los guardrails: la validación de esquema no habría cazado ni una sola de estas
16 fallas silenciosas. `SUM(budget_usd)` sobre un join con `homes` es SQL
perfectamente válido: las tablas existen, las columnas existen, los tipos
cuadran. Lo que está mal es el grano de la agregación, y eso ninguna validación
de esquema lo ve.

---

## Costo

| | Entrada | Salida | Razonamiento | Costo |
|---|---|---|---|---|
| Q1 (5 corridas) | 4,965 | 448 | 0 | $0.001553 |
| Q2 (5 corridas) | 4,905 | 212 | 0 | $0.001246 |
| Q3 (5 corridas) | 4,955 | 535 | 0 | $0.001660 |
| Q4 (5 corridas) | 4,945 | 383 | 0 | $0.001468 |
| Q5 (5 corridas) | 4,930 | 579 | 0 | $0.001710 |
| **Total** | **24,700** | **2,157** | **0** | **$0.007636** |

`reasoning_tokens` fue **0 en las 25 llamadas**.

El bloque de valores costó **2.66x en tokens de entrada** contra config A (988
por llamada contra 371). Los de salida quedaron casi iguales (2,157 contra
2,001): el prompt más largo no produjo SQL más largo.

**Costo total de la rebanada 2, las 50 llamadas: $0.011992.** Estimado antes de
correr: $0.0125, rango $0.011–$0.016.

Precio aplicado: $0.20 por millón de entrada, $1.25 de salida. **Advertencia
heredada de la línea base:** esos precios se tomaron de páginas públicas de
terceros, no de una factura. Los conteos de tokens vienen del campo `usage` de
la API y son exactos; los dólares pueden estar mal por un factor constante.

---

## Qué no se verificó en esta corrida

- **N=5 sigue siendo poco.** Ninguna proporción de este archivo tiene un
  intervalo de confianza calculado. "5 de 5" con N=5 no es lo mismo que
  determinismo.
- **Un solo modelo, un solo esfuerzo de razonamiento, una sola redacción de
  cada pregunta.** Nada de esto se probó en otro modelo ni con paráfrasis.
- **Un solo umbral de cardinalidad.** El 20 no se comparó contra 10, 50 ni
  contra listar todo. No se sabe si el umbral importa.
- **`fiscal_year` sigue sin listarse** por la regla de llaves. Todas las
  corridas escribieron `fiscal_year = 2024` adivinando, y le atinaron. Es
  adivinanza de literal que no falló, no adivinanza eliminada.
- **La regla de columnas numéricas no se midió, se decidió.** No se corrió una
  config con los números listados, así que no hay evidencia de qué habría
  pasado. La decisión se tomó para proteger la atribución de la trampa #1, y
  ese razonamiento no está verificado empíricamente.
- **Las trampas #2 y #6 siguen sin probarse.** Ninguna pregunta obligó al
  modelo a aplicar `unit_scale` a un conteo ni a razonar sobre `closing_date`
  NULL.
- **La clasificación es de una sola persona**, contra criterios escritos antes
  pero sin segunda opinión independiente ni scoring automático. Eso es la
  rebanada 4.
- No se probó el flag `--model` ni el desenvolvedor `_unwrap`, que siguió sin
  ejercitarse: las 50 respuestas vinieron sin envolver.
