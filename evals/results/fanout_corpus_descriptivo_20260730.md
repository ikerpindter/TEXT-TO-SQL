# Detector de fan-out sobre el corpus real: distribución descriptiva

**Corrida del 30 de julio de 2026.** Archivo de resultados: no se edita.
Una corrección va como nota fechada al inicio, nunca como reescritura.

| | |
|---|---|
| Corpus | `evals/gold/corpus_sql.json`, **49 entradas distintas** |
| Base | `data/portfolio.db`, sha256 `c710b6354d57bc0e74feb9d4233bb77e902ae4ff6f49b85960a6eef15684d762` |
| sqlglot | 30.14.0, pin exacto |
| Dialecto | `sqlite` |
| Llamadas a API | 0 |

## Qué NO es esto

**Cero precision, cero recall, cero porcentajes.**

No hay contra qué compararlos: `worksheet_dev.md` tiene sus 25 líneas
`LABEL:` vacías y **no existe una sola etiqueta humana**, así que no hay
verdaderos ni falsos positivos que contar. Lo único que estas 49 entradas
pueden sostener es qué contestó el detector.

Y aunque las etiquetas existieran, seguiría faltando un dato: **la
duplicación semántica del corpus no está medida.** El dedupe fue solo por
string, así que dos queries idénticas salvo alias son dos entradas de las 49
y esas 49 **no son 49 observaciones independientes**. Eso cambia la N
efectiva de cualquier tasa, y por eso el ROADMAP la pide medida antes de
publicar una.

**Tampoco hay desglose por dev y holdout**, y no es por la regla del patrón
—`split_assignment.json` no hace match con `evals/gold/*holdout*`— sino
porque ver el comportamiento por mitad antes de la etapa 4 es justo el
insumo que permitiría afinar contra el holdout.

## Veredictos

Denominador: **49**, las entradas distintas del corpus. Cada entrada
recibe exactamente un veredicto.

| Veredicto | Entradas | de |
|---|---|---|
| `not_analyzed` | 14 | 49 |
| `no_contributing_rows` | 12 | 49 |
| `clean` | 11 | 49 |
| `shape_no_inflation` | 4 | 49 |
| `inflated` | 8 | 49 |

Recordatorio que importa para la rebanada 6: **`clean` significa «sin
duplicación de filas medida», no «la query es correcta».** Las trampas de
`unit_scale` y de año fiscal producen números mal con veredicto `clean`, y
eso es el comportamiento correcto de un detector que mide una sola cosa.

## Razones de `not_analyzed`

Denominador: **14**, las entradas `not_analyzed`.

La columna de la derecha importa por la tabla de adjudicación del
ROADMAP: una razón que el documento de criterios lista es un error de
etiquetado del humano, y una que no lista es un **hueco del documento**.
Se ven igual en los datos y tienen causas opuestas.

| Razón | Entradas | ¿La listan los criterios? |
|---|---|---|
| `non_fk_join` | 1 | sí |
| `unattributable_aggregate` | 13 | **no** |

## Formas detectadas

Denominador: **25** hallazgos, repartidos en
**24** de las 49 entradas. Una entrada puede
traer más de un hallazgo, así que los dos números son distintos y ninguno
es el otro.

| Forma | Hallazgos |
|---|---|
| `chasm_trap` | 15 |
| `fan_trap` | 10 |

## Agregados de los hallazgos

| Función | Hallazgos |
|---|---|
| `AVG` | 8 |
| `COUNT` | 3 |
| `SUM` | 14 |

Con `GROUP BY`: **9** de 25 hallazgos, todos con
`multiplier_scope: global`. Un multiplicador global mayor a 1 prueba que
**existe** duplicación en algún lugar del resultado, no que **cada**
grupo esté afectado.

## Multiplicadores medidos

Denominador: **12** hallazgos con `row_multiplier` calculable,
de 25 hallazgos totales. Los demás tienen la fuente sin filas
que aporten y el multiplicador es indefinido, no cero.

| `row_multiplier` | Hallazgos |
|---|---|
| 1.0 | 4 |
| 2.0 | 2 |
| 40.0 | 5 |
| 51.5 | 1 |

Mínimo 1.0, máximo 51.5.

## `value_inflation`, o por qué casi nunca sale

Hallazgos con `deduplicated_value` calculado: **0** de
25.

El caso angosto exige las cuatro cosas juntas: exactamente un agregado
marcado, forma `fan_trap`, `SUM` o `COUNT` sobre una columna del lado «uno»,
y sin `GROUP BY`. Fuera de ahí va `null`, **y no se aproxima dividiendo por
`row_multiplier`**: sobre Q4 esa división da 359,701,250 contra 348,500,000
reales, 3.21% de error en una cifra que se vería exacta.


## Agregados no atribuibles: el hueco de cobertura más grande

Entradas con al menos un agregado sensible sin columna a la que atribuirlo:
**14** de 49.

Son `COUNT(*)` y variantes como
`SUM(CASE WHEN ... THEN 1 ELSE 0 END)`, donde lo que se suma es una
constante. No hay columna, así que no hay `T` y el multiplicador no es
calculable. Marcarlos produciría un falso positivo medido sobre
`COUNT(*) FROM homes JOIN communities`, donde la duplicación de
`communities` no toca al conteo de casas.

