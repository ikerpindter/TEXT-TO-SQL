"""Valida una worksheet etiquetada. REPORTA, NO ARREGLA NADA.

    uv run python evals/gold/validate_labels.py evals/gold/worksheet_dev.md

No llama al modelo, no toca la base, no escribe ningun archivo. Costo $0.

QUE HACE Y QUE NO
-----------------
Reporta problemas y sale con codigo distinto de cero si encuentra alguno. **No
corrige, no normaliza, no rellena defaults.** Una etiqueta es una medicion hecha por
una persona; un validador que "arregla" una etiqueta esta inventando datos.

Todo lo que encuentre se lista completo. No corta a los primeros N: un validador que
trunca su salida hace que el ultimo problema sea el que nadie ve.

PROTECCION DEL HOLDOUT
----------------------
Si el archivo es del holdout, **se suprime la distribucion por veredicto** y solo se
reportan chequeos estructurales. Saber cuantos `inflated` hay en el holdout ya es
informacion del holdout, y la regla 4 dice que no se abre hasta la etapa 4. El
validador tiene que poder correr sin filtrar eso.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

GOLD_DIR = Path(__file__).resolve().parent
KEYMAP = GOLD_DIR / "worksheet_keymap.json"

VERDICTS = {"not_analyzed", "no_contributing_rows", "clean",
            "shape_no_inflation", "inflated"}
SHAPES = {"fan_trap", "chasm_trap", "unexplained", "-"}

# Un veredicto sin forma tiene que llevar '-'. Uno con forma no puede llevar '-'.
SHAPE_REQUIRED = {"inflated", "shape_no_inflation"}
SHAPE_FORBIDDEN = {"clean", "not_analyzed"}
# no_contributing_rows puede ir con forma o sin ella: la forma se detecta
# estaticamente aunque el multiplicador sea indefinido.

CASE_RE = re.compile(r"^### ((?:DEV|HOLD)-\d{2})\s*$", re.M)
FIELD_RE = re.compile(r"^(LABEL|SHAPE|NOTA):[ \t]*(.*)$", re.M)


def parse(text: str) -> dict[str, dict[str, str]]:
    """Extrae {clave: {LABEL, SHAPE, NOTA}} en orden de aparicion."""
    marks = [(m.group(1), m.start()) for m in CASE_RE.finditer(text)]
    out: dict[str, dict[str, str]] = {}
    for i, (key, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        fields = {name: value.strip()
                  for name, value in FIELD_RE.findall(text[start:end])}
        out[key] = fields
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2

    path = Path(argv[1])
    if not path.exists():
        print(f"no existe {path}")
        return 2

    is_holdout = "holdout" in path.name.lower()
    text = path.read_text("utf-8")
    cases = parse(text)

    problems: list[str] = []

    # --- estructura contra el keymap ---
    if KEYMAP.exists():
        keymap = json.loads(KEYMAP.read_text("utf-8"))["keymap"]
        prefix = "HOLD" if is_holdout else "DEV"
        expected = {k for k in keymap if k.startswith(prefix)}
        missing = expected - set(cases)
        extra = set(cases) - expected
        for k in sorted(missing):
            problems.append(f"{k}: falta en la worksheet, esta en el keymap")
        for k in sorted(extra):
            problems.append(f"{k}: esta en la worksheet, no esta en el keymap")
    else:
        problems.append(f"no existe {KEYMAP.name}, no se pudo cruzar la estructura")

    # --- contenido de cada caso ---
    filled = 0
    verdict_counts: collections.Counter[str] = collections.Counter()

    for key in sorted(cases):
        fields = cases[key]
        for name in ("LABEL", "SHAPE"):
            if name not in fields:
                problems.append(f"{key}: falta la linea {name}:")

        label = fields.get("LABEL", "")
        shape = fields.get("SHAPE", "")

        if not label:
            problems.append(f"{key}: LABEL vacio")
        elif label not in VERDICTS:
            problems.append(
                f"{key}: LABEL {label!r} no esta en el vocabulario "
                f"({', '.join(sorted(VERDICTS))})")
        else:
            verdict_counts[label] += 1

        if not shape:
            problems.append(f"{key}: SHAPE vacio, usa '-' si no hay forma")
        elif shape not in SHAPES:
            problems.append(
                f"{key}: SHAPE {shape!r} no esta en el vocabulario "
                f"({', '.join(sorted(SHAPES))})")

        if label in VERDICTS and shape in SHAPES:
            if label in SHAPE_REQUIRED and shape == "-":
                problems.append(
                    f"{key}: LABEL {label} exige una forma, SHAPE dice '-'")
            if label in SHAPE_FORBIDDEN and shape != "-":
                problems.append(
                    f"{key}: LABEL {label} no lleva forma, SHAPE dice {shape!r}")

        if label and shape:
            filled += 1

    # --- reporte ---
    print(f"archivo : {path}")
    print(f"casos   : {len(cases)}")
    print(f"completos (LABEL y SHAPE) : {filled} de {len(cases)}")

    if is_holdout:
        print("\nHOLDOUT: la distribucion por veredicto se suprime a proposito.")
        print("Verla ya es informacion del holdout. Solo se reportan chequeos")
        print("estructurales. Se abre en la etapa 4, una sola vez.")
    else:
        print("\ndistribucion por veredicto:")
        if verdict_counts:
            for verdict in sorted(VERDICTS):
                n = verdict_counts.get(verdict, 0)
                print(f"  {verdict:<22} {n}")
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
