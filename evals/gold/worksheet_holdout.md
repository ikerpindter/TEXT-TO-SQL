# Worksheet ciega de etiquetado: holdout

Generada el 2026-07-30. 24 entradas del corpus real.

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

### HOLD-01

```sql
SELECT
  SUM(CASE WHEN c.name IN ('Lennar', 'D.R. Horton') THEN f.homes_delivered ELSE 0 END) AS total_homes_delivered_2024
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE f.fiscal_year = 2024
  AND c.name IN ('Lennar', 'D.R. Horton')
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-02

```sql
SELECT
  SUM(homes_delivered) AS total_homes_vendidos
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE f.fiscal_year = 2024
  AND c.name IN ('Lennar', 'D.R. Horton')
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-03

```sql
SELECT COUNT(*) AS houses_sold
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

### HOLD-04

```sql
SELECT
  AVG(h.sale_price) AS avg_sale_price
FROM companies c
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
JOIN financials f ON f.company_id = c.id
WHERE c.name = 'Lennar'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.closing_date IS NOT NULL
  AND strftime('%Y', h.closing_date) = '2024'
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-05

```sql
WITH lennar AS (
  SELECT id
  FROM companies
  WHERE ticker = 'LEN'
)
SELECT AVG(h.sale_price) AS avg_sale_price
FROM homes h
JOIN communities c ON c.id = h.community_id
JOIN lennar l ON l.id = c.company_id
JOIN financials f ON f.company_id = c.company_id
WHERE h.status = 'closed'
  AND f.fiscal_year = 2024
  AND h.closing_date IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-06

```sql
SELECT
  c.id AS company_id,
  c.name AS company_name,
  SUM(CASE WHEN h.status = 'Backlog' THEN 1 ELSE 0 END) AS homes_in_backlog,
  f.backlog_value AS backlog_value
FROM companies c
JOIN communities cm ON cm.company_id = c.id
JOIN homes h ON h.community_id = cm.id
JOIN financials f ON f.company_id = c.id
GROUP BY c.id, c.name, f.backlog_value
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-07

```sql
SELECT
  c.name AS company,
  COUNT(CASE WHEN h.status = 'backlog' THEN 1 END) AS backlog_homes,
  f.backlog_value AS backlog_value
FROM companies c
JOIN communities com
  ON com.company_id = c.id
JOIN homes h
  ON h.community_id = com.id
JOIN financials f
  ON f.company_id = c.id
GROUP BY
  c.id,
  c.name,
  f.backlog_value
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-08

```sql
SELECT COUNT(*) AS sold_houses_count
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

### HOLD-09

```sql
SELECT
  SUM(COALESCE(homes_delivered, 0)) AS total_homes_vendidas_2024
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE c.ticker IN ('LEN', 'DHI')
  AND f.fiscal_year = 2024
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-10

```sql
SELECT
  c.company_id,
  SUM(c.budget_usd) AS total_presupuesto_usd,
  COUNT(h.id) AS total_casas
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.name = 'D.R. Horton'
GROUP BY c.company_id
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-11

