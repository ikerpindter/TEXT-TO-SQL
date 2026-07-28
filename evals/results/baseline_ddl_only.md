# Línea base: esquema en DDL puro, sin valores

**Este archivo está congelado. No se edita nunca.** Si cambia cualquier
variable —modelo, prompt, contenido del esquema, esfuerzo de razonamiento,
temperatura, las preguntas— el resultado va en un archivo nuevo. Editar éste
destruye la comparación que hace que el resultado signifique algo.

---

## Configuración exacta

| | |
|---|---|
| Fecha de la corrida | 2026-07-28 |
| Rebanada | 1 (el esqueleto) |
| Modelo solicitado | `gpt-5.4-nano` |
| Modelo que resolvió la API | `gpt-5.4-nano-2026-03-17` |
| API | Responses API (`client.responses.create`) |
| Esfuerzo de razonamiento | **default de la API** — no se fijó `reasoning={"effort": ...}` |
| `reasoning_tokens` observados | **0 en las cinco llamadas** |
| `store` | `False` |
| Temperatura | no se fijó |
| `max_output_tokens` | no se fijó |
| Reintentos | ninguno. Una llamada por pregunta |
| Base de datos | `data/portfolio.db`, sha256 `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762` |
| Filas | companies 2, financials 4, communities 20, homes 794 |

### Qué recibió el modelo

El esquema se introspecciona con `PRAGMA table_info` y se manda como DDL
reconstruido. **Sin comentarios, sin filas de ejemplo, sin valores distintos,
sin cardinalidades.** Ésta es la variable que define esta línea base y es la
razón del nombre del archivo.

```sql
CREATE TABLE companies (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  ticker TEXT NOT NULL,
  fiscal_year_end TEXT NOT NULL
);

CREATE TABLE financials (
  company_id INTEGER NOT NULL,
  fiscal_year INTEGER NOT NULL,
  revenues REAL,
  net_income REAL,
  homes_delivered INTEGER,
  backlog_value REAL,
  unit_scale TEXT NOT NULL,
  PRIMARY KEY (company_id, fiscal_year),
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE communities (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  state TEXT NOT NULL,
  opened_date TEXT NOT NULL,
  lot_count INTEGER NOT NULL,
  budget_usd REAL NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE homes (
  id INTEGER PRIMARY KEY,
  community_id INTEGER NOT NULL,
  list_price REAL NOT NULL,
  sale_price REAL,
  contract_date TEXT,
  closing_date TEXT,
  status TEXT NOT NULL,
  FOREIGN KEY (community_id) REFERENCES communities(id)
);
```

Instrucciones y plantilla de la pregunta: ver `SYSTEM_PROMPT` y
`USER_TEMPLATE` en `src/txt2sql/generate.py` en el commit que acompaña a este
archivo.

---

## Marcador

**4 fallas ruidosas, 1 falla silenciosa. Cero correctas.**

| # | Categoría | Devolvió |
|---|---|---|
| 1 | falla ruidosa | `NULL` |
| 2 | falla ruidosa | `0` |
| 3 | falla ruidosa | `NULL` |
| 4 | falla ruidosa | `NULL`, `0` |
| 5 | **falla silenciosa** | tabla con datos de apariencia plausible |

Definiciones usadas: **ruidosa** = el resultado se delata solo (NULL, cero
filas, error). **Silenciosa** = devuelve un número plausible que está mal.

---

## Las cinco preguntas

### Q1 — "¿Cuánto vendieron en total Lennar y D.R. Horton juntos en su año fiscal 2024?"

```sql
SELECT
  SUM(h.homes_sold) AS total_homes_vendidos
FROM (
  SELECT
    c.id AS company_id,
    COALESCE(SUM(f.homes_delivered), 0) AS homes_sold
  FROM companies c
  JOIN financials f
    ON f.company_id = c.id
  WHERE c.name IN ('Lennar', 'D.R. Horton')
    AND f.fiscal_year = 2024
  GROUP BY c.id
) h
```

Resultado: `NULL` (1 fila). 375 tok entrada + 108 salida, $0.000210.

