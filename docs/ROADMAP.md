# Roadmap

Lectura previa obligatoria antes de tocar nada del repo.

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
