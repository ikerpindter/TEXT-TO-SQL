"""Genera las worksheets ciegas de etiquetado. Desechable, fechado.

    uv run python evals/gold/make_worksheets_20260729.py

Read-only sobre la base y los artefactos. Escribe las dos worksheets y el keymap,
y se niega a sobrescribir cualquiera de los tres.

LOS TRES GUARDS, Y POR QUE SON TRES Y NO UNO
---------------------------------------------
Se evaluan en este orden, y cada uno protege una cosa distinta:

1. **Etiquetas escritas.** Protege una MEDICION. Una worksheet etiquetada no es una
   plantilla: regenerarla destruye el diff contra el papel en blanco.
2. **Sello en la cabecera.** Protege una PROMESA. Agregado el 30 de julio de 2026.
3. **El archivo ya existe.** Es el guard generico y el mas debil.

**El guard 2 existe porque el 1 no cubre el unico archivo que el sello protege.**
`worksheet_holdout.md` tiene sus 24 lineas `LABEL:` vacias —nadie ha etiquetado el
holdout, por definicion, hasta la etapa 4— asi que el guard de etiquetas lo deja
pasar entero. Y el guard 3 no alcanza, por dos razones: se dispara solo si el
archivo existe, y su mensaje **invita a borrarlo** ("borralos a mano si de verdad
quieres rehacerlos"), que es exactamente la instruccion equivocada para un archivo
sellado. Una regeneracion se llevaria el sello sin dejar rastro, que es justo el
modo de falla que el sello existe para evitar.

**El guard va sobre el SELLO, no sobre las etiquetas**, y por eso es independiente:
un archivo puede estar sellado y vacio, que es precisamente el caso del holdout.

Limite honesto, anotado y no cerrado: si alguien **borra** el archivo, no queda
sello que detectar y el guard no puede hacer nada. Eso no se puede arreglar desde
aqui; lo unico que se puede es que borrarlo sea un acto deliberado y visible en un
diff, que es lo que el sello ya logra.

POR QUE LA WORKSHEET NO LLEVA EL id DEL CORPUS
----------------------------------------------
La especificacion pedia "id, SQL formateado, LABEL:, SHAPE:". **El id del corpus
filtra la config**, que es una de las seis cosas que la worksheet no puede mostrar.

Medido: los ids 1-25 son todos `ddl_only` y los ids 26-49 son todos
`values_text_maxcard20`, porque `extract_corpus.py` recorre los archivos de
corridas en orden de nombre. La regla "id <= 25 entonces config A" acierta **49 de
49**. Imprimir el id equivale a imprimir la config.

Por eso la worksheet lleva una **clave opaca** —DEV-01, HOLD-07— y el mapeo a los
ids vive aparte en `worksheet_keymap.json`. El keymap se commitea porque es
contabilidad, no etiquetas: hace falta para unir las etiquetas de vuelta al corpus.
El ciego sigue dependiendo de la disciplina de no ir a abrirlo, igual que el
holdout.

LO QUE LA WORKSHEET NO MUESTRA
------------------------------
pregunta, indice de pregunta, config, resultado ejecutado, categoria, row_count, y
el id del corpus por lo de arriba.

LIMITE HONESTO DEL CIEGO
------------------------
El SQL es el artefacto a etiquetar y no se puede redactar sin destruir la tarea.
Los literales delatan la config a quien conozca el proyecto: `'Lennar'` solo
aparece en la config A y `'Lennar Corporation'` solo en la B. **El ciego es parcial
por construccion**, y eso se anota en lugar de fingir que es total.
"""

from __future__ import annotations

import json
import random
import re
import sys
from datetime import date
from pathlib import Path

GOLD_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOLD_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
from txt2sql import db, schema as schema_mod  # noqa: E402

CORPUS = GOLD_DIR / "corpus_sql.json"
SPLIT = GOLD_DIR / "split_assignment.json"
KEYMAP = GOLD_DIR / "worksheet_keymap.json"
OUT = {"dev": GOLD_DIR / "worksheet_dev.md",
       "holdout": GOLD_DIR / "worksheet_holdout.md"}

SEED = 20260729

LABELS = ["shape_present", "shape_absent", "out_of_scope", "unsure"]
SHAPES = ["fan_trap", "chasm_trap", "unexplained"]

