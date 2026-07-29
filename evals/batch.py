"""Repite las preguntas N veces por configuración y guarda todo en JSON.

    uv run python evals/batch.py --config ddl_only            --n 5
    uv run python evals/batch.py --config values_text_maxcard20 --n 5
    uv run python evals/batch.py --config ddl_only --n 1 --dry-run

ESTO NO ES EL EVAL HARNESS
---------------------------
No hay gold set, no hay scoring, no hay métricas, no hay agregados. Eso es la
rebanada 4 y tiene que construirse a propósito, no salir de aquí por inercia.

Lo único que hace este archivo es llamar al modelo, correr el SQL que devuelva,
y dejar el resultado crudo en disco. La clasificación de correcto / falla
ruidosa / falla silenciosa la hace una persona leyendo el JSON, contra
criterios escritos ANTES de correr en el archivo de resultados.

Las corridas van a evals/runs/. Los archivos de evals/results/ son el análisis
escrito a mano y están congelados; éstos son la materia prima.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from txt2sql import db, generate, schema as schema_mod  # noqa: E402

RUNS_DIR = Path(__file__).resolve().parent / "runs"

# Verbatim de evals/results/baseline_ddl_only.md. No se tocan: cambiarlas
# rompería la comparación con la línea base, que es todo el punto.
QUESTIONS = [
    "¿Cuánto vendieron en total Lennar y D.R. Horton juntos en su año fiscal 2024?",
    "¿Cuántas casas se han vendido en Texas?",
    "¿Precio promedio de venta de las casas cerradas en el año fiscal 2024 de Lennar?",
    "¿Presupuesto total de las comunidades de D.R. Horton y cuántas casas tienen?",
    "¿Cuántas casas tiene cada compañía en backlog y cuál es su valor?",
]

# La única variable entre las dos configuraciones es `with_values`.
CONFIGS = {
    "ddl_only": False,
    "values_text_maxcard20": True,
}

# El SQL del modelo se ejecuta sin LIMIT (así está la rebanada 1: sin límite de
# filas y sin timeout). Acá se topa cuántas filas se GUARDAN, no cuántas
# devuelve la consulta: el conteo que se reporta abajo es el real.
ROW_CAP = 1000


def _jsonable(value: object) -> object:
    """sqlite puede devolver bytes; JSON no los sabe serializar."""
    if isinstance(value, (bytes, bytearray)):
        return repr(bytes(value))
    return value


def execute(conn: sqlite3.Connection, sql: str) -> dict:
    """Corre el SQL del modelo. Un error es un resultado, no una excepción."""
    try:
        cursor = conn.execute(sql)
    except sqlite3.Error as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchmany(ROW_CAP)
    extra = cursor.fetchone()

    return {
        "error": None,
        "columns": columns,
        "rows": [[_jsonable(v) for v in row] for row in rows],
        "row_count": len(rows),
        "rows_truncated": extra is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="batch")
    parser.add_argument("--config", required=True, choices=sorted(CONFIGS))
    parser.add_argument("--n", type=int, default=5, help="corridas por pregunta")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="imprime el prompt y la estimación de costo, sin llamar a la API",
    )
    args = parser.parse_args()

    load_dotenv(db.REPO_ROOT / ".env")
    conn = db.connect()

    with_values = CONFIGS[args.config]
    schema_text = schema_mod.dump_schema(conn, with_values=with_values)
    model = args.model or generate.model_name()
    n_calls = len(QUESTIONS) * args.n

    print(f"config      : {args.config}  (with_values={with_values})")
    print(f"modelo      : {model}")
    print(f"esquema     : {len(schema_text)} chars")
    print(f"llamadas    : {len(QUESTIONS)} preguntas x {args.n} = {n_calls}")

    if args.dry_run:
        print(f"\n--- esquema ---\n{schema_text}")
        return 0

    RUNS_DIR.mkdir(exist_ok=True)
    out_path = RUNS_DIR / f"{args.config}_n{args.n}.json"
    if out_path.exists():
        print(f"\nya existe {out_path}. Bórralo a mano si de verdad quieres rehacerlo.")
        return 1

    records = []
    total_cost = 0.0

    for q_index, question in enumerate(QUESTIONS, start=1):
        print(f"\nQ{q_index}  {question}")
        for run in range(1, args.n + 1):
            result = generate.generate_sql(question, schema_text, model=args.model)
            outcome = execute(conn, result.sql)
            cost = result.cost_usd or 0.0
            total_cost += cost

            records.append(
                {
                    "question_index": q_index,
                    "question": question,
                    "run": run,
                    "sql": result.sql,
                    "raw": result.raw,
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "reasoning_tokens": result.reasoning_tokens,
                    "cost_usd": result.cost_usd,
                    "result": outcome,
                }
            )

            if outcome["error"]:
                shape = f"ERROR {outcome['error'][:40]}"
            else:
                shape = f"{outcome['row_count']} filas"
            print(
                f"  run {run}  {result.input_tokens:>5}+{result.output_tokens:<4} tok"
                f"  ${cost:.6f}  {shape}"
            )

    payload = {
        "config": args.config,
        "with_values": with_values,
        "max_cardinality": schema_mod.MAX_CARDINALITY,
        "n": args.n,
        "date": date.today().isoformat(),
        "model_requested": model,
        "db_path": str(db.db_path()),
        "schema_text": schema_text,
        "system_prompt": generate.SYSTEM_PROMPT,
        "user_template": generate.USER_TEMPLATE,
        "records": records,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")

    print(f"\nescrito: {out_path}")
    print(f"costo total de esta configuración: ${total_cost:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
