"""Valida una worksheet etiquetada. REPORTA, NO ARREGLA NADA.

    uv run python evals/gold/validate_labels.py evals/gold/worksheet_dev.md

No llama al modelo, no toca la base, no escribe ningun archivo. Costo $0.

EL VOCABULARIO HUMANO NO COMPARTE NI UN TOKEN CON EL DEL DETECTOR
----------------------------------------------------------------
Las etiquetas son `shape_present`, `shape_absent`, `out_of_scope` y `unsure`. Los
veredictos del detector son `inflated`, `shape_no_inflation`, `no_contributing_rows`,
`clean` y `not_analyzed`. **Cero tokens compartidos, a proposito.**

La razon es que tres de los cinco veredictos NO son determinables desde el SQL:
`inflated` y `shape_no_inflation` exigen el multiplicador medido, y
`no_contributing_rows` exige `COUNT(T.rowid)`. Un humano a ciegas solo puede aportar
la mitad estructural. Si los vocabularios compartieran nombres, alguien compararia
etiqueta contra veredicto con `==` y pareceria que funciona.

La adjudicacion entre los dos vocabularios esta pre-registrada en `docs/ROADMAP.md`,
escrita antes de que exista una sola etiqueta.

`SHAPE` es OPCIONAL y solo aplica a `shape_present`. Nombrar `fan_trap` contra
`chasm_trap` es un segundo juicio que puede fallar independiente del primero, y el
primario es el binario.

QUE HACE Y QUE NO
-----------------
Reporta problemas y sale con codigo distinto de cero si encuentra alguno. **No
corrige, no normaliza, no rellena defaults.** Una etiqueta es una medicion hecha por
una persona; un validador que "arregla" una etiqueta esta inventando datos.

Todo lo que encuentre se lista completo. No corta a los primeros N: un validador que
trunca su salida hace que el ultimo problema sea el que nadie ve.

**Cualquier linea con forma `PALABRA:` que no reconozca se reporta.** Un
`RECONOCIDO:` mal tecleado tenia que ser visible: el silencio de un campo que no se
captura es el mismo modo de falla que `args.get("from")` devolviendo None, que el C1
que pasaba verde midiendo nada, y que `rowid` sobre una derivada.

PROTECCION DEL HOLDOUT
----------------------
Si el archivo es del holdout, **se suprime la distribucion por etiqueta** y solo se
reportan chequeos estructurales. Saber cuantos `shape_present` hay en el holdout ya
es informacion del holdout, y la regla 4 dice que no se abre hasta la etapa 4.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

GOLD_DIR = Path(__file__).resolve().parent
KEYMAP = GOLD_DIR / "worksheet_keymap.json"

# Vocabulario HUMANO. No comparte ni un token con el de veredictos del detector.
LABELS = {"shape_present", "shape_absent", "out_of_scope", "unsure"}

# SHAPE es opcional y SOLO aplica a shape_present.
SHAPES = {"fan_trap", "chasm_trap", "unexplained"}
SHAPE_ONLY_FOR = "shape_present"
SHAPE_EMPTY = {"", "-"}

RECONOCIDA_VALUES = {"si", ""}

KNOWN_FIELDS = {"LABEL", "SHAPE", "RECONOCIDA", "NOTA"}

CASE_RE = re.compile(r"^### ((?:DEV|HOLD)-\d{2})\s*$", re.M)
FIELD_RE = re.compile(r"^(LABEL|SHAPE|RECONOCIDA|NOTA):[ \t]*(.*)$", re.M)
NOTA_RE = re.compile(r"^NOTA:", re.M)
# Cualquier linea que ARRANQUE con una palabra en mayusculas y dos puntos.
# Deliberadamente laxa: preferimos un falso positivo reportado a un campo perdido.
ANYFIELD_RE = re.compile(r"^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ_]{1,30}):", re.M)


def parse(text: str) -> dict[str, dict]:
    """Extrae {clave: {campos, desconocidos, tras_nota}} en orden de aparicion.

    LA NOTA PUEDE SER MULTILINEA
    ----------------------------
    `NOTA:` es el ultimo campo de la plantilla y todo lo que va despues es texto
    libre. El barrido de campos desconocidos **se corta ahi**, porque si no, una
    nota de dos lineas cuya segunda arranque con algo tipo `OJO:` se reportaria
    como campo mal escrito. Se probo: pasaba exactamente eso.

    A cambio, un campo conocido que aparezca DESPUES de la NOTA se reporta: su
    valor queda ambiguo con el texto libre, y la plantilla pone NOTA al final.
    """
    marks = [(m.group(1), m.start()) for m in CASE_RE.finditer(text)]
    out: dict[str, dict] = {}
    for i, (key, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        block = text[start:end]

        fields = {name: value.strip() for name, value in FIELD_RE.findall(block)}

        nota = NOTA_RE.search(block)
        head = block[:nota.start()] if nota else block
        tail = block[nota.end():] if nota else ""

        unknown = sorted({m for m in ANYFIELD_RE.findall(head)
                          if m not in KNOWN_FIELDS})
        after_nota = sorted({m for m in ANYFIELD_RE.findall(tail)
                             if m in KNOWN_FIELDS})

        out[key] = {"fields": fields, "unknown": unknown, "after_nota": after_nota}
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: uv run python evals/gold/validate_labels.py <worksheet.md>")
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"no existe {path}")
        return 2

    is_holdout = "holdout" in path.name.lower()
    cases = parse(path.read_text("utf-8"))

    problems: list[str] = []

    # --- estructura contra el keymap ---
    if KEYMAP.exists():
        keymap = json.loads(KEYMAP.read_text("utf-8"))["keymap"]
        prefix = "HOLD" if is_holdout else "DEV"
        expected = {k for k in keymap if k.startswith(prefix)}
        for k in sorted(expected - set(cases)):
            problems.append(f"{k}: falta en la worksheet, esta en el keymap")
        for k in sorted(set(cases) - expected):
            problems.append(f"{k}: esta en la worksheet, no esta en el keymap")
    else:
        problems.append(f"no existe {KEYMAP.name}, no se pudo cruzar la estructura")

    # --- contenido de cada caso ---
    filled = 0
    label_counts: collections.Counter[str] = collections.Counter()
    reconocidas = 0

    for key in sorted(cases):
        fields = cases[key]["fields"]

        for name in cases[key]["unknown"]:
            problems.append(
                f"{key}: linea {name}: no reconocida. Campos validos: "
                f"{', '.join(sorted(KNOWN_FIELDS))}")

        for name in cases[key]["after_nota"]:
            problems.append(
                f"{key}: el campo {name}: aparece DESPUES de NOTA:. Todo lo que "
                f"sigue a NOTA: es texto libre, asi que ese valor queda ambiguo. "
                f"Mueve {name}: arriba de NOTA:")

        if "LABEL" not in fields:
            problems.append(f"{key}: falta la linea LABEL:")

        label = fields.get("LABEL", "")
        shape = fields.get("SHAPE", "")
        recon = fields.get("RECONOCIDA", "")

        if not label:
            problems.append(f"{key}: LABEL vacio")
        elif label not in LABELS:
            problems.append(
                f"{key}: LABEL {label!r} no esta en el vocabulario "
                f"({', '.join(sorted(LABELS))})")
        else:
            label_counts[label] += 1
            filled += 1

        # SHAPE es opcional. Lo unico invalido es un valor fuera del vocabulario,
        # o una forma nombrada en una etiqueta que no es shape_present.
        if shape not in SHAPE_EMPTY:
            if shape not in SHAPES:
                problems.append(
                    f"{key}: SHAPE {shape!r} no esta en el vocabulario "
                    f"({', '.join(sorted(SHAPES))}), o dejalo vacio")
            elif label and label != SHAPE_ONLY_FOR:
                problems.append(
                    f"{key}: SHAPE {shape!r} solo aplica a {SHAPE_ONLY_FOR}, "
                    f"y LABEL dice {label!r}")

        if recon not in RECONOCIDA_VALUES:
            problems.append(
                f"{key}: RECONOCIDA {recon!r} invalida. Usa 'si' o dejala vacia")
        elif recon == "si":
            reconocidas += 1

    # --- reporte ---
    print(f"archivo : {path}")
    print(f"casos   : {len(cases)}")
    print(f"con LABEL valido : {filled} de {len(cases)}")

    if is_holdout:
        print("\nHOLDOUT: la distribucion por etiqueta se suprime a proposito.")
        print("Verla ya es informacion del holdout. Solo se reportan chequeos")
        print("estructurales. Se abre en la etapa 4, una sola vez.")
    else:
        print("\ndistribucion por etiqueta:")
        if label_counts:
            for label in sorted(LABELS):
                print(f"  {label:<16} {label_counts.get(label, 0)}")
            print(f"\nRECONOCIDA=si : {reconocidas}")
            print("  (una query reconocida no se descarta: se reporta aparte, "
                  "porque el ciego sobre ella ya no vale)")
        else:
            print("  (ninguna etiqueta valida todavia)")

    print(f"\nproblemas : {len(problems)}")
    for p in problems:
        print(f"  {p}")

    if problems:
        print("\nNO se arreglo nada. Corrigelos a mano en la worksheet.")
        return 1
    print("\nsin problemas.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
