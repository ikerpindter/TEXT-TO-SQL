# text-to-SQL con guardrails

Preguntas en lenguaje natural contra una base de datos de constructoras de
vivienda. El proyecto se construye por rebanadas; ésta es la primera.

## Qué hay en esta rebanada

El esqueleto que va de una pregunta a un resultado:

```
pregunta -> schema.py -> generate.py -> SQL -> db.py (solo lectura) -> resultado
```

**La única protección es que la conexión está en modo `mode=ro`.** El SQL que
devuelve el modelo se ejecuta sin validar, sin parsear, sin límite de filas y
sin timeout. Eso es a propósito: cada guardrail se agrega en su propia rebanada
y con su propia medición, no todos de golpe.

## Correr

Todo en WSL. Nunca desde PowerShell.

```bash
uv sync
uv run python data/build_db.py          # construye data/portfolio.db
cp .env.example .env                    # y pon tu OPENAI_API_KEY

uv run txt2sql "cuantas casas se cerraron en Texas"
uv run txt2sql --schema                 # el esquema que ve el modelo, sin costo
```

El CLI imprime siempre los tokens y el costo real de la llamada.

## Los datos

Cuatro tablas en SQLite.

| Tabla | Filas | Origen |
|---|---|---|
| `companies` | 2 | Lennar y D.R. Horton |
| `financials` | 4 | **Cifras reales** de los 10-K, FY2023 y FY2024 |
| `communities` | 20 | Sintético, escrito a mano |
| `homes` | 794 | Sintético, generado con semilla fija |

`financials` no tiene ni una cifra inventada. Cada número está citado contra su
filing, con accession number y sección, en
[data/seeds/SOURCES.md](data/seeds/SOURCES.md).

`communities` y `homes` son sintéticos y **no reconcilian** con `financials`. No
deben: son una muestra ilustrativa, no el inventario de las compañías.

La construcción es determinista. Dos corridas de `build_db.py` producen un
archivo byte por byte idéntico.

## Las trampas

La base tiene ocho trampas plantadas a propósito para que un text-to-SQL se
equivoque de maneras interesantes: dos escalas monetarias distintas en la misma
columna, dos calendarios fiscales que no coinciden, filas canceladas que siguen
contando, `closing_date` en NULL para el backlog, fan-out de presupuesto al
hacer join, y más.

Están documentadas una por una en el bloque `TRAMPAS PLANTADAS A PROPÓSITO` al
inicio de [data/build_db.py](data/build_db.py), y anotadas en el `CREATE TABLE`
en el punto exacto donde cada una se planta.

El esquema que se le manda al modelo **no** incluye esos comentarios: se
introspecciona con `PRAGMA table_info`, que devuelve el catálogo sin anotar.
Ver el porqué en el docstring de [src/txt2sql/schema.py](src/txt2sql/schema.py).

## Fuera de alcance en esta rebanada

Validación de esquema, parseo de SQL, límite de filas, timeout, harness de
evaluación, gold set y pruebas de ataque. Nada de eso está aquí todavía.
