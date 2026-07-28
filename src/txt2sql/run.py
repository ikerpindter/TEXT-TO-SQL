"""CLI.

    uv run txt2sql "cuantas casas se cerraron en Texas"
    uv run txt2sql --schema          # vuelca el esquema, sin llamar al modelo

Imprime el SQL que generó el modelo, el resultado de correrlo, y lo que costó
la llamada. El costo se imprime siempre: es regla del proyecto no correr nada
a ciegas.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from dotenv import load_dotenv

from txt2sql import db, generate, schema as schema_mod

MAX_COL = 40


def _fmt(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"
    return str(value)


def print_table(columns: list[str], rows: list[tuple]) -> None:
    if not columns:
        print("(sin columnas)")
        return

    cells = [[_fmt(v) for v in row] for row in rows]
    widths = [
        min(MAX_COL, max(len(c), *(len(r[i]) for r in cells)) if cells else len(c))
        for i, c in enumerate(columns)
    ]

    def line(values: list[str]) -> str:
        return "  ".join(v[:w].ljust(w) for v, w in zip(values, widths))

    print(line(columns))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print(line(row))

    print(f"\n({len(rows)} fila{'s' if len(rows) != 1 else ''})")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="txt2sql",
        description="Genera SQL desde una pregunta y lo corre contra portfolio.db",
    )
    parser.add_argument("question", nargs="?", help="la pregunta, en lenguaje natural")
    parser.add_argument(
        "--schema",
        action="store_true",
        help="vuelca el esquema que se le manda al modelo y sale, sin llamar a la API",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"modelo a usar (default: {generate.model_name()})",
    )
    args = parser.parse_args()

    load_dotenv(db.REPO_ROOT / ".env")

    try:
        conn = db.connect()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    schema_text = schema_mod.dump_schema(conn)

    if args.schema:
        print(schema_text)
        return 0

    if not args.question:
        parser.error("falta la pregunta (o usa --schema)")

    print(f"pregunta: {args.question}\n")

    try:
        result = generate.generate_sql(args.question, schema_text, model=args.model)
    except Exception as exc:  # la API puede fallar de muchas maneras
        print(f"la llamada al modelo falló: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("SQL generado:")
    print(f"  {result.sql}".replace("\n", "\n  "))
    print()

    exit_code = 0
    try:
        cursor = conn.execute(result.sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        print_table(columns, cursor.fetchall())
    except sqlite3.Error as exc:
        print(f"el SQL falló al ejecutarse: {type(exc).__name__}: {exc}")
        exit_code = 2

    cost = result.cost_usd
    cost_str = f"${cost:.6f}" if cost is not None else "precio desconocido"
    # reasoning_tokens ya viene dentro de output_tokens; se muestra aparte
    # porque en un modelo de razonamiento suele ser la mayor parte del costo.
    reasoning = (
        f" (de los cuales {result.reasoning_tokens} de razonamiento)"
        if result.reasoning_tokens
        else ""
    )
    print(
        f"\n{result.model}  |  "
        f"{result.input_tokens} tok entrada + {result.output_tokens} tok salida"
        f"{reasoning}  |  {cost_str}"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
