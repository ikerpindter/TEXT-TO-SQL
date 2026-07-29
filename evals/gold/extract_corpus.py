"""Congela el corpus de SQL que ya existe en evals/runs/ en un archivo único.

    uv run python evals/gold/extract_corpus.py

No llama al modelo. No toca la base. No evalúa nada. Lee los JSON de corridas,
junta todo el SQL que el modelo ya produjo, lo deduplica y escribe
evals/gold/corpus_sql.json.

QUÉ ES Y QUÉ NO ES
------------------
Es la materia prima de la etapa de etiquetado de la rebanada 3: la lista de SQL
distintos que hay que clasificar a mano, cada uno con su procedencia completa
para poder volver a la corrida original.

No es un gold set. No tiene la respuesta correcta de ninguna pregunta, ni la
etiqueta de fan-out de ningún query. Esas las pone una persona en la worksheet,
a ciegas, y eso es otro archivo.

SOBRE EL DEDUPE
---------------
`docs/ROADMAP.md` ya midió que agrupar por string exacto no ahorra trabajo: las
25 corridas de la config A dieron 25 SQL distintos. El dedupe de aquí no está
para ahorrar clasificaciones —no va a ahorrar casi ninguna— sino para garantizar
que la worksheet no contenga dos veces el mismo string, y para dejar el conteo
de colapso medido en el archivo en lugar de supuesto.

La normalización aplica SOLO a la llave de comparación. El SQL que se guarda es
el texto crudo, byte por byte como salió del modelo.

EL CHEQUEO DE PARSEO VIVE AQUÍ
------------------------------
Que el SQL del corpus parse con sqlglot es una afirmación sobre el corpus, no
sobre la librería. `smoke_sqlglot.py` es el gate de la dependencia y usa fixtures
escritos a mano; no lee este archivo ni ningún otro dato. Si el chequeo del
corpus viviera allá, el gate de la librería dependería del artefacto que se
construye usando la librería.

Si algo no parsea, el corpus **no se escribe**. Un SQL generado que sqlglot no
puede leer es un hallazgo que necesita una decisión humana —¿es basura de formato
que sobrevivió a `generate.py`, o es SQL válido que sqlglot no soporta?— y no
algo que se congele en silencio.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import sqlglot

GOLD_DIR = Path(__file__).resolve().parent
RUNS_DIR = GOLD_DIR.parent / "runs"
OUT_PATH = GOLD_DIR / "corpus_sql.json"

DIALECT = "sqlite"

# La única normalización que se aplica a la llave de dedupe. Deliberadamente
# mínima: colapsa corridas de espacios en blanco y recorta los extremos. No
# toca mayúsculas, no normaliza alias, no ordena columnas, no quita el punto y
# coma final. Cualquiera de esas cosas fusionaría queries que un humano tiene
# que ver por separado.
def norm_key(sql: str) -> str:
    return " ".join(sql.split())


def load_runs() -> list[dict]:
    """Devuelve los payloads de evals/runs/*.json en orden de nombre de archivo."""
    paths = sorted(RUNS_DIR.glob("*.json"))
    if not paths:
        raise SystemExit(f"no hay corridas en {RUNS_DIR}")

    payloads = []
    for path in paths:
        payload = json.loads(path.read_text("utf-8"))
        payload["_file"] = path.name
        payloads.append(payload)
    return payloads


def main() -> int:
    # Protocolo de archivos congelados: este archivo no se sobrescribe.
    if OUT_PATH.exists():
        print(f"ya existe {OUT_PATH}. Bórralo a mano si de verdad quieres rehacerlo.")
        return 1

    payloads = load_runs()

    # Llave normalizada -> entrada del corpus. dict preserva orden de inserción,
    # así que los ids salen en orden de primera aparición y son reproducibles.
    groups: dict[str, dict] = {}
    total_sql = 0

    for payload in payloads:
        file_name = payload["_file"]
        config = payload["config"]

        for record in payload["records"]:
            sql = record["sql"]
            total_sql += 1

            source = {
                "file": file_name,
                "config": config,
                "question_index": record["question_index"],
                "question": record["question"],
                "run": record["run"],
            }

            key = norm_key(sql)
            entry = groups.get(key)

            if entry is None:
                groups[key] = {
                    "id": len(groups) + 1,
                    "sql": sql,
                    "occurrences": 1,
                    "whitespace_variants": False,
                    "sources": [source],
                }
            else:
                entry["occurrences"] += 1
                # Misma llave pero texto crudo distinto: el colapso lo hizo la
                # normalización de whitespace, no una repetición literal. Se
                # marca para que nadie lea `sql` como el único texto del grupo.
                if sql != entry["sql"]:
                    entry["whitespace_variants"] = True
                entry["sources"].append(source)

    entries = list(groups.values())

    # Chequeo de parseo antes de escribir. Ver el docstring: si algo no parsea,
    # el corpus no se congela.
    unparsed = []
    for entry in entries:
        try:
            tree = sqlglot.parse_one(entry["sql"], dialect=DIALECT)
        except Exception as exc:  # noqa: BLE001 - cualquier excepción cuenta
            unparsed.append((entry["id"], f"{type(exc).__name__}: {exc}"))
        else:
            if tree is None:
                unparsed.append((entry["id"], "parse_one devolvió None"))

    if unparsed:
        print(f"{len(unparsed)} de {len(entries)} distintos NO parsean con "
              f"sqlglot {sqlglot.__version__} dialecto {DIALECT!r}:")
        for entry_id, msg in unparsed:
            print(f"  id={entry_id}  {msg}")
        print("\nel corpus NO se escribió. Decide qué hacer con esos casos antes "
              "de congelar.")
        return 1

    payload_out = {
        "generated": date.today().isoformat(),
        "source_files": [p["_file"] for p in payloads],
        "dedupe": "string exacto sobre whitespace normalizado (' '.join(sql.split()))",
        "total_sql": total_sql,
        "distinct_sql": len(entries),
        "entries": entries,
    }
    OUT_PATH.write_text(
        json.dumps(payload_out, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )

    collapsed = total_sql - len(entries)
    ws_only = sum(1 for e in entries if e["whitespace_variants"])
    print(f"archivos leídos : {len(payloads)}")
    print(f"SQL totales     : {total_sql}")
    print(f"SQL distintos   : {len(entries)}")
    print(f"colapsados      : {collapsed}")
    print(f"  de esos, colapsados solo por whitespace: {ws_only}")
    print(f"parsean         : {len(entries)} de {len(entries)}"
          f"  (sqlglot {sqlglot.__version__}, dialecto {DIALECT!r})")
    print(f"escrito: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
