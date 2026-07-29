# Config A: DDL puro, sin valores, N=5

**Este archivo está congelado. No se edita nunca.** Si cambia cualquier
variable —modelo, prompt, contenido del esquema, esfuerzo de razonamiento,
temperatura, las preguntas— el resultado va en un archivo nuevo.

Es el brazo de control de la rebanada 2. Se compara contra
[`values_text_maxcard20_n5.md`](values_text_maxcard20_n5.md), que corre las
mismas cinco preguntas con la misma configuración y **una sola diferencia**: el
bloque de valores anexado al esquema.

No reemplaza a [`baseline_ddl_only.md`](baseline_ddl_only.md), que sigue
congelado y sin tocar. Aquélla corrió N=1 y por eso no sirve para comparar
contra una corrida de N=5.

---

## Configuración exacta

| | |
|---|---|
| Fecha de la corrida | 2026-07-28 |
| Rebanada | 2 (inyección de valores) — brazo de control |
| Configuración | `ddl_only` |
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
| Esquema enviado | 980 chars, DDL puro |

Misma base, mismo sha256 y mismas cinco preguntas que la línea base. Lo único
que cambió contra `baseline_ddl_only.md` es N.

---

## Criterios de clasificación

**Escritos y guardados en disco antes de lanzar la primera llamada.** Sin esto,
clasificar a mano después de leer los resultados es como se cuelan los sesgos:
si decido *después* de ver el SQL si "vendidas" incluía el backlog, termino
aprobando lo que sea que el modelo haya hecho.

Tres categorías, excluyentes.

**Correcto.** El SQL corre sin error, devuelve al menos una fila, y todas las
cifras coinciden con la referencia bajo alguna de las lecturas admitidas.

**Falla ruidosa.** El resultado se delata solo, sin necesidad de saber la
respuesta. Cualquiera de: error de SQLite, cero filas, todas las columnas
agregadas en `NULL`, o un `0` donde la referencia dice que sí hay filas.

**Falla silenciosa.** El SQL corre, devuelve filas con valores no nulos, nada
en la salida indica que haya problema, y al menos una cifra no coincide con la
referencia.

**Desempate.** Si un resultado califica como ruidosa y silenciosa a la vez —una
fila con un `NULL` en una columna y una cifra mal en otra— gana **ruidosa**. Lo
que define la categoría es si el resultado se delata, y un `NULL` se delata.

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
pregunta se reporta como resultado por derecho propio: si la misma pregunta
produce SQL distinto entre corridas, eso es un hallazgo.

---

## Predicciones escritas antes de correr

### Predicción — Claude Code (esta sesión)

Config A debería reproducir la línea base: **4 fallas ruidosas, 1 silenciosa,
cero correctas.** Las cuatro ruidosas mueren adivinando literales de texto
antes de llegar a ninguna trampa.

Lo que esta corrida agrega sobre la línea base es la estabilidad, y ahí sí
predigo algo que N=1 no podía ver: **al menos 2 de las 5 preguntas van a
producir más de un SQL distinto entre las 5 corridas.** El default de la API no
es temperatura 0. Apuesto por Q1 y Q5 como las más inestables, que son las que
más libertad de formulación tienen.

Predicción secundaria: la *categoría* va a ser estable aunque el SQL no lo sea.
Es decir, variantes distintas de SQL que caen todas en la misma casilla. Si eso
no se cumple —si una misma pregunta da correcto en una corrida y falla en
otra— es un hallazgo más grande que cualquier otra cosa en este archivo.

---

## Marcador

Todo lo de aquí para abajo se escribió después de correr. Los criterios, las
cifras de referencia y las predicciones de arriba ya estaban en disco.

**Por pregunta: 4 ruidosas, 1 silenciosa, cero correctas.** Reproduce la línea
base exactamente.

**Por SQL distinto (25 de 25): 22 ruidosas, 3 silenciosas, cero correctas.**

