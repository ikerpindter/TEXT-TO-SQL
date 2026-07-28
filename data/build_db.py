"""Construye data/portfolio.db desde los CSV de data/seeds/.

Uso (siempre desde WSL):

    uv run python data/build_db.py

Determinista: dos corridas producen un archivo byte por byte idéntico. Lo
sintético sale de un random.Random() con semilla fija; nada depende del reloj,
de os.urandom ni del orden de un set/dict no ordenado.

===========================================================================
TRAMPAS PLANTADAS A PROPÓSITO
===========================================================================

Este dataset existe para que un text-to-SQL se equivoque de maneras
interesantes. Ocho trampas, todas deliberadas. Ninguna es un bug.

--- #1  unit_scale: dos escalas distintas en la misma tabla ---------------
    financials.revenues, net_income y backlog_value de Lennar están en
    MILES de USD. Los de D.R. Horton están en MILLONES de USD.
    La columna unit_scale lo dice, pero hay que leerla y aplicarla.
    Sumar o comparar las dos compañías sin normalizar da un resultado
    equivocado por un factor de 1000.

    Esto NO está fabricado: es como reportan de verdad. Lennar encabeza sus
    estados "(In thousands, except per share amounts)" y D.R. Horton
    "(In millions, except per share data)". Ver data/seeds/SOURCES.md.

--- #2  unit_scale aplica solo a lo monetario ----------------------------
    homes_delivered es un CONTEO. 80210 casas son 80210 casas, no 80210
    miles de casas. Aplicarle unit_scale a homes_delivered da un absurdo.
    La trampa es que unit_scale vive en la misma fila y parece aplicar a
    todo lo que esté a su lado.

--- #3  dos calendarios fiscales distintos, ninguno es el natural --------
    Lennar cierra el 30 de noviembre: su FY2024 va del 2023-12-01 al
    2024-11-30.
    D.R. Horton cierra el 30 de septiembre: su FY2024 va del 2023-10-01 al
    2024-09-30.

    O sea que la fila fiscal_year=2024 de una compañía y la fila
    fiscal_year=2024 de la otra NO cubren el mismo periodo. Se traslapan
    once meses y difieren dos. Compararlas de frente, o sumarlas para
    sacar un "total de la industria en 2024", compara periodos distintos.

    Y para las tablas sintéticas: filtrar homes por año calendario
    (strftime('%Y', closing_date) = '2024') no da el año fiscal de nadie.
    Hay cierres generados a ambos lados del 30 de noviembre y del 30 de
    septiembre justamente para que esto se note.

    companies.fiscal_year_end guarda el cierre real de cada una como
    'MM-DD', que es el único lugar del esquema donde esta información
    existe.

--- #4  status='cancelled' sigue siendo una fila -------------------------
    Una venta cancelada no desaparece de homes. SELECT COUNT(*) FROM homes
    cuenta casas que nunca se vendieron. Casi cualquier pregunta sobre
    "cuántas casas vendió" necesita filtrar status.

--- #5  list_price y sale_price conviven ---------------------------------
    list_price es el precio de lista, siempre presente. sale_price es lo
    que realmente se pagó, y es NULL si la casa no se vendió. Son
    distintos: el sale_price trae descuentos e incentivos encima. Usar
    list_price para hablar de ingresos infla la cifra.

--- #6  closing_date NULL para las casas en backlog ----------------------
    status='backlog' significa contrato firmado pero casa no entregada:
    contract_date tiene fecha, closing_date es NULL. Un WHERE sobre
    closing_date las descarta en silencio. Un ORDER BY o un MIN/MAX las
    ignora. Y son justamente las que forman el backlog.

--- #7  budget_usd vive en communities: el join hace fan-out -------------
    El presupuesto es un atributo de la COMUNIDAD, no de la casa. Al hacer
    JOIN homes ON communities, el budget_usd se repite una vez por cada
    casa de esa comunidad. SUM(budget_usd) sobre el join multiplica el
    presupuesto por el número de casas. Hay que agregar communities
    aparte, o usar SUM(DISTINCT ...) con cuidado, o subconsulta.

    ESTA NO ES UNA TRAMPA MÁS: ES EL MODO DE FALLA DOMINANTE.

    En la línea base del 2026-07-28 (evals/results/baseline_ddl_only.md) el
    fan-out pegó DOS VECES, por dos puertas distintas, y ninguna de las dos
    se delató en la salida:

      Q4, por communities.budget_usd. El modelo escribió
      SUM(c.budget_usd) con LEFT JOIN homes y reportó $14,388,050,000
      contra los $348,500,000 reales. Inflado 41x, o sea una vez por cada
      casa de la comunidad promedio.

      Q5, por financials. El modelo colgó un LEFT JOIN financials de una
      consulta sobre homes, sin ninguna relación real entre las dos. Cada
      casa se duplicó una vez por año fiscal (hay 2 filas de financials por
      compañía), y el conteo de backlog salió 206 en vez de 103. Exacto 2x.

    La lección: el fan-out no depende de que la columna inflada sea
    budget_usd. Cualquier tabla colgada de un join sin relación de grano
    real multiplica todo lo que esté del otro lado. financials es
    especialmente peligrosa porque tiene varias filas por compañía y se ve
    como una tabla de atributos.

--- #8  lo sintético es una MUESTRA, no cuadra con financials ------------
    communities y homes son datos sintéticos: ~20 comunidades y ~800
    casas. financials dice que Lennar entregó 80210 casas en FY2024 y
    D.R. Horton 89690.

    SELECT COUNT(*) FROM homes da unos 800. No hay ninguna reconciliación
    posible entre las dos tablas y no debe haberla. financials es la
    verdad reportada al regulador; homes es una muestra ilustrativa.
    Cruzarlas para "verificar" o para calcular participaciones da basura.

===========================================================================
"""