```sql
SELECT
  c.name AS company_name,
  SUM(co.budget_usd) AS total_community_budget_usd,
  COUNT(h.id) AS total_homes
FROM companies c
JOIN communities co ON co.company_id = c.id
LEFT JOIN homes h ON h.community_id = co.id
WHERE c.ticker = 'DHI'
GROUP BY c.name
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-12

```sql
SELECT
  SUM(c.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS total_homes_count
FROM companies co
JOIN communities c ON c.company_id = co.id
LEFT JOIN homes h ON h.community_id = c.id
WHERE co.name = 'D.R. Horton, Inc.'
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-13

```sql
SELECT
  c.budget_total_usd AS presupuesto_total_usd,
  c.homes_total AS casas_totales
FROM (
  SELECT
    SUM(comm.budget_usd) AS budget_total_usd,
    COUNT(h.id) AS homes_total
  FROM companies co
  JOIN communities comm ON comm.company_id = co.id
  LEFT JOIN homes h ON h.community_id = comm.id
  WHERE co.name = 'D.R. Horton'
) c
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-14

```sql
SELECT COUNT(*) AS sold_homes_texas
FROM homes
JOIN communities ON communities.id = homes.community_id
WHERE communities.state = 'Texas'
  AND homes.status = 'Sold'
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-15

```sql
WITH backlog_homes AS (
  SELECT
    c.id AS company_id,
    COUNT(*) AS backlog_count,
    SUM(f.backlog_value) AS backlog_value_total
  FROM homes h
  JOIN communities cm ON cm.id = h.community_id
  JOIN companies c ON c.id = cm.company_id
  LEFT JOIN financials f
    ON f.company_id = c.id
  WHERE h.status = 'backlog'
  GROUP BY c.id
)
SELECT
  co.name AS company,
  bh.backlog_count AS backlog_homes_count,
  bh.backlog_value_total AS backlog_value
FROM backlog_homes bh
JOIN companies co ON co.id = bh.company_id
ORDER BY co.name
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-16

```sql
SELECT
  c.name AS company,
  COUNT(*) AS homes_in_backlog,
  f.backlog_value AS backlog_value
FROM homes h
JOIN communities com ON com.id = h.community_id
JOIN companies c ON c.id = com.company_id
LEFT JOIN financials f ON f.company_id = c.id AND f.backlog_value IS NOT NULL
WHERE h.status = 'backlog'
GROUP BY c.id, c.name, f.backlog_value
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-17

```sql
SELECT
  SUM(
    CASE
      WHEN c.name IN ('Lennar Corporation', 'D.R. Horton, Inc.') THEN f.homes_delivered
      ELSE 0
    END
  ) AS total_homes_delivered_2024
FROM financials f
JOIN companies c ON c.id = f.company_id
WHERE f.fiscal_year = 2024
  AND c.name IN ('Lennar Corporation', 'D.R. Horton, Inc.')
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-18

```sql
WITH backlog_homes AS (
  SELECT
    c.id AS company_id,
    c.name AS company_name,
    f.backlog_value AS backlog_value,
    COUNT(*) AS backlog_homes_count
  FROM homes h
  JOIN communities cm ON cm.id = h.community_id
  JOIN companies c ON c.id = cm.company_id
  JOIN financials f ON f.company_id = c.id
  WHERE h.status = 'backlog'
  GROUP BY c.id, c.name, f.backlog_value
)
SELECT
  company_name,
  backlog_homes_count,
  backlog_value
FROM backlog_homes
ORDER BY company_name, backlog_value DESC
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-19

```sql
SELECT
  c.id AS company_id,
  c.name AS company_name,
  c.ticker,
  f.fiscal_year,
  f.homes_delivered AS houses_in_backlog,
  f.backlog_value
FROM companies c
JOIN financials f
  ON f.company_id = c.id
WHERE f.homes_delivered IS NOT NULL
  AND f.backlog_value IS NOT NULL
ORDER BY c.id, f.fiscal_year
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-20

```sql
SELECT
  AVG(h.sale_price) AS avg_sale_price
FROM homes h
JOIN communities c ON c.id = h.community_id
JOIN companies co ON co.id = c.company_id
JOIN financials f ON f.company_id = co.id
WHERE
  co.name = 'Lennar Corporation'
  AND h.status = 'closed'
  AND f.fiscal_year = 2024
  AND c.opened_date IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-21

```sql
SELECT AVG(h.sale_price) AS avg_sale_price_closed
FROM companies c
JOIN financials f ON f.company_id = c.id
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
WHERE c.name = 'Lennar Corporation'
  AND f.fiscal_year = 2024
  AND h.status = 'closed' AND h.sale_price IS NOT NULL
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-22

```sql
SELECT
  SUM(h.net_income) AS total_ventas
FROM companies c
JOIN financials h ON h.company_id = c.id
WHERE c.name IN ('Lennar', 'D.R. Horton')
  AND h.fiscal_year = 2024
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-23

```sql
SELECT
  c.name AS company,
  SUM(cu.budget_usd) AS total_budget_usd,
  COUNT(h.id) AS total_homes
FROM companies c
JOIN communities cu ON cu.company_id = c.id
JOIN homes h ON h.community_id = cu.id
WHERE c.name = 'D.R. Horton, Inc.'
GROUP BY c.name
```

```
LABEL:
SHAPE:
NOTA:
```

### HOLD-24

```sql
SELECT
  AVG(h.sale_price) AS avg_sale_price
FROM companies c
JOIN financials f ON f.company_id = c.id
JOIN communities com ON com.company_id = c.id
JOIN homes h ON h.community_id = com.id
WHERE c.name = 'Lennar Corporation'
  AND f.fiscal_year = 2024
  AND h.status = 'closed'
  AND h.closing_date >= '2024-01-01'
  AND h.closing_date < '2025-01-01'
```

```
LABEL:
SHAPE:
NOTA:
```
