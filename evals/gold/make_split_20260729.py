"""Genera la particion dev/holdout del corpus real. Desechable, fechado.

    uv run python evals/gold/make_split_20260729.py

Read-only sobre la base y los artefactos. Escribe solo split_assignment.json, y
se niega a sobrescribirlo.

POR QUE ESTA COMMITEADO
-----------------------
Una particion con seed que no se puede regenerar no es reproducible, y "seed
20260729" no significa nada sin el codigo que la consume. Este script ES la
definicion operativa de la particion; el JSON es su salida congelada.

QUE NO HACE
-----------
No mira ninguna etiqueta, porque no existe ninguna todavia. Los tres flags de
estratificacion son hechos ESTRUCTURALES medidos en el lote de verificacion, no
etiquetas, asi que no hay fuga. Ese es el punto entero de correr esto antes de
etiquetar.

El set adversario NO se parte y no lo toca este script: va entero a dev y lo
declara su propio archivo.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path

import sqlglot

GOLD_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOLD_DIR.parents[1]
CORPUS = GOLD_DIR / "corpus_sql.json"
RUNS = REPO_ROOT / "evals" / "runs"
OUT = GOLD_DIR / "split_assignment.json"

SEED = 20260729
DIALECT = "sqlite"


def structural_flags(entry: dict, row_counts: dict) -> tuple[bool, bool, bool]:
    """Los tres flags del estrato. Hechos estructurales, no etiquetas.

    `is_no_rows` significa aqui, literalmente, **row_count del output igual a
    cero en todas sus corridas**. NO significa "fuente de filas vacia": el lote
    de verificacion midio que 19 entradas tienen la fuente vacia y solo 2 tienen
    row_count 0, porque un agregado desnudo sobre cero filas emite una fila con
    un cero adentro. El flag se conserva con esta definicion porque es la que se
    pre-registro y con la que se calcularon los estratos; el nombre se documenta
    en lugar de cambiarse.
    """
    counts = {row_counts[(s["file"], s["question_index"], s["run"])]
              for s in entry["sources"]}
    is_no_rows = counts == {0}

    tree = sqlglot.parse_one(entry["sql"], dialect=DIALECT)
    has_cte = tree.find(sqlglot.exp.CTE) is not None
    has_left_join = any(
        (j.side or "").upper() in ("LEFT", "RIGHT", "FULL")
        for j in tree.find_all(sqlglot.exp.Join)
    )
    return is_no_rows, has_cte, has_left_join


def main() -> int:
    if OUT.exists():
        print(f"ya existe {OUT}. Borralo a mano si de verdad quieres rehacerlo.")
        return 1

    row_counts = {}
    for path in sorted(RUNS.glob("*.json")):
        payload = json.loads(path.read_text("utf-8"))
        for record in payload["records"]:
            row_counts[(path.name, record["question_index"], record["run"])] = (
                record["result"]["row_count"]
            )

    entries = json.loads(CORPUS.read_text("utf-8"))["entries"]

    strata: dict[tuple[bool, bool, bool], list[int]] = {}
    flags_by_id: dict[int, tuple[bool, bool, bool]] = {}
    for entry in entries:
        key = structural_flags(entry, row_counts)
        flags_by_id[entry["id"]] = key
        strata.setdefault(key, []).append(entry["id"])

    rng = random.Random(SEED)
    assignment: dict[int, str] = {}
    stratum_report = []

    # Orden deterministico de los estratos: por la tupla. Sin esto el resultado
    # dependeria del orden de insercion y la seed no bastaria para reproducirlo.
    for key in sorted(strata):
        ids = sorted(strata[key])
        rng.shuffle(ids)
        dev, holdout = [], []
        for i, entry_id in enumerate(ids):
            side = "dev" if i % 2 == 0 else "holdout"
            assignment[entry_id] = side
            (dev if side == "dev" else holdout).append(entry_id)
        stratum_report.append({
            "is_no_rows": key[0],
            "has_cte": key[1],
            "has_left_join": key[2],
            "n": len(ids),
            "dev": sorted(dev),
            "holdout": sorted(holdout),
        })

    dev_ids = sorted(i for i, s in assignment.items() if s == "dev")
    holdout_ids = sorted(i for i, s in assignment.items() if s == "holdout")

    payload = {
        "generated": date.today().isoformat(),
        "seed": SEED,
        "corpus": "corpus_sql.json",
        "strata_definition": [
            "is_no_rows: row_count del OUTPUT igual a 0 en todas las corridas de la "
            "entrada. NO es 'fuente de filas vacia'. Ver el docstring del script.",
            "has_cte: el arbol contiene al menos un nodo CTE.",
            "has_left_join: al menos un JOIN con side LEFT, RIGHT o FULL en el scope "
            "de mas afuera. Es un PISO: no busca joins anidados dentro de CTEs ni "
            "subconsultas.",
        ],
        "method": "Dentro de cada estrato, orden por id, shuffle con la seed, y "
                  "luego alternar dev y holdout empezando por dev. Los estratos se "
                  "recorren en orden de la tupla para que la seed baste.",
        "adversarial_set": {
            "file": "corpus_sql_adversarial.json",
            "split": "dev",
            "note": "No se parte. Son unit tests con respuesta declarada, no una "
                    "muestra. No entran a la estimacion de desempeno de nadie.",
        },
        "holdout_puede": "Cachar overfitting grueso: si el comportamiento cambia "
                         "fuerte entre la mitad usada para construir y la que no, "
                         "eso se ve.",
        "holdout_no_puede": "Producir una tasa publicable. Son 49 entradas, mitades "
                            "de 25 y 24, con tasa de positivos desconocida. Precision "
                            "y recall se reportan EN CONTEOS, nunca en porcentajes, "
                            "hasta que exista el gold set de la rebanada 4. Segunda "
                            "razon, independiente del N: la duplicacion semantica del "
                            "corpus sigue sin medir, asi que las 49 entradas no son 49 "
                            "observaciones independientes.",
        "limitacion": "has_left_join es un conteo sintactico del scope de mas afuera "
                      "y puede ser un piso, asi que algunas entradas pueden estar mal "
                      "estratificadas. Estratos imperfectos siguen ganandole a un "
                      "split aleatorio con N chica, pero la imperfeccion se anota.",
        "counts": {
            "total": len(entries),
            "dev": len(dev_ids),
            "holdout": len(holdout_ids),
            "strata": len(stratum_report),
        },
        "strata": stratum_report,
        "dev": dev_ids,
        "holdout": holdout_ids,
        "assignment": {str(k): assignment[k] for k in sorted(assignment)},
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print(f"entradas   : {len(entries)}")
    print(f"estratos   : {len(stratum_report)}")
    for s in stratum_report:
        print(f"  ({s['is_no_rows']!s:<5} {s['has_cte']!s:<5} {s['has_left_join']!s:<5}) "
              f"n={s['n']:<3} dev={len(s['dev']):<3} holdout={len(s['holdout'])}")
    print(f"dev        : {len(dev_ids)}")
    print(f"holdout    : {len(holdout_ids)}")
    print(f"escrito: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
