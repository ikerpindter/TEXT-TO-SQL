# Procedencia de las cifras de `financials.csv`

Toda cifra de `financials.csv` sale de un 10-K presentado ante la SEC. Ninguna
está estimada, interpolada ni inventada. Esta es la única fuente de verdad
sobre de dónde salió cada número.

`financials.csv` no lleva columnas de fuente a propósito: es dato que el
sistema consume, y una columna que `build_db.py` ignorara se desincronizaría
en silencio el día que se corrija una cifra. Si corriges un valor allá,
corrige su fila aquí.

## Filings usados

| Clave | Compañía | Año fiscal | Periodo cubierto | Accession | Presentado |
|---|---|---|---|---|---|
| LEN-FY2023 | Lennar Corporation | FY2023 | 2022-12-01 → 2023-11-30 | 0001628280-24-002371 | 2024-01-26 |
| LEN-FY2024 | Lennar Corporation | FY2024 | 2023-12-01 → 2024-11-30 | 0001628280-25-002404 | 2025-01-23 |
| DHI-FY2023 | D.R. Horton, Inc. | FY2023 | 2022-10-01 → 2023-09-30 | 0000882184-23-000115 | 2023-11-17 |
| DHI-FY2024 | D.R. Horton, Inc. | FY2024 | 2023-10-01 → 2024-09-30 | 0000882184-24-000057 | 2024-11-19 |

Cada cifra se tomó del 10-K de su propio año fiscal, no de la columna
comparativa del año siguiente.

## Unidades declaradas por el emisor

| Compañía | Escala | Dónde lo dice |
|---|---|---|
| Lennar | miles de USD | Encabezado de los estados financieros: "(In thousands, except per share amounts)"; tablas de MD&A: "Dollar Value (In thousands)" |
| D.R. Horton | millones de USD | Encabezado del estado de resultados: "(In millions, except per share data)"; tablas de MD&A: "Value (In millions)" |

Esta diferencia es real, no fabricada. Es la trampa #1 del dataset.

## Cifra por cifra

### Lennar FY2023 — `LEN-FY2023`

| Campo | Valor | Sección del filing |
|---|---|---|
| revenues | 34,233,366 | Item 8, Consolidated Statements of Operations, línea "Total revenues", columna 2023. XBRL `us-gaap:Revenues`, periodo 2022-12-01/2023-11-30 |
| net_income | 3,938,511 | Item 8, Consolidated Statements of Operations, línea "Net earnings attributable to Lennar", columna 2023. XBRL `us-gaap:NetIncomeLoss` |
| homes_delivered | 73,087 | Item 7 MD&A, "Summary of Homebuilding Data" → tabla "Deliveries", fila "Total", columna Homes 2023. Incluye entregas de entidades no consolidadas |
| backlog_value | 6,633,750 | Item 7 MD&A, "Summary of Homebuilding Data" → tabla "Backlog", fila "Total", columna Dollar Value 2023, al 30 de noviembre de 2023 |

### Lennar FY2024 — `LEN-FY2024`

| Campo | Valor | Sección del filing |
|---|---|---|
| revenues | 35,441,452 | Item 8, Consolidated Statements of Operations, línea "Total revenues", columna 2024. XBRL `us-gaap:Revenues`, periodo 2023-12-01/2024-11-30 |
| net_income | 3,932,533 | Item 8, Consolidated Statements of Operations, línea "Net earnings attributable to Lennar", columna 2024. XBRL `us-gaap:NetIncomeLoss` |
| homes_delivered | 80,210 | Item 7 MD&A, "Summary of Homebuilding Data" → tabla "Deliveries", fila "Total", columna Homes 2024. Incluye entregas de entidades no consolidadas |
| backlog_value | 5,372,784 | Item 7 MD&A, "Summary of Homebuilding Data" → tabla "Backlog", fila "Total", columna Dollar Value 2024, al 30 de noviembre de 2024 |

### D.R. Horton FY2023 — `DHI-FY2023`

| Campo | Valor | Sección del filing |
|---|---|---|
| revenues | 35,460.4 | Item 8, Consolidated Statements of Operations, línea "Revenues", columna 2023. XBRL `us-gaap:Revenues`, periodo 2022-10-01/2023-09-30 |
| net_income | 4,745.7 | Item 8, Consolidated Statements of Operations, línea "Net income attributable to D.R. Horton, Inc.", columna 2023. XBRL `us-gaap:NetIncomeLoss` |
| homes_delivered | 82,917 | Item 7 MD&A, tabla "Homes Closed and Revenue", fila de totales, columna Homes Closed 2023 |
| backlog_value | 5,923.3 | Item 7 MD&A, tabla "Sales Order Backlog", fila de totales, columna Value 2023, al 30 de septiembre de 2023 |

### D.R. Horton FY2024 — `DHI-FY2024`

| Campo | Valor | Sección del filing |
|---|---|---|
| revenues | 36,801.4 | Item 8, Consolidated Statements of Operations, línea "Revenues", columna 2024. XBRL `us-gaap:Revenues`, periodo 2023-10-01/2024-09-30 |
| net_income | 4,756.4 | Item 8, Consolidated Statements of Operations, línea "Net income attributable to D.R. Horton, Inc.", columna 2024. XBRL `us-gaap:NetIncomeLoss` |
| homes_delivered | 89,690 | Item 7 MD&A, tabla "Homes Closed and Revenue", fila de totales, columna Homes Closed 2024 |
| backlog_value | 4,770.3 | Item 7 MD&A, tabla "Sales Order Backlog", fila de totales, columna Value 2024, al 30 de septiembre de 2024 |

## Decisión sobre `net_income`

Se usa la utilidad **atribuible al accionista de la controladora**
(`us-gaap:NetIncomeLoss`), que es la línea que ambas compañías presentan como
su resultado final. Excluye la participación no controladora.

La alternativa sería `us-gaap:ProfitLoss`, la utilidad total incluyendo NCI.
Si algún día se quiere cambiar el criterio, estas son las cifras:

| Compañía | FY | `NetIncomeLoss` (el que se usa) | `ProfitLoss` (incluye NCI) |
|---|---|---|---|
| Lennar | 2023 | 3,938,511 | 3,961,291 |
| Lennar | 2024 | 3,932,533 | 3,967,655 |
| D.R. Horton | 2023 | 4,745.7 | 4,795.2 |
| D.R. Horton | 2024 | 4,756.4 | 4,806.0 |

## Nota sobre `homes_delivered` de Lennar

Los 80,210 (FY2024) y 73,087 (FY2023) son el total reportado **incluyendo
entidades no consolidadas**. El propio 10-K aclara que de esos, 383 (FY2024) y
340 (FY2023) vienen de entidades no consolidadas. Si se quisiera solo
consolidado, serían 79,827 y 72,747. Se eligió el total porque es la cifra que
Lennar usa en su titular de Item 1 y en MD&A.

D.R. Horton no hace esta distinción en su tabla de "Homes Closed".

## Cómo reverificar

Los filings están en EDGAR. Para el XBRL sin bajar el documento completo:

```
https://data.sec.gov/api/xbrl/companyconcept/CIK0000920760/us-gaap/Revenues.json   # Lennar
https://data.sec.gov/api/xbrl/companyconcept/CIK0000882184/us-gaap/Revenues.json   # D.R. Horton
```

`homes_delivered` y `backlog_value` **no** están etiquetados en XBRL: son datos
operativos no auditados que solo viven en el texto y las tablas de Item 7. Hay
que leerlos del documento.