from __future__ import annotations

import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEEDS = HERE / "seeds"
DB_PATH = HERE / "portfolio.db"

# Semilla fija. No la cambies sin querer: cambiarla cambia todas las casas.
SEED = 20241130

SCHEMA = """
CREATE TABLE companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    -- Cierre de año fiscal como 'MM-DD'. Trampa #3: no son iguales.
    fiscal_year_end TEXT    NOT NULL
);

CREATE TABLE financials (
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    fiscal_year     INTEGER NOT NULL,
    -- Trampa #1: revenues, net_income y backlog_value están en la escala
    -- que diga unit_scale, que NO es la misma para las dos compañías.
    revenues        REAL,
    net_income      REAL,
    -- Trampa #2: esto es un conteo. unit_scale no le aplica.
    homes_delivered INTEGER,
    backlog_value   REAL,
    -- 'thousands' o 'millions'.
    unit_scale      TEXT    NOT NULL,
    PRIMARY KEY (company_id, fiscal_year)
);

CREATE TABLE communities (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    name         TEXT    NOT NULL,
    region       TEXT    NOT NULL,
    state        TEXT    NOT NULL,
    opened_date  TEXT    NOT NULL,
    lot_count    INTEGER NOT NULL,
    -- Trampa #7: atributo de la comunidad. Un join con homes lo replica.
    budget_usd   REAL    NOT NULL
);

CREATE TABLE homes (
    id            INTEGER PRIMARY KEY,
    community_id  INTEGER NOT NULL REFERENCES communities(id),
    -- Trampa #5: list_price siempre existe, sale_price solo si se vendió.
    list_price    REAL    NOT NULL,
    sale_price    REAL,
    contract_date TEXT,
    -- Trampa #6: NULL para backlog y para cancelled.
    closing_date  TEXT,
    -- 'closed' | 'backlog' | 'cancelled' | 'available'
    -- Trampa #4: 'cancelled' sigue ocupando una fila.
    status        TEXT    NOT NULL
);
"""

# Precio de lista base por estado, en USD. Inventado, pero con el orden de
# magnitud correcto para cada mercado. Es dato sintético y no pretende ser
# otra cosa (trampa #8).
BASE_PRICE = {
    "CA": 780_000,
    "WA": 620_000,
    "CO": 590_000,
    "NJ": 570_000,
    "NV": 490_000,
    "AZ": 470_000,
    "PA": 450_000,
    "FL": 420_000,
    "IL": 420_000,
    "NC": 400_000,
    "TN": 390_000,
    "SC": 370_000,
    "GA": 360_000,
    "TX": 320_000,
}

# Ventana de generación de contratos. Se eligió para que haya cierres a
# ambos lados del 30-nov (cierre fiscal de Lennar) y del 30-sep (cierre
# fiscal de D.R. Horton) en 2023 y 2024. Eso es lo que hace que la
# trampa #3 muerda de verdad.
CONTRACT_FROM = date(2022, 7, 1)
CONTRACT_TO = date(2024, 11, 20)

STATUS_WEIGHTS = [
    ("closed", 62),
    ("available", 15),
    ("backlog", 14),
    ("cancelled", 9),
]