CRITERIA = """\
## Criterio, resumido

**Fan-out** es una agregacion que cae sobre una columna del lado "uno" de un join
uno-a-muchos. El join replica esa fila una vez por cada fila del lado "muchos", y la
agregacion suma el mismo valor varias veces.

Estas juzgando **si la ESTRUCTURA del SQL permite que la duplicacion infle un
numero.** No estas juzgando si de hecho infla: eso depende de los datos y se mide
aparte. Tampoco estas juzgando si el query contesta bien la pregunta, porque no
sabes cual era la pregunta, y es a proposito.

### Las cuatro etiquetas

| Etiqueta | Cuando |
|---|---|
| `shape_present` | Hay join **mas** agregado tal que la duplicacion de filas **PODRIA** inflar un numero. No afirma que pase, solo que la estructura lo permite. |
| `shape_absent` | La estructura no lo permite: sin join, o agregado inmune (`DISTINCT`, `MAX`, `MIN`), o el CTE pre-agrega bien. |
| `out_of_scope` | Self join, window function, `UNION`/`INTERSECT`/`EXCEPT`, join que no sigue una FK declarada, o columna ambigua. |
| `unsure` | No se puede decidir desde el SQL. **Es una respuesta valida, no un fracaso.** |

**Estas cuatro NO son los veredictos del detector.** El detector emite otros cinco
nombres y ninguno coincide con estos, a proposito: tres de sus veredictos exigen
medir los datos y tu no los estas viendo. La adjudicacion entre los dos vocabularios
esta escrita en `docs/ROADMAP.md`, **antes de que existiera una sola etiqueta.**

### `SHAPE:` es OPCIONAL

Solo aplica a `shape_present`, y solo si quieres nombrar cual forma es:

- `fan_trap`: se agrega una columna del lado "uno" despues de unir al lado "muchos".
- `chasm_trap`: dos ramas uno-a-muchos desde un ancestro comun, unidas entre si.
  **Las ramas pueden tener mas de un salto.**
- `unexplained`: hay estructura duplicadora pero no encaja limpio en ninguna.

**Dejala vacia sin culpa.** Nombrar la forma es un segundo juicio que puede fallar
independiente del primero, y el primario es el binario.

### Reglas que no dependen de juicio

- Cualquier agregado con `DISTINCT` es inmune. Tambien `MAX` y `MIN`.
- Sensibles a duplicacion: `SUM`, `AVG`, `COUNT` sin DISTINCT, `TOTAL`.
- Una query **sin agregados** no tiene forma: va `shape_absent`.
- `shape_present` exige **las dos cosas juntas**: la estructura de joins **y** un
  agregado sensible sobre una columna afectada.
- Un CTE que pre-agrega a una fila por llave **no duplica**.

### `RECONOCIDA:`

Escribe `si` si reconoces la query de nuestras conversaciones. Dejala vacia si no.

No descarta el caso: se reporta aparte. El ciego sobre esa entrada ya no vale, y eso
es un dato sobre la etiqueta, no un defecto de ella.

### Si dudas

Usa `unsure` y escribe por que en `NOTA:`. Un `unsure` registrado vale mas que una
etiqueta forzada, y sale del conteo en lugar de ensuciarlo. **No se promedian los
desacuerdos.**
"""


# Una linea LABEL: con algo que no sea espacio. Las worksheets vacias traen
# "LABEL:" pelado, asi que esto distingue papel en blanco de medicion.
LABELED_RE = re.compile(r"^LABEL:[ \t]*\S", re.M)


def labeled_cases(path: Path) -> int:
    """Cuantas lineas LABEL: traen valor. 0 si el archivo no existe."""
    if not path.exists():
        return 0
    return len(LABELED_RE.findall(path.read_text("utf-8")))


# El campo de sello. Va dentro de un comentario HTML por dos razones: no se ve en
# el markdown renderizado, y no parece un campo de la plantilla. `validate_labels`
# reporta cualquier linea con forma `PALABRA:` que no reconozca, asi que un sello
# escrito como campo visible seria ruido en cada corrida del validador.
SEAL_RE = re.compile(r"^<!--\s*SELLO\b", re.M)

# Solo se mira la cabecera. Un sello vale por estar arriba, donde lo ve quien abre
# el archivo; buscarlo en todo el cuerpo lo volveria falsificable desde cualquier
# linea perdida a la mitad.
SEAL_HEADER_LINES = 40


def sealed(path: Path) -> bool:
    """Si el archivo trae el campo de sello en su cabecera.

    **Lee el archivo pero no lo vuelca**: devuelve un booleano y nada mas, y solo
    mira las primeras lineas. Es la misma disciplina con la que se escribio el
    sello del holdout, que se antepuso sin abrir el archivo.
    """
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as handle:
        head = "".join(next(handle, "") for _ in range(SEAL_HEADER_LINES))
    return SEAL_RE.search(head) is not None