**Cuando no hubo ningún otro hallazgo, la entrada va a `not_analyzed`, no a
`clean`.** Esta regla se corrigió el 30 de julio de 2026 **después de**
mirar esta misma corrida: la versión anterior devolvía `clean` y nombraba
el agregado aparte, y así marcaba `clean` tres entradas de Q5 en la config
B —ids 45, 46 y 48— que el ROADMAP documenta como portadoras del artefacto
de fan-out. Un `clean` sobre la falla que esta rebanada existe para cazar
es un miss, no un hueco aceptable.

Cuando **sí** hubo otro hallazgo medible, la entrada conserva su veredicto y
el agregado no atribuible se nombra al lado: la id 47 trae un `COUNT(*)` y
además un `SUM(financials.backlog_value)` inflado 51.5x, y anular la entrada
entera tiraría una detección verdadera.

**Esto es un dato de alcance, no un resultado.** Es el costo de no afirmar
lo que no se midió, y es la primera cosa que la rebanada 4 debería atacar.

## Entrada por entrada

Los 49 veredictos, para que cualquier conteo de arriba se pueda reproducir.
Sin `row_count` ni config: el detector no los leyó y no hacen falta aquí.

| id | Veredicto | Forma | `row_multiplier` | Razón / subcaso | Agregados no atribuidos |
|---|---|---|---|---|---|
| 1 | `clean` | — | — | — | 0 |
| 2 | `clean` | — | — | — | 0 |
| 3 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 4 | `clean` | — | — | — | 0 |
| 5 | `clean` | — | — | — | 0 |
| 6 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 7 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 8 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 9 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 10 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 11 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 12 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 13 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 14 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 15 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 16 | `no_contributing_rows` | fan_trap | — | `empty_source` | 0 |
| 17 | `no_contributing_rows` | fan_trap | — | `empty_source` | 0 |
| 18 | `no_contributing_rows` | fan_trap | — | `empty_source` | 0 |
| 19 | `no_contributing_rows` | fan_trap | — | `empty_source` | 0 |
| 20 | `no_contributing_rows` | fan_trap | — | `empty_source` | 0 |
| 21 | `clean` | — | — | — | 0 |
| 22 | `clean` | — | — | — | 0 |
| 23 | `inflated` | chasm_trap | 2.0 | — | 0 |
| 24 | `no_contributing_rows` | chasm_trap | — | `empty_source` | 0 |
| 25 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 26 | `clean` | — | — | — | 0 |
| 27 | `clean` | — | — | — | 0 |
| 28 | `clean` | — | — | — | 0 |
| 29 | `shape_no_inflation` | chasm_trap | 1.0 | — | 0 |
| 30 | `clean` | — | — | — | 0 |
| 31 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 32 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 33 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 34 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 35 | `shape_no_inflation` | chasm_trap | 1.0 | — | 0 |
| 36 | `not_analyzed` | — | — | `non_fk_join` | 0 |
| 37 | `shape_no_inflation` | chasm_trap | 1.0 | — | 0 |
| 38 | `clean` | — | — | — | 0 |
| 39 | `shape_no_inflation` | chasm_trap | 1.0 | — | 0 |
| 40 | `inflated` | fan_trap | 40.0 | — | 0 |
| 41 | `inflated` | fan_trap | 40.0 | — | 0 |
| 42 | `inflated` | fan_trap | 40.0 | — | 0 |
| 43 | `inflated` | fan_trap | 40.0 | — | 0 |
| 44 | `inflated` | fan_trap | 40.0 | — | 0 |
| 45 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 46 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 47 | `inflated` | chasm_trap | 51.5 | — | 1 |
| 48 | `not_analyzed` | — | — | `unattributable_aggregate` | 1 |
| 49 | `inflated` | chasm_trap | 2.0 | — | 0 |

## Qué NO se verificó en esta corrida

- **Que los veredictos sean correctos.** No hay etiquetas humanas. Esta
  corrida describe la salida del detector; no la juzga.
- **La duplicación semántica de las 49 entradas.** Sigue sin medir, así que
  la N efectiva de este corpus es desconocida y menor que 49.
- **El comportamiento por mitad del split.** No se calculó a propósito.
- **Que el corpus ejercite los guards.** `WITHOUT ROWID`, columnas que
  sombrean `rowid` y agregados sobre fuentes no-base siguen sin blanco en
  esta base; el gate adversario tampoco los cubre.
- **Los `clean`.** Nadie verificó una por una las entradas que salieron
  `clean`. Podría haber fan-out real ahí y esta corrida no lo sabría.

## Contraste con lo que la rebanada 2 ya tenía medido

No es una validación —esas entradas no son etiquetas y el ROADMAP describe
preguntas, no strings de SQL— pero sí es el único cotejo disponible contra
algo escrito antes.

| Caso | Lo que dice el ROADMAP | Lo que salió aquí |
|---|---|---|
| Q4, config B, `SUM` sobre el lado uno de un join a `homes` | las 5 corridas tienen el fan-out | **5 de 5** `inflated` / `fan_trap`, `row_multiplier` 40.0 |
| Q4, config A | devolvió `NULL`, se delata sola | **5 de 5** `no_contributing_rows` / `empty_source` |
| Q5, `financials` colgada sin relación de grano | las 5 de la config B tienen el artefacto | **2 de 5** `inflated` / `chasm_trap`; las otras 3 a `not_analyzed` por agregado no atribuible |

El renglón de Q5 es el que importa: **el detector no alcanza 3 de las 5**, y
las reporta como no analizadas en vez de como limpias. La distinción es todo
el punto —un hueco declarado se puede cerrar, un `clean` falso no se ve—
pero el hueco existe y es la deuda más grande que deja esta etapa.

