"""Conexión a portfolio.db en modo SOLO LECTURA.

Ésta es la única protección de la rebanada 1. El SQL que devuelve el modelo
se ejecuta sin validar, sin parsear, sin límite de filas y sin timeout. Lo
único que impide que una generación desafortunada destruya la base es que el
descriptor está abierto en modo `ro` a nivel de SQLite.

`mode=ro` hace que SQLite rechace cualquier INSERT, UPDATE, DELETE, DROP,
ALTER o CREATE con `sqlite3.OperationalError: attempt to write a readonly
database`. No es un filtro sobre el texto del SQL: es el motor negándose.

Lo que `mode=ro` NO cubre, y que por lo tanto sigue abierto en esta rebanada:
un SELECT puede tardar para siempre, puede devolver millones de filas, y
puede leer cualquier tabla. Eso es alcance de rebanadas posteriores.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

# src/txt2sql/db.py -> src/txt2sql -> src -> raíz del repo
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "portfolio.db"


def db_path() -> Path:
    """Ruta a la base. Se puede sobreescribir con TXT2SQL_DB."""
    override = os.environ.get("TXT2SQL_DB")
    return Path(override).resolve() if override else DEFAULT_DB_PATH


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Abre portfolio.db en modo solo lectura.

    Levanta FileNotFoundError si la base no existe. SQLite en modo `ro`
    crearía silenciosamente un descriptor a un archivo inexistente y
    fallaría después con un error críptico, así que se checa antes.
    """
    target = Path(path).resolve() if path else db_path()

    if not target.exists():
        raise FileNotFoundError(
            f"No existe {target}\n"
            f"Constrúyela con:  uv run python data/build_db.py"
        )

    # La ruta puede traer espacios y otros caracteres que SQLite interpreta
    # dentro de un URI, así que se escapa. `safe="/"` deja los separadores.
    uri = f"file:{quote(target.as_posix(), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True)