**Categoría: falla ruidosa.** Adivinó los literales de `name`; la tabla guarda
`'Lennar Corporation'` y `'D.R. Horton, Inc.'`. Cero filas.

Trampa asignada: #1 y #3. **Ninguna se probó** — la consulta murió antes de
llegar a ellas. Además leyó "cuánto vendieron" como conteo de casas y no como
ingresos, lo cual es una ambigüedad de la pregunta, no un error del modelo.

Con los nombres corregidos habría dado 169,900 casas: correcto como conteo,
pero sumando dos años fiscales que no cubren el mismo periodo.

### Q2 — "¿Cuántas casas se han vendido en Texas?"

```sql
SELECT COUNT(*) AS sold_homes_count
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'Texas'
  AND h.status = 'sold'
```

Resultado: `0` (1 fila). 362 tok entrada + 43 salida, $0.000126.

**Categoría: falla ruidosa.** Dos literales adivinados, ambos inexistentes:
`status = 'sold'` (los valores son `closed`, `backlog`, `cancelled`,
`available`) y `state = 'Texas'` (la columna guarda `'TX'`).

Trampa asignada: #4. **No se probó.** El modelo sí intentó filtrar por status,
pero con un valor que no existe, así que nunca contó una fila `cancelled`.

### Q3 — "¿Precio promedio de venta de las casas cerradas en el año fiscal 2024 de Lennar?"

```sql
SELECT AVG(h.sale_price) AS avg_sale_price
FROM financials f
JOIN companies c ON c.id = f.company_id
JOIN communities cm ON cm.company_id = c.id
JOIN homes h ON h.community_id = cm.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.sale_price IS NOT NULL
```

Resultado: `NULL` (1 fila). 377 tok entrada + 89 salida, $0.000187.

**Categoría: falla ruidosa**, otra vez por `name`.

Trampas: **#5 pasa** — usó `sale_price` y no `list_price`. **#3 falla**, pero
de forma latente: no hay ninguna condición sobre `closing_date`. El
`f.fiscal_year = 2024` no filtra casas, solo multiplica filas.

Verificado corriendo el mismo SQL con el nombre corregido:

| | |
|---|---|
| SQL del modelo, sin ventana fiscal | 455,129 sobre 255 casas |
| Correcto, FY2024 = 2023-12-01 a 2024-11-30 | **459,127 sobre 118 casas** |
| Si hubiera usado año calendario 2024 | 458,981 |

El modelo promedió las casas cerradas de **todos** los años.

### Q4 — "¿Presupuesto total de las comunidades de D.R. Horton y cuántas casas tienen?"

```sql
SELECT
  SUM(c.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS total_homes
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.name = 'D.R. Horton' OR co.ticker = 'D.R. Horton'
```

Resultado: `NULL`, `0` (1 fila). 373 tok entrada + 78 salida, $0.000172.

**Categoría: falla ruidosa**, por `name`. (Nota: también comparó `ticker`
contra `'D.R. Horton'`, cuando el ticker es `DHI`.)

Trampa asignada: #7. **Falla, latente.** La estructura del fan-out está
completa. Con el nombre corregido:

| | |
|---|---|
| SQL del modelo | budget **$14,388,050,000**, casas 400 |
| Correcto | budget **$348,500,000**, casas 400 |
| | **inflado 41x** |

### Q5 — "¿Cuántas casas tiene cada compañía en backlog y cuál es su valor?"

```sql
SELECT
  c.id AS company_id,
  c.name AS company_name,
  SUM(CASE WHEN h.status = 'backlog' THEN 1 ELSE 0 END) AS homes_in_backlog,
  MAX(f.backlog_value) AS backlog_value
FROM companies c
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
LEFT JOIN financials f ON f.company_id = c.id
GROUP BY c.id, c.name
```

Resultado, 2 filas. 368 tok entrada + 103 salida, $0.000202.

```
company_id  company_name        homes_in_backlog  backlog_value
1           Lennar Corporation  102               6,633,750
2           D.R. Horton, Inc.   104               5,923.3
```

**Categoría: falla silenciosa.**

