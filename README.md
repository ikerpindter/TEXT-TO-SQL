# text-to-SQL con guardrails

Un text-to-SQL puede devolver un número mal sin que nada se queje: el SQL es
válido, las tablas existen, los tipos cuadran, y aun así la cifra está inflada
porque un join duplicó filas antes de sumarlas. Este repo mide ese modo de falla
sobre una base con trampas plantadas a propósito, y le pone encima un detector
determinista que revisa el SQL producido y explica qué se duplicó y por qué.

## Cómo está armado

```
pregunta -> schema.py -> generate.py -> SQL -> db.py (solo lectura) -> resultado
                                          \
                                           fanout.py -> veredicto + explicación
```

**El SQL del modelo se ejecuta sin validar, sin parsear, sin límite de filas y
sin timeout**, con la conexión en `mode=ro` como única protección de ejecución.
Es deliberado: cada guardrail entra en su propia rebanada y con su propia
medición, no todos de golpe. Van tres rebanadas cerradas de seis.

## Correr

Requiere [uv](https://docs.astral.sh/uv/) y Python 3.12. En Linux, macOS o WSL.

### Sin API key

Todo esto corre sin llave y sin costo, y es la mayor parte del repo:

```bash
uv sync
uv run python data/build_db.py                 # construye data/portfolio.db
sha256sum data/portfolio.db                    # tiene que dar c710b635...

uv run python evals/gold/gate_adversarial.py   # 25 casos con respuesta declarada
uv run python evals/gold/smoke_sqlglot.py      # las 4 APIs de sqlglot que se usan

uv run txt2sql --schema                        # el esquema que ve el modelo
uv run txt2sql --schema --values               # el mismo, con los valores inyectados
uv run python evals/batch.py --config ddl_only --n 5 --dry-run
```

La base es determinista: dos corridas de `build_db.py` producen un archivo byte
por byte idéntico. Salida de un checkout limpio, verificada el 13 de agosto de
2026 clonando en un directorio nuevo:

```
uv lock --check    exit 0   (20 paquetes)
build_db.py        exit 0
sha256             c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762
gate_adversarial   exit 0   25 de 25 pasan
smoke_sqlglot      exit 0   las 4 partes pasan
```

El `schema_text` guardado dentro de `evals/runs/*.json` se comparó contra el que
produce el código hoy: idéntico en los dos archivos, mismo sha256 y misma
longitud. Los resultados congelados son comprobables por terceros.

### Con API key

```bash
cp .env.example .env                    # y pon tu OPENAI_API_KEY
uv run txt2sql "cuantas casas se cerraron en Texas"
uv run python evals/batch.py --config ddl_only --n 5
uv run python evals/batch.py --config values_text_maxcard20 --n 5
```

El CLI imprime siempre los tokens y el costo real de cada llamada.
`evals/batch.py` **no es un eval harness**: no tiene gold set, scoring ni
métricas. Llama, corre el SQL, le pega el veredicto del detector y deja el crudo
en `evals/runs/`. El harness es la rebanada 4 y no existe todavía.

## Los datos

Cuatro tablas en SQLite. Salida verbatim de `build_db.py`:

```
  companies        2 filas
  financials       4 filas
  communities     20 filas
  homes          794 filas
```

`financials` no tiene ni una cifra inventada: son números reales de los 10-K de
Lennar y D.R. Horton, FY2023 y FY2024, cada uno citado contra su filing con
accession number y sección en [data/seeds/SOURCES.md](data/seeds/SOURCES.md).
`communities` y `homes` son sintéticos y **no reconcilian** con `financials`. No
deben: son una muestra ilustrativa, no el inventario de las compañías.

La base tiene ocho trampas plantadas a propósito —dos escalas monetarias en la
misma columna, dos calendarios fiscales que no coinciden, filas canceladas que
siguen contando, `closing_date` en NULL para el backlog, fan-out de presupuesto
al hacer join, y más— documentadas una por una en el bloque
`TRAMPAS PLANTADAS A PROPÓSITO` de [data/build_db.py](data/build_db.py). El
esquema que se le manda al modelo **no** incluye esos comentarios: se
introspecciona con `PRAGMA table_info`, que devuelve el catálogo sin anotar.

## Qué encontró

La pregunta Q4 pide el presupuesto total de las comunidades de D.R. Horton. Éste
es el SQL que escribió el modelo —la entrada 40 del corpus, no un ejemplo
inventado— y la salida real del detector sobre él:

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

$348,500,000 reportados como **$14,388,050,000**, en 5 de 5 corridas. El SQL es
impecable: las tablas existen, las columnas existen, los tipos cuadran. Lo que
está mal es el grano de la agregación.

Y el `COUNT(h.id)` de esa misma consulta **no** se marca, porque cada casa entra
una sola vez. El detector evalúa el multiplicador de la tabla que se agrega, no
el de cualquier tabla del join.

### `row_multiplier` y `value_inflation` no son lo mismo

Los dos campos del hallazgo, tal como salen:

```json
{
  "shape": "fan_trap",
  "aggregate": "SUM(communities.budget_usd)",
  "one_side": "communities",
  "many_side": "homes",
  "row_multiplier": 40.0,
  "value_inflation": 41.285653,
  "reported_value": 14388050000.0,
  "deduplicated_value": 348500000.0
}
```

- **`row_multiplier` = 40.0** es duplicación de **filas**:
  `COUNT(T.rowid) / COUNT(DISTINCT T.rowid)` sobre la misma fuente de filas de
  la consulta original. Prueba que hay duplicación, y es estructural.
- **`value_inflation` = 41.285653** es cuánto se infló **esta cifra**:
  `reported_value / deduplicated_value`, con el deduplicado **recalculado contra
  la base**, nunca estimado.

Difieren porque el ratio de valor está ponderado por `budget_usd`: cada comunidad
aporta su presupuesto por *su propio* número de casas, y los presupuestos no son
iguales. Coincidirían solo si lo fueran.

**Consecuencia dura: `deduplicated_value` no se puede derivar dividiendo por el
multiplicador.** `14,388,050,000 / 40.0` da `359,701,250` contra `348,500,000`
reales: **3.21% de error presentado como cifra exacta.**

Y la brecha **cambia de signo**. En Q4 el multiplicador queda por debajo del
ratio de valor (40.0 contra 41.285653); en el caso A6 del set adversario queda
por encima (39.7 contra 39.6336, 0.17% de diferencia). No es cota superior ni
inferior en ninguna dirección, así que el render tiene prohibido decir "al menos
Nx" o "a lo mucho Nx". Cuando el valor deduplicado no se puede calcular, el texto
dice que **no se midió**, en vez de estimarlo.

Ésa es la regla que ordena todo el proyecto: **nunca afirmar por cuánto está mal
un número que no se midió.** Un guardrail que reporta un factor de inflación que
no calculó está fabricando precisión, que es exactamente la falla que se le mide
al modelo.

## El detector

Dos pasadas, y la primera no depende de la segunda:

1. **Estática**, sobre el árbol del SQL: ¿hay estructura de join uno-a-muchos
   **y** un agregado sensible a duplicación sobre una columna afectada? La
   dirección del join sale **solo de llaves foráneas declaradas**
   (`PRAGMA foreign_key_list`), nunca de los datos.
2. **Dinámica**, contra la base: el multiplicador de filas de arriba.

La estática corre siempre. Si el hallazgo solo naciera cuando el multiplicador
sale mayor a 1, una consulta con la estructura peligrosa y datos que hoy no la
disparan se reportaría como limpia.

**Cero llamadas a la API.** Dos consultas de SQLite por hallazgo, sobre la
conexión de solo lectura que ya existe. sqlglot va con pin exacto en 30.14.0,
porque en esa librería un salto de MINOR rompe compatibilidad.

Cinco veredictos, evaluados en orden; el primero que aplica gana:

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
`clean`. Eso es el comportamiento correcto de un detector honesto sobre su
alcance, no un hoyo.

**Marca y explica, no bloquea.** La respuesta se muestra siempre. Bloquear
convertiría una falla silenciosa en una ruidosa, que es mejor, pero también
mataría consultas legítimas.

## Qué está medido y qué no

Las dos listas van juntas a propósito: una sin la otra miente por omisión.

### Medido

| | |
|---|---|
| Gate adversario | **25 de 25**, commit `5865127`. Cada caso con una **precondición evaluada antes del veredicto**: un caso que no puede distinguir una implementación correcta de una rota **falla**, en vez de pasar en verde |
| Comportamiento sobre output real | Las **49** consultas distintas que el modelo produjo en las rebanadas 1 y 2, corridas y descritas |
| Q4 | **5 de 5** corridas detectadas, con el deduplicado recalculado contra la base en $348,500,000 |
| Checkout limpio | Clon nuevo, `uv sync`, build, hash y los dos gates: todo pasa (bloque de arriba) |

Un número de gate no se reporta nunca solo: va con su commit y su conteo de
casos. Este repo ya tiene "21 de 21" (`b0de43d`) y "25 de 25" (`5865127`). Los
dos son 100% y no son comparables — la suite creció. Sin el conteo, una suite que
**encoge** también da 100% y se lee como salud.

Distribución de veredictos sobre las 49 entradas, de
[`fanout_corpus_valores_ensanchados_20260730.md`](evals/results/fanout_corpus_valores_ensanchados_20260730.md):

| Veredicto | Entradas | de |
|---|---|---|
| `not_analyzed` | 14 | 49 |
| `no_contributing_rows` | 12 | 49 |
| `clean` | 11 | 49 |
| `shape_no_inflation` | 4 | 49 |
| `inflated` | 8 | 49 |

### No medido

Esto importa tanto como lo de arriba.

- **No hay ninguna medida de acierto en este repo. Ni precision, ni recall, ni
  porcentaje de nada.** No existe una sola etiqueta humana contra la cual
  comparar los veredictos: `evals/gold/worksheet_dev.md` tiene sus 25 líneas
  `LABEL:` y las 25 están vacías. Sin etiquetas no hay verdaderos ni falsos
  positivos que contar, y cualquier cifra de acierto sería inventada.
- **Correr el detector sobre esas 49 entradas es una demo, no una medición.** El
  detector fue construido, depurado y corregido contra ese mismo SQL: dos bugs
  aparecieron corriéndolo sobre el corpus y una regla se cambió por lo que el
  corpus devolvió. Está documentado con su evidencia, y el commit que lo dice es
  `6cf4903`. Los archivos de `evals/results/fanout_corpus_*` describen el
  comportamiento del detector sobre las entradas contra las que fue construido;
  no son evidencia de generalización.
- **El orden que hacía de las etiquetas una medición está roto, y se reporta.**
  El protocolo era criterios, luego etiquetas, luego detector, en commits
  separados. El detector se escribió antes de que existiera una sola etiqueta
  (`5e11672`). Cualquier etiqueta futura se escribe con el detector ya en el
  árbol, y nada en el repo puede probar que su output no estuvo disponible.
- **Las 11 entradas `clean` no se auditaron una por una.** Puede haber fan-out
  real ahí y este repo no lo sabría.
- **Cuatro guards del detector no tienen ningún caso en el corpus real.**
  `WITHOUT ROWID`, columna que sombrea `rowid`, agregado sobre fuente no-base y
  subconsulta correlacionada aparecen **cero** veces en las 49. Solo se ejercitan
  contra casos escritos a mano.
- **La duplicación semántica del corpus sigue sin medir.** El dedupe fue solo por
  string, así que dos consultas idénticas salvo alias son dos entradas de las 49,
  y **esas 49 no son 49 observaciones independientes.** Cambia la N efectiva de
  cualquier tasa que se publique en el futuro.
- **La mitad holdout sigue sellada y sin abrir**, y hoy está **sin función**: el
  detector no vio una mitad más que la otra, así que una diferencia entre mitades
  sería ruido de muestreo entre 24 y 25, no overfitting. Se queda sellada para
  cuando una rebanada futura afine contra dev y el holdout vuelva a medir algo.

Una prueba real de este detector necesita SQL que no haya visto, o sea corridas
nuevas del modelo congeladas antes de tocarlas. Eso es la rebanada 4.

## La deuda abierta

**13 de las 49 entradas caen en `not_analyzed` por `unattributable_aggregate`.**
Tres de ellas son Q5 en la configuración con valores —las ids 45, 46 y 48— que el
propio [ROADMAP](docs/ROADMAP.md) documenta como portadoras del artefacto de
fan-out. El detector alcanza 2 de esas 5.

**La causa es una sola y es estructural.** El multiplicador se define sobre una
tabla `T`: `COUNT(T.rowid) / COUNT(DISTINCT T.rowid)`. Un `COUNT(*)` no nombra
ninguna columna, así que no hay `T`, y la misma pared aparece con
`SUM(CASE WHEN ... THEN 1 ELSE 0 END)`, donde lo que se suma es una constante.
**El detector no falla por no saber medir: falla por no saber a qué tabla
apuntarle.**

Las dos salidas fáciles ya se descartaron con medición:

- **Devolver `clean`** marcaba limpias las tres entradas de Q5. Eso es un miss,
  no un hueco.
- **Marcar contra cualquier tabla duplicada** produce un falso positivo sobre
  `COUNT(*) FROM homes JOIN communities`, que es correctísimo: `communities` se
  duplica y el conteo de casas no.

El camino escrito para la rebanada 4 es sondear **todas** las tablas base de la
fuente de filas en vez de deducir una sola `T`, y reportar todas las
granularidades duplicadas. Para `COUNT(*) FROM homes JOIN communities` daría
`homes` 1.0 y `communities` 39.7, y esos dos números juntos dicen algo que
ninguno dice solo: el conteo está al grano de `homes`, y `homes` no se duplica.
Eso exige vocabulario de salida que hoy no existe, así que es un cambio de forma
del detector, no un parche.

## Fuera de alcance por ahora

Límite de filas, timeout, eval harness con gold set, y pruebas de ataque. Nada de
eso está aquí.

**La validación de esquema se descartó con evidencia, no por falta de tiempo.**
El plan original la ponía como el guardrail central. Medida contra las fallas
reales de este sistema, caza **cero**: cuando el modelo escribe
`WHERE name IN ('Lennar')` la tabla existe, la columna existe y el tipo es
correcto —**el valor es lo que no existe**— y cuando suma un presupuesto sobre un
join a `homes`, el SQL es impecable y lo que está mal es el grano. En 55 llamadas
medidas, este sistema **no alucinó ni una tabla ni una columna.** Se descartó por
falta de blanco.

## Cómo se construye esto

Por rebanadas. Cada una se mide antes de pasar a la siguiente, y las decisiones
quedan escritas **antes** de conocer el resultado, incluidas las predicciones que
fallaron.

**Un archivo de resultados nunca se edita.** Si cambia cualquier variable
—modelo, prompt, esquema, temperatura, gold set— el resultado va en un archivo
nuevo, y una corrección va como nota fechada. Sobrescribir un archivo de
resultados destruye la comparación que hace que el resultado signifique algo.

**Todo número de este README es salida generada y pegada verbatim.** Ninguno se
tecleó a mano. La regla se ganó: un borrador anterior traía un bloque de salida
escrito a mano que mezclaba dos consultas distintas, cada número real por
separado y juntos describiendo una consulta que no existe.

| Archivo | Qué midió |
|---|---|
| [`baseline_ddl_only.md`](evals/results/baseline_ddl_only.md) | Rebanada 1, DDL puro, N=1 |
| [`ddl_only_n5.md`](evals/results/ddl_only_n5.md) | Rebanada 2, control: DDL puro, N=5 |
| [`values_text_maxcard20_n5.md`](evals/results/values_text_maxcard20_n5.md) | Rebanada 2, con valores inyectados, N=5 |
| [`corpus_verification.md`](evals/results/corpus_verification.md) | Rebanada 3, verificación del corpus y de la fórmula |
| [`fanout_corpus_descriptivo_20260730.md`](evals/results/fanout_corpus_descriptivo_20260730.md) | Rebanada 3, el detector sobre las 49. Descriptivo, sin tasas |
| [`fanout_corpus_valores_ensanchados_20260730.md`](evals/results/fanout_corpus_valores_ensanchados_20260730.md) | Lo mismo tras ensanchar dos reglas de valor. El diff contra el anterior es la evidencia |

El orden de rebanadas, las decisiones pre-registradas, las predicciones fallidas
y las deudas abiertas están en [docs/ROADMAP.md](docs/ROADMAP.md), que es la
fuente viva.