def read_seed(name: str) -> list[dict[str, str]]:
    with (SEEDS / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def pick_status(rng: random.Random) -> str:
    total = sum(w for _, w in STATUS_WEIGHTS)
    roll = rng.uniform(0, total)
    upto = 0.0
    for status, weight in STATUS_WEIGHTS:
        upto += weight
        if roll <= upto:
            return status
    return STATUS_WEIGHTS[-1][0]


def build_homes(communities: list[dict[str, str]], rng: random.Random):
    """Genera ~800 casas. Cada llamada con el mismo rng da lo mismo."""
    span = (CONTRACT_TO - CONTRACT_FROM).days
    home_id = 0
    rows = []

    for community in communities:
        state = community["state"]
        base = BASE_PRICE[state]
        # Entre 28 y 52 casas por comunidad: ~40 de promedio, ~800 en total.
        # Es una muestra, no el inventario completo (trampa #8).
        n_homes = rng.randint(28, 52)

        for _ in range(n_homes):
            home_id += 1
            status = pick_status(rng)

            # Precio de lista con dispersión por lote y tipo de producto.
            list_price = round(base * rng.uniform(0.82, 1.28), -3)

            contract_date = None
            closing_date = None
            sale_price = None

            if status == "available":
                # Casa spec sin contrato: solo se conoce el precio de lista.
                # Trampa #5.
                pass
            else:
                offset = rng.randint(0, span)
                contracted = CONTRACT_FROM + timedelta(days=offset)
                contract_date = contracted.isoformat()

                if status == "closed":
                    # De contrato a escrituración: uno a cinco meses.
                    closed = contracted + timedelta(days=rng.randint(30, 150))
                    closing_date = closed.isoformat()
                    # Incentivos y descuentos: el precio pagado es menor al
                    # de lista. Trampa #5.
                    sale_price = round(list_price * rng.uniform(0.88, 1.0), -3)
                elif status == "backlog":
                    # Contrato firmado, casa no entregada. closing_date NULL
                    # a propósito. Trampa #6.
                    sale_price = round(list_price * rng.uniform(0.90, 1.0), -3)
                elif status == "cancelled":
                    # La fila se queda. Nunca hubo venta, así que no hay
                    # sale_price ni closing_date. Trampa #4.
                    pass

            rows.append(
                (
                    home_id,
                    int(community["id"]),
                    float(list_price),
                    sale_price,
                    contract_date,
                    closing_date,
                    status,
                )
            )

    return rows


def main() -> None:
    companies = read_seed("companies.csv")
    financials = read_seed("financials.csv")
    communities = read_seed("communities.csv")

    rng = random.Random(SEED)
    homes = build_homes(communities, rng)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)

        conn.executemany(
            "INSERT INTO companies (id, name, ticker, fiscal_year_end)"
            " VALUES (?, ?, ?, ?)",
            [
                (int(r["id"]), r["name"], r["ticker"], r["fiscal_year_end"])
                for r in companies
            ],
        )

        conn.executemany(
            "INSERT INTO financials (company_id, fiscal_year, revenues,"
            " net_income, homes_delivered, backlog_value, unit_scale)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    int(r["company_id"]),
                    int(r["fiscal_year"]),
                    float(r["revenues"]),
                    float(r["net_income"]),
                    int(r["homes_delivered"]),
                    float(r["backlog_value"]),
                    r["unit_scale"],
                )
                for r in financials
            ],
        )

        conn.executemany(
            "INSERT INTO communities (id, company_id, name, region, state,"
            " opened_date, lot_count, budget_usd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    int(r["id"]),
                    int(r["company_id"]),
                    r["name"],
                    r["region"],
                    r["state"],
                    r["opened_date"],
                    int(r["lot_count"]),
                    float(r["budget_usd"]),
                )
                for r in communities
            ],
        )

        conn.executemany(
            "INSERT INTO homes (id, community_id, list_price, sale_price,"
            " contract_date, closing_date, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            homes,
        )

        conn.commit()
        report(conn)
    finally:
        conn.close()


def report(conn: sqlite3.Connection) -> None:
    print(f"escrito: {DB_PATH}")
    for table in ("companies", "financials", "communities", "homes"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<12} {n:>5} filas")

    print("\n  homes por status:")
    for status, n in conn.execute(
        "SELECT status, COUNT(*) FROM homes GROUP BY status ORDER BY status"
    ):
        print(f"    {status:<10} {n:>4}")

    nulls = conn.execute(
        "SELECT COUNT(*) FROM homes WHERE closing_date IS NULL"
    ).fetchone()[0]
    print(f"\n  closing_date NULL: {nulls}  (trampa #6)")


if __name__ == "__main__":
    main()