---

## El desarme de Q5

**Éste es el resultado más importante del archivo.** Es la única consulta que
devolvió datos, no se delató por ningún lado, y está mal de tres formas
apiladas. Ninguna es visible en la salida.

### Bug 1 — doble conteo por fan-out

Casas en backlog reales: **103** (Lennar 51, D.R. Horton 52).
El modelo reportó **102 + 104 = 206**.

El `LEFT JOIN financials` no tiene ninguna relación con `homes`, pero duplica
cada fila de casa una vez por cada año fiscal de la compañía. Hay 2 filas de
`financials` por compañía, entonces 103 × 2 = 206.

El reparto 102/104 en vez de 51/52 confirma la duplicación exacta.

### Bug 2 — `MAX(backlog_value)` eligió el año equivocado

No hay filtro de `fiscal_year`, así que `MAX` toma el valor más grande de los
dos años, que en ambas compañías resulta ser **FY2023**, no el más reciente.

| Compañía | FY2023 | FY2024 | MAX eligió |
|---|---|---|---|
| Lennar | 6,633,750 | 5,372,784 | FY2023 |
| D.R. Horton | 5,923.3 | 4,770.3 | FY2023 |

### Bug 3 — trampa #1 en carne viva

Las dos cifras salen lado a lado sin normalizar:

| Compañía | Valor mostrado | `unit_scale` | En USD |
|---|---|---|---|
| Lennar | 6,633,750 | thousands | $6,633,750,000 |
| D.R. Horton | 5,923.3 | millions | $5,923,300,000 |

Se leen como **1,120x de diferencia**. La diferencia real es **1.12x**. La
columna `unit_scale` está en el esquema que recibió el modelo y no se usó.

### Y encima, trampa #8

La fila junta en la misma línea 102 casas de una muestra sintética con el
backlog real reportado a la SEC. El backlog real de Lennar al 30 de noviembre
de 2024 son 11,633 casas, no 51. La fila completa no significa nada.

---

## Predicciones escritas antes de correr

### Predicción 1 — Claude chat (la de Iker)

