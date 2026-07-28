# Roadmap

Lectura previa obligatoria antes de tocar nada del repo.

## Orden de rebanadas

Actualizado tras cerrar la rebanada 1.

1. **Esqueleto.** CERRADA. Línea base congelada en
   [`evals/results/baseline_ddl_only.md`](../evals/results/baseline_ddl_only.md).
2. **Inyección de valores de columnas de baja cardinalidad al prompt.**
3. **Guardrails.**
4. **Eval harness** con gold set y N.
5. **Ataques a escala.**
6. **Conectar como tool del agente.**

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

### Nota importante sobre la rebanada 3

**La validación de esquema NO habría cazado ninguna falla de la rebanada 1.**

`name IN ('Lennar')` pasa la validación de esquema sin problema: la tabla
existe, la columna existe, el tipo es correcto. **El valor es lo que no
existe**, y eso la validación de esquema no lo ve.

Son dos problemas distintos y no hay que confundirlos. Un guardrail que
verifica que las columnas referenciadas existen es útil contra otra clase de
falla, pero habría dejado pasar las cinco consultas de la línea base.

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
