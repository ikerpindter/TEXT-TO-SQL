# Worksheet ciega de etiquetado: dev

Generada el 2026-07-30. 25 entradas del corpus real.

**Llena `LABEL:` y `SHAPE:` en cada bloque. No borres nada mas.**

Esta worksheet no muestra la pregunta, el indice de pregunta, la config,
el resultado ejecutado, la categoria, el row_count, ni el id del corpus.
Las claves son opacas a proposito: el id del corpus filtra la config.

El set adversario **no esta aqui** y nunca lo estara: trae su respuesta
declarada por diseno y vive en `corpus_sql_adversarial.json`.

Vocabulario de `LABEL:` -> not_analyzed, no_contributing_rows, clean, shape_no_inflation, inflated
Vocabulario de `SHAPE:` -> fan_trap, chasm_trap, unexplained, -

---

## Esquema completo de la base

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

---

## Criterio, resumido

**Fan-out** es una agregacion que cae sobre una columna del lado "uno" de un join
uno-a-muchos. El join replica esa fila una vez por cada fila del lado "muchos", y la
agregacion suma el mismo valor varias veces.

Estas juzgando **si el SQL infla por duplicacion de filas**. NO estas juzgando si el
query contesta bien la pregunta: no sabes cual era la pregunta, y es a proposito.

### Los cinco veredictos, en orden de precedencia

| Veredicto | Cuando |
|---|---|
| `not_analyzed` | No se puede analizar: self join, window function, UNION/INTERSECT/EXCEPT, join que no sigue una FK declarada, o columna ambigua. |
| `no_contributing_rows` | La tabla agregada no aporta ni una fila a la fuente. El multiplicador es indefinido. |
| `clean` | Analizable y sin forma de fan-out presente. |
| `shape_no_inflation` | La forma esta presente pero no duplica: el multiplicador es 1.0. |
| `inflated` | La forma esta presente y duplica. |

**El primero que aplica gana.** Si hay varios hallazgos, manda el peor caso.

### Las dos formas

- `fan_trap`: se agrega una columna del lado "uno" despues de unir al lado "muchos".
- `chasm_trap`: dos ramas uno-a-muchos desde un ancestro comun, unidas entre si.
  **Las ramas pueden tener mas de un salto.**
- `unexplained`: hay duplicacion pero no encaja limpio en ninguna de las dos.
- `-`: sin forma. Va con `clean` y con `not_analyzed`.

### Reglas que no dependen de juicio

- Cualquier agregado con `DISTINCT` es inmune. Tambien `MAX` y `MIN`.
- Sensibles a duplicacion: `SUM`, `AVG`, `COUNT` sin DISTINCT, `TOTAL`.
- Una query **sin agregados** no tiene forma: va `clean`.
- "Forma presente" exige **las dos cosas juntas**: la estructura de joins **y** un
  agregado sensible sobre una columna afectada.
- Un CTE que pre-agrega a una fila por llave **no duplica**.

### Si dudas

Escribe la etiqueta que creas y agrega una nota en la linea `NOTA:`. Un desacuerdo
registrado vale mas que una etiqueta forzada. **No se promedian los desacuerdos.**

---

## Casos

### DEV-01

```sql
SELECT COUNT(*) AS houses_sold_in_texas
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'TX'
  AND h.status = 'closed'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-02

```sql
SELECT COUNT(*) AS sold_houses
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'Texas'
  AND h.status = 'sold'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-03

```sql
SELECT
  COALESCE(SUM(homes_delivered), 0) AS total_homes_delivered_2024
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE f.fiscal_year = 2024
  AND c.ticker IN ('LEN', 'DHI')
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-04

```sql
SELECT
  SUM(homes_delivered) AS total_homes_delivered
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE c.name IN ('Lennar', 'D.R. Horton')
  AND f.fiscal_year = 2024
  AND f.homes_delivered IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-05

```sql
SELECT
  c.id AS company_id,
  c.name AS company_name,
  f.fiscal_year AS fiscal_year,
  f.homes_delivered AS backlog_homes,
  f.backlog_value AS backlog_value
FROM companies c
JOIN financials f
  ON f.company_id = c.id
ORDER BY c.id, f.fiscal_year
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-06

```sql
SELECT
  SUM(c.budget_usd) AS total_presupuesto_usd,
  COUNT(h.id) AS total_casas
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.name = 'D.R. Horton'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-07

```sql
SELECT
  SUM(h.sale_price) AS total_venta_2024
FROM homes h
JOIN communities c ON c.id = h.community_id
JOIN companies co ON co.id = c.company_id
JOIN financials f ON f.company_id = co.id
WHERE co.name IN ('Lennar', 'D.R. Horton')
  AND f.fiscal_year = 2024
  AND h.status IN ('Sold', 'Closed')
  AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-08

```sql
SELECT
  c.name AS company_name,
  COUNT(h.id) AS backlog_homes_count,
  f.backlog_value AS backlog_value
FROM companies c
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
LEFT JOIN financials f ON f.company_id = c.id
WHERE h.status = 'backlog'
GROUP BY c.id, f.backlog_value
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-09