> Falla 4 o 5 de las 8. Se cae en el fan-out del join (#7), en las escalas
> distintas (#1) y en el año fiscal (#3). NO se cae en cancelled (#4).

### Predicción 2 — Claude Code (la de esta sesión)

Falla 3 seguras (#7, #3, #1), 4 contando la #4 a 55%. Pasa #5, #6, #2, #8.
Señaló además que las trampas #2 y #8 no estaban bien cubiertas por las cinco
preguntas y que un "pasa" en ellas no sería evidencia de nada.

### Predicción 3 — el modo de falla alterno, misma sesión

> Como no ve el enum, lo más probable es que **adivine el literal** y escriba
> `WHERE status = 'sold'`, que no existe en la tabla y devuelve **cero filas**.
> Eso no es caer en la #4 ni esquivarla — es una tercera cosa, y ensucia la
> medición.

### Marcador

| # | Predicción 1 | Predicción 2 | Pasó |
|---|---|---|---|
| 7 | falla | falla | **falla** |
| 3 | falla | falla | **falla** |
| 1 | falla | falla | **falla** |
| 8 | — | pasa | **falla** |
| 5 | — | pasa | pasa |
| 4 | no falla | falla 55% | no se probó |
| 2 | — | no medible | no se probó |
| 6 | — | pasa | no se probó |

**Falló 4 de 8.**

La predicción 1 acertó el número ("4 o 5", fue 4) y las tres trampas que
nombró. La predicción 2 subestimó el total y se equivocó en la #8: la descartó
argumentando que ninguna pregunta empujaba al modelo a cruzar `homes` con
`financials`, y la Q5 lo hizo por iniciativa propia.

**La predicción 3 resultó ser el hallazgo dominante de la corrida**, y ninguna
de las dos predicciones principales la puso en el centro.

---

## Trampas que no se probaron, y por qué

### #2 — `unit_scale` aplicado a un conteo

No se probó, y **no era medible con este diseño**. Solo se puede fallar la #2
si primero se manejó la #1: hay que estar aplicando `unit_scale` para poder
aplicarlo mal a `homes_delivered`. El modelo ignoró `unit_scale` por completo,
así que nunca llegó. Esto se anticipó antes de correr.

### #4 — `status = 'cancelled'` sigue siendo una fila

No se probó. La Q2 sí intentó filtrar por status, pero con `'sold'`, un valor
inexistente. La consulta devolvió cero filas sin llegar a contar ninguna fila
cancelada. No es evidencia ni a favor ni en contra.

### #6 — `closing_date` NULL en backlog

No se probó de forma significativa. La Q3 filtró por `status = 'closed'`, lo
cual excluye el backlog por otra vía, y la Q5 nunca tocó `closing_date`.
Ninguna pregunta obligó al modelo a razonar sobre el NULL.

---

## El hallazgo que domina la corrida

**Cuatro de cinco consultas murieron adivinando literales de texto, no en las
trampas del dataset.**

El modelo recibe DDL puro. No tiene forma de saber que `status` vale
`closed`/`backlog`/`cancelled`/`available`, que `state` guarda `'TX'` y no
`'Texas'`, ni cuál es el nombre legal de cada compañía. Adivina, y falla.

| Pregunta | Literal adivinado | Valor real |
|---|---|---|
| Q1 | `name IN ('Lennar', 'D.R. Horton')` | `'Lennar Corporation'`, `'D.R. Horton, Inc.'` |
| Q2 | `status = 'sold'` | `closed` / `backlog` / `cancelled` / `available` |
| Q2 | `state = 'Texas'` | `'TX'` |
| Q3 | `name = 'Lennar'` | `'Lennar Corporation'` |
| Q4 | `name = 'D.R. Horton'`, `ticker = 'D.R. Horton'` | `'D.R. Horton, Inc.'`, `'DHI'` |

Esto **enmascaró** las trampas #1, #3 y #7. Las tres se confirmaron solo
corriendo las consultas del modelo con los literales corregidos, contra la
misma base y sin volver a llamar a la API.

Consecuencia para el diseño: mientras el 80% de las consultas mueran antes de
llegar a las trampas, un gold set sobre este prompt mide capacidad de adivinar
strings, no capacidad de razonar sobre un esquema.

---

## Costo

| Pregunta | Entrada | Salida | Razonamiento | Costo |
|---|---|---|---|---|
| Q1 | 375 | 108 | 0 | $0.000210 |
| Q2 | 362 | 43 | 0 | $0.000126 |
| Q3 | 377 | 89 | 0 | $0.000187 |
| Q4 | 373 | 78 | 0 | $0.000172 |
| Q5 | 368 | 103 | 0 | $0.000202 |
| **Total** | **1,855** | **421** | **0** | **$0.000897** |

Precio aplicado: $0.20 por millón de tokens de entrada, $1.25 por millón de
salida.

Estimación hecha antes de correr: $0.0009 a $0.0029. El real cayó en el piso
del rango porque `reasoning_tokens` fue 0 en las cinco llamadas.

**Advertencia sobre el precio:** los $0.20 / $1.25 se tomaron de páginas
públicas de terceros, no de una factura. Si la cuenta está en otro tier, todos
los costos de este archivo están mal por un factor constante. Los conteos de
tokens sí vienen del campo `usage` de la API y son exactos.

---

## Qué no se verificó en esta corrida

- Una sola corrida por pregunta, sin repeticiones. **No se sabe qué tan
  estables son estas fallas entre corridas.**
- El desenvolvedor de bloques markdown (`_unwrap` en `generate.py`) nunca se
  ejercitó: el modelo devolvió SQL sin envolver las cinco veces.
- No se probó qué hace el pipeline si el modelo devuelve algo que no es un
  SELECT. El modo `mode=ro` lo detendría, pero no se observó ocurriendo por la
  ruta del CLI.
- No se probó el flag `--model`.
- Las cinco preguntas se escribieron para cubrir las ocho trampas y solo
  ejercitaron cinco de ellas. La cobertura del gold set es trabajo de una
  rebanada posterior.