| # | SQL distintos | Categoría | Devolvió |
|---|---|---|---|
| 1 | 5 de 5 | ruidosa ×5 | `NULL` |
| 2 | 5 de 5 | ruidosa ×5 | `0` |
| 3 | 5 de 5 | ruidosa ×5 | `NULL` |
| 4 | 5 de 5 | ruidosa ×5 | `NULL`,`0` ×4 y cero filas ×1 |
| 5 | 5 de 5 | **silenciosa ×3, ruidosa ×2** | ver abajo |

---

## Hallazgo 1 — las 25 corridas dieron 25 SQL distintos

**La agrupación por string exacto no agrupó absolutamente nada.**

| Pregunta | SQL distintos / corridas |
|---|---|
| Q1 | 5 / 5 |
| Q2 | 5 / 5 |
| Q3 | 5 / 5 |
| Q4 | 5 / 5 |
| Q5 | 5 / 5 |

Predije "al menos 2 de las 5 preguntas". Fueron las 5, sin una sola
repetición en 25 llamadas. La predicción acertó la dirección y se quedó corta
por mucho en la magnitud.

Buena parte de la variación es cosmética —alias distintos (`h` contra `com`
contra `cm`), nombres de columna de salida en español o en inglés— pero no
toda. Q2 es el caso extremo de variación puramente cosmética: las cinco
corridas escribieron la misma consulta con cinco alias de salida distintos
(`sold_homes_count`, `sold_homes_texas`, `sold_houses_count`, `houses_sold`,
`sold_houses`) y una diferencia de mayúscula en el literal.

Q1 en cambio varió de fondo: una corrida sumó `net_income` bajo el alias
`total_ventas`, tres sumaron `homes_delivered`, y una se fue a `homes.sale_price`
cruzando cuatro tablas. Cinco lecturas distintas de la misma pregunta.

**Consecuencia de método:** agrupar por SQL exacto, que era la instrucción de
esta rebanada para no clasificar 50 veces, resultó no ahorrar nada en config A.
El agrupamiento útil tendría que ser por plan de ejecución o por resultado, no
por texto. Se anota para la rebanada 4.

## Hallazgo 2 — la categoría NO fue estable, y es el resultado importante

Predije que la categoría sería estable aunque el SQL no lo fuera, y escribí
antes de correr que si eso fallaba sería el hallazgo más grande del archivo.
**Falló, en Q5.**

Las cinco corridas de Q5 se repartieron en dos categorías distintas, y lo que
decide de qué lado cae cada una es **una mayúscula**:

| Corrida | Literal de status | Resultado | Categoría |
|---|---|---|---|
| 1 | — (usó `financials`) | 4 filas, 73087/80210/82917/89690 | silenciosa |
| 2 | — (usó `financials`) | 4 filas, mismas cifras | silenciosa |
| 3 | `LOWER(status) IN ('backlog','in backlog')` | 4 filas, 51/52 | silenciosa |
| 4 | `status = 'Backlog'` | **cero filas** | ruidosa |
| 5 | `status = 'Backlog'` | 4 filas con conteo `0` | ruidosa |

En SQLite el `=` sobre texto distingue mayúsculas: `status='Backlog'` da 0
filas, `status='backlog'` da 103. La corrida 3 escribió `LOWER(status)` y por
eso acertó el conteo (51 y 52) sin saber que el valor era minúscula.

**La misma pregunta, el mismo prompt, el mismo modelo, cinco llamadas: dos
veces la falla se delata y tres veces no.** Un resultado con N=1 sobre esta
pregunta reporta una categoría u otra dependiendo del volado. La línea base
sacó "silenciosa" con una sola corrida; tenía 2 de 5 de probabilidad de haber
reportado "ruidosa" y de que el archivo dijera otra cosa.

Ésta es la respuesta directa a lo que la línea base dejó abierto en su sección
"Qué no se verificó": *"No se sabe qué tan estables son estas fallas entre
corridas."* Ahora se sabe: las de Q1 a Q4 son estables, la de Q5 no.

## Hallazgo 3 — un modo de falla silenciosa que la línea base no produjo

Dos de las cinco corridas de Q5 (1 y 2) resolvieron "cuántas casas tiene cada
compañía en backlog" leyendo **`financials.homes_delivered`**:

