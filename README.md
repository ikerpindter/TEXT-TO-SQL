# text-to-SQL con guardrails

Preguntas en lenguaje natural contra una base de datos de constructoras de
vivienda. El proyecto se construye por rebanadas; van tres.

## Qué hay hasta ahora

El esqueleto que va de una pregunta a un resultado, más un detector que revisa
el SQL producido:

```
pregunta -> schema.py -> generate.py -> SQL -> db.py (solo lectura) -> resultado
                                          \
                                           fanout.py -> veredicto + explicación
```

**El SQL del modelo se ejecuta sin validar, sin parsear, sin límite de filas y
sin timeout**, con la conexión en `mode=ro` como única protección de ejecución.
Eso es a propósito: cada guardrail se agrega en su propia rebanada y con su
propia medición, no todos de golpe.

La rebanada 2 agregó la **inyección de valores**: por cada columna de texto que
no sea llave y tenga 20 valores distintos o menos, el esquema lleva la lista
completa. Completos o nada, nunca una muestra. Se prende con `--values`.

La rebanada 3 agregó el **detector de fan-out**, que es la sección de abajo.

## El detector de fan-out

### Qué problema resuelve

Cuando una consulta une una tabla con otra que tiene varias filas por cada fila
de la primera, el motor **replica** las filas del lado "uno". Si encima hay una
suma, cada valor se suma una vez por copia. El SQL es válido, las tablas
existen, los tipos cuadran y **el número sale mal sin que nada se queje.**

El caso medido de este repo: un presupuesto de $348,500,000 reportado como
**$14,388,050,000**, porque cada comunidad se sumó una vez por cada casa.

### Cómo lo detecta

Dos pasadas, y la primera no depende de la segunda:

1. **Estática**, sobre el árbol del SQL: ¿hay estructura de join uno-a-muchos
   **y** un agregado sensible a duplicación sobre una columna afectada? La
   dirección del join sale **solo de llaves foráneas declaradas**, nunca de los
   datos.
2. **Dinámica**, contra la base: `COUNT(T.rowid) / COUNT(DISTINCT T.rowid)` sobre
   la misma fuente de filas de la consulta original.

La estática corre siempre. Si el hallazgo solo naciera cuando el multiplicador
sale mayor a 1, una consulta con la estructura peligrosa y datos que hoy no la
disparan se reportaría como limpia.

**Cero llamadas a la API.** Dos consultas de SQLite por hallazgo, sobre la
conexión de solo lectura que ya existe.

### Los cinco veredictos

Se evalúan en orden y el primero que aplica gana.

| Veredicto | Qué significa |
|---|---|
| `not_analyzed` | El detector no pudo analizarla. Siempre con su razón |
| `no_contributing_rows` | Ninguna fila de la tabla agregada llegó al cálculo. El multiplicador es indefinido |
| `clean` | Analizada, sin duplicación de filas medida |
| `shape_no_inflation` | La estructura peligrosa está, y con estos datos no duplicó |
| `inflated` | La estructura está y el multiplicador medido es mayor a 1 |

**`clean` significa "sin duplicación de filas medida", NO "la consulta es
correcta".** Este detector mide una sola cosa. Un número puede seguir estando mal
por escalas de unidades, por año fiscal o por un literal mal adivinado, y salir
`clean`. Eso es el comportamiento correcto, no un hoyo.

### Marca y explica, no bloquea

La respuesta se muestra siempre. Debajo va un bloque que **nombra la
consecuencia, no la mecánica**.

Esto es la salida real del detector sobre el SQL que el modelo escribió para Q4
—la entrada 40 del corpus, no un ejemplo inventado:

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
[!] esta respuesta se calculó sobre filas repetidas
    communities.budget_usd se sumó una vez por cada fila de homes, no una
    vez por communities.
    Cada fila de communities entró 40 veces al cálculo (400 filas sobre 10
    distintas).
    Por el join: homes.community_id = communities.id
    El número quedó 41.2857x más alto que el que daría sin la repetición.
    Sin la repetición, SUM(communities.budget_usd) da 348,500,000.00 en vez
    de 14,388,050,000.00.
    Ese valor es un diagnóstico, no la respuesta a tu pregunta.
```

La regla que manda sobre ese texto: **nunca afirmar por cuánto está mal un número
que no se midió.** El multiplicador de **filas** y el factor de inflación del
**valor** son cosas distintas —**40.0** contra **41.285653** en el caso de
arriba— y la brecha cambia de signo según el caso, así que el multiplicador no
acota el error ni por arriba ni por abajo. Cuando el valor deduplicado no se
puede calcular, el texto dice que **no se midió**, en vez de estimarlo dividiendo:
esa división daría 359,701,250 contra 348,500,000 reales, un 3.21% de error con
cara de cifra exacta.

Y el `COUNT(h.id)` de esa misma consulta **no** se marca, porque cada casa entra
una sola vez: el detector evalúa el multiplicador de la tabla que se agrega, no
el de cualquier tabla del join.

### Qué está medido, y qué no

**Medido:**

- **25 de 25** casos adversarios, cada uno con una **precondición que se evalúa
  antes del veredicto**: un caso que no puede distinguir una implementación
  correcta de una rota **falla**, en vez de pasar en verde.
- Comportamiento sobre las **49** consultas distintas que el modelo produjo en las
  rebanadas 1 y 2.
- El caso Q4: **5 de 5** corridas detectadas, con el valor deduplicado
  recalculado contra la base en $348,500,000.

**No medido, y esto importa tanto como lo anterior:**

- **No hay ninguna medida de acierto en este repo: precision, recall o cualquier
  porcentaje.** No existe todavía una sola etiqueta humana contra la cual
  comparar los veredictos, así que no hay verdaderos ni falsos positivos que
  contar. Cualquier cifra de acierto sería inventada.
- Las entradas que salieron `clean` no se auditaron una por una.
- Cuatro guards del detector no tienen ningún caso en el corpus real y solo se
  ejercitan con pruebas escritas a mano.

**Hueco conocido:** un `COUNT(*)` no nombra ninguna columna, así que no hay tabla
a la que atribuirle la duplicación y el detector lo declara no analizado en vez
de adivinar. Son **13 de las 49** entradas. Está anotado con su causa y su camino
de arreglo en [docs/ROADMAP.md](docs/ROADMAP.md).

## Correr

Todo en WSL. Nunca desde PowerShell.

```bash
uv sync
uv run python data/build_db.py          # construye data/portfolio.db
cp .env.example .env                    # y pon tu OPENAI_API_KEY