```sql
SELECT COUNT(*) AS sold_homes_count
FROM homes
JOIN communities ON communities.id = homes.community_id
WHERE communities.state = 'TX'
  AND homes.status = 'closed'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-10

```sql
SELECT
  c.ticker,
  f.fiscal_year,
  SUM(h.sale_price) AS total_vendido
FROM companies c
JOIN financials f ON f.company_id = c.id
JOIN communities cm ON cm.company_id = c.id
JOIN homes h ON h.community_id = cm.id
WHERE c.ticker IN ('LEN', 'DHI')
  AND f.fiscal_year = 2024
GROUP BY c.ticker, f.fiscal_year
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-11

```sql
SELECT
  SUM(c.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS houses_count
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.ticker = 'DHI' AND co.name = 'D.R. Horton, Inc.'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-12

```sql
SELECT COUNT(*) AS sold_homes_count
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'Texas'
  AND h.status = 'Sold'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-13

```sql
WITH dr_horton AS (
  SELECT id
  FROM companies
  WHERE name = 'D.R. Horton' OR ticker = 'D.R. Horton'
),
community_budget AS (
  SELECT
    SUM(c.budget_usd) AS total_budget_usd,
    COUNT(h.id) AS total_houses
  FROM communities c
  JOIN dr_horton d ON d.id = c.company_id
  LEFT JOIN homes h ON h.community_id = c.id
)
SELECT total_budget_usd, total_houses
FROM community_budget
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-14

```sql
SELECT
  SUM(c.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS total_homes
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.ticker = 'DHI' OR co.name = 'D.R. Horton, Inc.'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-15

```sql
SELECT AVG(h.sale_price) AS avg_sale_price
FROM companies c
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
JOIN financials f ON f.company_id = c.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.closing_date IS NOT NULL
  AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-16

```sql
SELECT COUNT(*) AS sold_homes_count
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'TX' AND h.status = 'closed'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-17

```sql
SELECT COUNT(*) AS sold_houses_count
FROM homes h
JOIN communities c ON c.id = h.community_id
WHERE c.state = 'TX' AND h.status = 'closed'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-18

```sql
SELECT AVG(h.sale_price) AS avg_sale_price
FROM companies c
JOIN communities comm ON comm.company_id = c.id
JOIN homes h ON h.community_id = comm.id
JOIN financials f ON f.company_id = c.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.closing_date IS NOT NULL
  AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-19

```sql
SELECT AVG(h.sale_price) AS avg_sale_price_closed
FROM companies c
JOIN communities cm ON cm.company_id = c.id
JOIN homes h ON h.community_id = cm.id
JOIN financials f ON f.company_id = c.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'Closed'
  AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-20

```sql
SELECT
  SUM(c.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS total_homes
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.name = 'D.R. Horton' OR co.ticker = 'D.R. Horton'
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-21

```sql
SELECT
  AVG(h.sale_price) AS avg_sale_price
FROM companies c
JOIN communities cm ON cm.company_id = c.id
JOIN homes h ON h.community_id = cm.id
JOIN financials f ON f.company_id = c.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-22

```sql
SELECT
  c.id AS company_id,
  c.name AS company_name,
  f.backlog_value AS backlog_value,
  COUNT(h.id) AS houses_in_backlog
FROM companies c
JOIN communities cm
  ON cm.company_id = c.id
JOIN homes h
  ON h.community_id = cm.id
JOIN financials f
  ON f.company_id = c.id
WHERE LOWER(h.status) IN ('backlog', 'in backlog')
GROUP BY c.id, c.name, f.backlog_value
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-23

```sql
WITH joined AS (
  SELECT
    f.company_id,
    c.name,
    f.fiscal_year,
    f.net_income,
    f.revenues,
    f.homes_delivered
  FROM financials f
  JOIN companies c ON c.id = f.company_id
  WHERE c.name IN ('Lennar Corporation', 'D.R. Horton, Inc.')
)
SELECT
  SUM(homes_delivered) AS total_homes_vendidas
FROM joined
WHERE fiscal_year = 2024
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-24

```sql
WITH lennar AS (
  SELECT id
  FROM companies
  WHERE name = 'Lennar Corporation'
),
closed_homes_2024 AS (
  SELECT
    h.sale_price
  FROM homes h
  JOIN communities c ON c.id = h.community_id
  JOIN lennar l ON l.id = c.company_id
  JOIN financials f ON f.company_id = l.id
  WHERE h.status = 'closed'
    AND f.fiscal_year = 2024
)
SELECT AVG(sale_price) AS avg_sale_price
FROM closed_homes_2024
WHERE sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### DEV-25

```sql
SELECT
  c.name AS company_name,
  COUNT(h.id) AS houses_in_backlog,
  SUM(f.backlog_value) AS total_backlog_value
FROM companies c
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
LEFT JOIN financials f ON f.company_id = c.id
WHERE h.status = 'Backlog'
GROUP BY c.id, c.name
```

```
LABEL:
SHAPE:
NOTA:
```