```
company_name        fiscal_year  houses_in_backlog  backlog_value
Lennar Corporation  2023         73087              6633750.0
Lennar Corporation  2024         80210              5372784.0
D.R. Horton, Inc.   2023         82917              5923.3
D.R. Horton, Inc.   2024         89690              4770.3
```

La respuesta correcta es 51 y 52. La consulta reporta 80,210 y 89,690, que son
**casas entregadas en el año fiscal**, no casas en backlog. Error de tres
órdenes de magnitud, presentado en una tabla impecable: sin NULL, sin ceros,
con el año fiscal desglosado y los nombres legales correctos.

Nunca tocó la tabla `homes`. La línea base no produjo esta variante ni una vez.
Es **peor** que la falla silenciosa de la línea base: aquélla al menos contaba
casas reales (mal, 206 en vez de 103); ésta contesta con una columna que no
tiene ninguna relación con la pregunta.

## Hallazgo 4 — el resto reproduce la línea base

Q1 a Q4 murieron adivinando literales de texto, en las 20 corridas, igual que
la línea base:

| Pregunta | Literal adivinado | Corridas | Valor real |
|---|---|---|---|
| Q1 | `name IN ('Lennar', 'D.R. Horton')` | 5/5 | `'Lennar Corporation'`, `'D.R. Horton, Inc.'` |
| Q2 | `state = 'Texas'` | 5/5 | `'TX'` |
| Q2 | `status = 'Sold'` / `'sold'` | 5/5 | `closed`/`backlog`/`cancelled`/`available` |
| Q3 | `name = 'Lennar'` | 5/5 | `'Lennar Corporation'` |
| Q4 | `name = 'D.R. Horton'` | 5/5 | `'D.R. Horton, Inc.'` |
| Q5 | `status = 'Backlog'` | 2/5 | `'backlog'` |

Dos corridas de Q4 volvieron a comparar `ticker = 'D.R. Horton'`, igual que la
línea base. El ticker es `DHI`.

**El 80% de las consultas sigue muriendo antes de llegar a las trampas.** Es la
justificación de la rebanada 2, y N=5 la confirma en vez de debilitarla.

---

## Costo

| | Entrada | Salida | Razonamiento | Costo |
|---|---|---|---|---|
| Q1 (5 corridas) | 1,880 | 383 | 0 | $0.000855 |
| Q2 (5 corridas) | 1,820 | 212 | 0 | $0.000629 |
| Q3 (5 corridas) | 1,870 | 489 | 0 | $0.000985 |
| Q4 (5 corridas) | 1,860 | 439 | 0 | $0.000921 |
| Q5 (5 corridas) | 1,845 | 478 | 0 | $0.000967 |
| **Total** | **9,275** | **2,001** | **0** | **$0.004356** |

`reasoning_tokens` fue **0 en las 25 llamadas**, igual que en la línea base.

Precio aplicado: $0.20 por millón de entrada, $1.25 de salida. **Advertencia
heredada de la línea base:** esos precios se tomaron de páginas públicas de
terceros, no de una factura. Los conteos de tokens vienen del campo `usage` de
la API y son exactos; los dólares pueden estar mal por un factor constante.

Estimación antes de correr: $0.0045. Real: $0.004356.

---

## Qué no se verificó en esta corrida

- **N=5 sigue siendo poco.** Q5 se repartió 3/2 entre dos categorías; con 5
  muestras el intervalo alrededor de esa proporción es enorme. Que Q1 a Q4
  hayan salido 5/5 en la misma categoría tampoco prueba que sean deterministas.
- No se probaron otras formulaciones de las mismas preguntas. La inestabilidad
  medida es la del modelo ante un prompt fijo, no ante paráfrasis.
- El desenvolvedor de bloques markdown (`_unwrap`) siguió sin ejercitarse: las
  25 respuestas vinieron sin envolver.
- No se probó qué pasa si el modelo devuelve algo que no es un SELECT.
- Las tres trampas que la línea base no pudo probar (#2, #6, #8) siguen sin
  probarse, por la misma razón: las consultas mueren antes.
- La clasificación la hizo una persona leyendo el JSON contra criterios
  escritos antes. No hay scoring automático ni segunda opinión independiente.