uv run txt2sql "cuantas casas se cerraron en Texas"
uv run txt2sql --schema                 # el esquema que ve el modelo, sin costo
uv run txt2sql --schema --values        # el mismo, con los valores inyectados
```

El CLI imprime siempre los tokens y el costo real de la llamada.

Para repetir las cinco preguntas N veces por configuración:

```bash
uv run python evals/batch.py --config ddl_only --n 5 --dry-run   # sin costo
uv run python evals/batch.py --config ddl_only --n 5
uv run python evals/batch.py --config values_text_maxcard20 --n 5
```

`evals/batch.py` **no es el eval harness**: no tiene gold set, scoring ni
métricas. Solo llama, corre el SQL, le pega el veredicto del detector y deja el
crudo en `evals/runs/`. El harness es la rebanada 4.

Los dos gates del detector, los dos sin costo y sin API:

```bash
uv run python evals/gold/gate_adversarial.py   # 25 casos con respuesta declarada
uv run python evals/gold/smoke_sqlglot.py      # las 4 APIs de sqlglot que usa
```

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

## Resultados medidos

Cada corrida vive en su propio archivo congelado bajo `evals/results/`. Un
archivo de resultados nunca se edita: si cambia una variable, es un archivo
nuevo.

| Archivo | Qué midió |
|---|---|
| [`baseline_ddl_only.md`](evals/results/baseline_ddl_only.md) | Rebanada 1, DDL puro, N=1 |
| [`ddl_only_n5.md`](evals/results/ddl_only_n5.md) | Rebanada 2, control: DDL puro, N=5 |
| [`values_text_maxcard20_n5.md`](evals/results/values_text_maxcard20_n5.md) | Rebanada 2, con valores, N=5 |
| [`corpus_verification.md`](evals/results/corpus_verification.md) | Rebanada 3, verificación del corpus y de la fórmula |
| [`fanout_corpus_descriptivo_20260730.md`](evals/results/fanout_corpus_descriptivo_20260730.md) | Rebanada 3, el detector sobre las 49. **Descriptivo, sin tasas** |
| [`fanout_corpus_valores_ensanchados_20260730.md`](evals/results/fanout_corpus_valores_ensanchados_20260730.md) | Lo mismo tras ensanchar dos reglas de valor. El diff contra el anterior es la evidencia |

El resultado de la rebanada 2, en un caso concreto. Q4 pregunta por el
presupuesto total de las comunidades de D.R. Horton:

| Esquema enviado | Devolvió | Real | ¿Se delata? |
|---|---|---|---|
| DDL puro | `NULL` | $348,500,000 | sí, es un NULL |
| DDL + valores | **$14,388,050,000** | $348,500,000 | **no** |

Misma pregunta, mismo modelo, misma base, 5 de 5 corridas en cada brazo. Lo
único que cambió fue el bloque de valores. El literal mal adivinado estaba
tapando un fan-out de 41.3x; al arreglar el literal, el fan-out quedó expuesto y
el resultado dejó de delatarse.

Las proporciones agregadas de las dos corridas están en los archivos de
resultados. **No se citan aquí a propósito:** sin scoring automático contra un
gold set —rebanada 4— son medición interna y no aguantan una cifra de portada.
Los casos individuales sí, porque cada uno se reproduce corriendo el SQL guardado
en `evals/runs/`.

## Fuera de alcance por ahora

Límite de filas, timeout, harness de evaluación con gold set, y pruebas de
ataque. Nada de eso está aquí todavía.

**La validación de esquema se descartó con evidencia, no por falta de tiempo.** El
plan original la ponía como el guardrail central. Medida contra las fallas reales
de este sistema, caza **cero**: cuando el modelo escribe `WHERE name IN ('Lennar')`
la tabla existe, la columna existe y el tipo es correcto —**el valor es lo que no
existe**— y cuando suma un presupuesto sobre un join a `homes`, el SQL es
impecable y lo que está mal es el grano de la agregación. En 55 llamadas medidas,
este sistema **no alucinó ni una tabla ni una columna**. Se descartó por falta de
blanco.

## Cómo se construye esto

Cada rebanada se mide antes de pasar a la siguiente, y las decisiones quedan
escritas **antes** de conocer el resultado. Los archivos de resultados no se
editan nunca: si cambia una variable, es un archivo nuevo, y una corrección va
como nota fechada.

El orden, las decisiones pre-registradas, las predicciones fallidas y las deudas
abiertas están en [docs/ROADMAP.md](docs/ROADMAP.md), que es la fuente viva.