def main() -> int:
    # GUARD DURO: una worksheet con etiquetas escritas es una MEDICION.
    # Regenerarla la destruye, y eso no puede depender de que alguien se acuerde.
    with_labels = [(p, n) for p in OUT.values() if (n := labeled_cases(p))]
    if with_labels:
        print("ME NIEGO A ESCRIBIR: hay etiquetas escritas.")
        print()
        for path, n in with_labels:
            print(f"  {path.name}: {n} lineas LABEL: con valor")
        print()
        print("Una worksheet con etiquetas es una MEDICION, no una plantilla.")
        print("Regenerarla la destruiria y el diff contra el papel en blanco, que es")
        print("la evidencia de que no se etiqueto mirando el output del detector,")
        print("se perderia sin dejar rastro.")
        print()
        print("Si de verdad hay que rehacer las worksheets, primero se decide que")
        print("pasa con esas etiquetas y se deja escrito. No se resuelve aqui.")
        return 2

    # GUARD DURO: un archivo sellado no se regenera, TENGA O NO ETIQUETAS.
    # Va sobre el sello y no sobre las etiquetas a proposito: el holdout esta
    # sellado y vacio, o sea que es justo el archivo que el guard de arriba no
    # cubre, y el unico que el sello protege.
    sealed_files = [p for p in OUT.values() if sealed(p)]
    if sealed_files:
        print("ME NIEGO A ESCRIBIR: hay archivos sellados.")
        print()
        for path in sealed_files:
            print(f"  {path.name}: trae un campo de sello en la cabecera")
        print()
        print("Un sello es una promesa que viaja DENTRO del archivo, y regenerarlo")
        print("lo borraria sin dejar rastro. Ese es exactamente el modo de falla")
        print("que el sello existe para evitar.")
        print()
        print("NO borres el archivo para saltarte esto. Si de verdad hay que")
        print("rehacerlo, primero se decide que pasa con el sello y se deja escrito,")
        print("porque borrarlo tiene que ser un acto deliberado y visible en un diff.")
        return 3

    existing = [p for p in [KEYMAP, *OUT.values()] if p.exists()]
    if existing:
        print("ya existen, borralos a mano si de verdad quieres rehacerlos:")
        for p in existing:
            print(f"  {p}")
        return 1

    entries = {e["id"]: e for e in
               json.loads(CORPUS.read_text("utf-8"))["entries"]}
    split = json.loads(SPLIT.read_text("utf-8"))

    conn = db.connect()
    ddl = schema_mod.dump_schema(conn, with_values=False)

    rng = random.Random(SEED)
    keymap: dict[str, int] = {}

    for side, prefix in (("dev", "DEV"), ("holdout", "HOLD")):
        ids = sorted(split[side])
        rng.shuffle(ids)

        lines = [
            f"# Worksheet ciega de etiquetado: {side}",
            "",
            f"Generada el {date.today().isoformat()}. "
            f"{len(ids)} entradas del corpus real.",
            "",
            "**Llena `LABEL:` y `SHAPE:` en cada bloque. No borres nada mas.**",
            "",
            "Esta worksheet no muestra la pregunta, el indice de pregunta, la config,",
            "el resultado ejecutado, la categoria, el row_count, ni el id del corpus.",
            "Las claves son opacas a proposito: el id del corpus filtra la config.",
            "",
            "El set adversario **no esta aqui** y nunca lo estara: trae su respuesta",
            "declarada por diseno y vive en `corpus_sql_adversarial.json`.",
            "",
            f"Vocabulario de `LABEL:` -> {', '.join(LABELS)}",
            f"`SHAPE:` es OPCIONAL, solo para shape_present -> "
            f"{', '.join(SHAPES)}",
            "`RECONOCIDA:` -> `si` si reconoces la query, o vacia.",
            "",
            "---",
            "",
            "## Esquema completo de la base",
            "",
            "```sql",
            ddl,
            "```",
            "",
            "---",
            "",
            CRITERIA,
            "---",
            "",
            "## Casos",
            "",
        ]

        for i, entry_id in enumerate(ids, start=1):
            key = f"{prefix}-{i:02d}"
            keymap[key] = entry_id
            lines += [
                f"### {key}",
                "",
                "```sql",
                entries[entry_id]["sql"],
                "```",
                "",
                "```",
                "LABEL:",
                "SHAPE:",
                "RECONOCIDA:",
                "NOTA:",
                "```",
                "",
            ]

        OUT[side].write_text("\n".join(lines), "utf-8")
        print(f"{side:<8} {len(ids):>3} casos -> {OUT[side].name}")

    KEYMAP.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "seed": SEED,
        "purpose": "Une las claves opacas de las worksheets con los ids del corpus. "
                   "Es contabilidad, no etiquetas. La worksheet no lleva el id "
                   "porque el id filtra la config: ids 1-25 son ddl_only y 26-49 "
                   "son values_text_maxcard20, o sea 49 de 49 predecibles.",
        "blind_limit": "El ciego es parcial por construccion. Los literales del SQL "
                       "delatan la config a quien conozca el proyecto ('Lennar' vs "
                       "'Lennar Corporation'). No se puede redactar el SQL sin "
                       "destruir la tarea de etiquetado.",
        "keymap": dict(sorted(keymap.items())),
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"keymap   {len(keymap):>3} claves -> {KEYMAP.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
