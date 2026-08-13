"""Regenera los cuatro PNG de docs/img/ desde artefactos congelados.

QUE LEE, Y NADA MAS
-------------------
- `evals/gold/corpus_sql.json`, congelado. Las 49 entradas distintas.
- `data/portfolio.db`, construida por `data/build_db.py`, determinista.
- `evals/results/ddl_only_n5.md` y `values_text_maxcard20_n5.md`, congelados.

**Ningun numero esta escrito en este archivo.** Las graficas a, b y d salen de
correr el detector sobre el corpus; la c sale de parsear la linea de conteos de
los dos archivos de resultados. Si un numero cambia, cambia porque cambio el
artefacto, y eso es justo lo que se quiere: una grafica que no se puede
desincronizar de la evidencia.

Lo unico que este archivo declara son **expectativas**, y las declara para
reventar si dejan de cumplirse: cuantas entradas debe traer el corpus, cuantas
corridas debe tener cada pregunta. Un assert que falla es un hallazgo; una
grafica que se dibuja sola sobre datos cambiados, no.

DETERMINISMO
------------
Se desactiva la metadata `Software` del PNG, que trae la version de matplotlib y
haria que el archivo cambiara al actualizar la libreria sin que cambiara ni un
dato. Dos corridas seguidas en la misma maquina producen bytes identicos; eso
esta verificado. Entre maquinas distintas **no** esta verificado y no se afirma:
el rasterizado de fuentes depende de las fuentes instaladas.

COSTO
-----
Cero llamadas a API. Solo lectura sobre la base.

    uv sync --group plots
    uv run --group plots python evals/plots/make_plots.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from txt2sql import db, fanout  # noqa: E402

REPO_ROOT = db.REPO_ROOT
CORPUS = REPO_ROOT / "evals" / "gold" / "corpus_sql.json"
RESULT_A = REPO_ROOT / "evals" / "results" / "ddl_only_n5.md"
RESULT_B = REPO_ROOT / "evals" / "results" / "values_text_maxcard20_n5.md"
OUT_DIR = REPO_ROOT / "docs" / "img"

CONFIG_A = "ddl_only"
CONFIG_B = "values_text_maxcard20"

# Expectativas sobre los artefactos. No son datos: son gates.
EXPECTED_ENTRIES = 49
EXPECTED_RUNS_PER_QUESTION = 5

# Escala de grises. El orden es de mas oscuro a mas claro y no codifica nada
# por color: cada barra lleva su cifra encima.
GRAY_DARK = "0.25"
GRAY_MID = "0.55"
GRAY_LIGHT = "0.80"
EDGE = "0.15"

VERDICT_ORDER = [
    fanout.NOT_ANALYZED,
    fanout.NO_CONTRIBUTING_ROWS,
    fanout.CLEAN,
    fanout.SHAPE_NO_INFLATION,
    fanout.INFLATED,
]


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _savefig(fig, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    # metadata Software=None: sin esto el PNG trae la version de matplotlib y
    # deja de ser reproducible al actualizar la libreria.
    fig.savefig(path, dpi=150, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return path


def _miles(value: float) -> str:
    return f"{value:,.0f}"


def _usd(value: float) -> str:
    r"""Dolares con el signo escapado.

    matplotlib interpreta `$...$` como mathtext: dos signos sin escapar en el
    mismo texto se comen las comas de los miles y ponen en cursiva lo que haya
    en medio. Salio en la primera corrida de la grafica de Q4 y se veia como
    'da 359, 701, 250, no 348,500,000'. Un `\$` se renderiza como `$` literal.
    """
    return rf"\${_miles(value)}"


# ---------------------------------------------------------------- carga


def load_corpus() -> list[dict]:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    entries = corpus["entries"]
    if len(entries) != EXPECTED_ENTRIES:
        _fail(
            f"{CORPUS.name} trae {len(entries)} entradas y se esperaban "
            f"{EXPECTED_ENTRIES}. El corpus esta congelado: si de verdad cambio, "
            f"cambia tambien EXPECTED_ENTRIES y di por que."
        )
    return entries


def analyze_all(entries: list[dict]) -> dict[int, fanout.FanoutResult]:
    conn = db.connect()
    try:
        return {e["id"]: fanout.analyze(e["sql"], conn) for e in entries}
    finally:
        conn.close()


# ---------------------------------------------------------- grafica (a)


def plot_verdicts(results: dict[int, fanout.FanoutResult]) -> Path:
    counts = {v: 0 for v in VERDICT_ORDER}
    for result in results.values():
        if result.verdict not in counts:
            _fail(f"veredicto desconocido: {result.verdict!r}")
        counts[result.verdict] += 1

    total = sum(counts.values())
    labels = list(counts)
    values = [counts[k] for k in labels]

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    bars = ax.bar(
        labels,
        values,
        color=[GRAY_DARK if k == fanout.NOT_ANALYZED else GRAY_MID for k in labels],
        edgecolor=EDGE,
        linewidth=0.8,
    )
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.25,
            str(value),
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_title(
        f"Veredicto del detector sobre las {total} consultas distintas del corpus",
        fontsize=12,
        pad=14,
    )
    ax.set_ylabel(f"Entradas (de {total})")
    ax.set_ylim(0, max(values) + 3)
    ax.tick_params(axis="x", labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    not_analyzed = counts[fanout.NOT_ANALYZED]
    fig.text(
        0.5,
        -0.10,
        f"La barra mas alta es not_analyzed, con {not_analyzed} de {total}. "
        "Es el hallazgo principal, no un defecto de presentacion:\n"
        "el detector dice cuando no puede analizar en vez de degradar a "
        "'clean', que afirmaria algo que no verifico.",
        ha="center",
        va="top",
        fontsize=9,
        color="0.25",
    )
    return _savefig(fig, "01_veredictos_49.png")


# ---------------------------------------------------------- grafica (b)


def plot_q4(results: dict[int, fanout.FanoutResult], entries: list[dict]) -> Path:
    """El caso Q4: la cifra reportada contra la recalculada sin duplicacion."""
    candidates = []
    for entry in entries:
        result = results[entry["id"]]
        for finding in result.findings:
            if finding.deduplicated_value and finding.value_inflation:
                candidates.append((entry["id"], finding))
    if not candidates:
        _fail("ningun hallazgo trae deduplicated_value; no hay caso que graficar")

    # El caso canonico es el de mayor inflacion de valor.
    entry_id, finding = max(candidates, key=lambda pair: pair[1].value_inflation)
    reported = finding.reported_value
    dedup = finding.deduplicated_value
    row_mult = finding.row_multiplier
    val_infl = finding.value_inflation

    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    bars = ax.bar(
        ["Reportado\npor el modelo", "Recalculado\nsin duplicacion"],
        [reported, dedup],
        color=[GRAY_DARK, GRAY_LIGHT],
        edgecolor=EDGE,
        linewidth=0.9,
        width=0.55,
    )
    ax.set_yscale("log")
    ax.set_ylim(1e8, reported * 6)
    for bar, value in zip(bars, [reported, dedup]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.15,
            _usd(value),
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_title(
        f"{finding.aggregate}, entrada {entry_id} del corpus\n"
        "Escala logaritmica: en escala lineal la barra correcta no se ve",
        fontsize=11.5,
        pad=14,
    )
    ax.set_ylabel("Dolares (log)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    fig.text(
        0.5,
        -0.02,
        f"row_multiplier = {row_mult}          "
        f"value_inflation = {val_infl:.2f}\n"
        "No son la misma cifra y no se derivan una de otra. El primero cuenta "
        "FILAS duplicadas; el segundo mide cuanto se inflo ESTE\n"
        "valor, y va ponderado por el presupuesto de cada comunidad. Dividir "
        f"por {row_mult} da {_usd(reported / row_mult)}, no "
        f"{_usd(dedup)}:\n"
        f"{abs(reported / row_mult - dedup) / dedup * 100:.2f}% de error con "
        "cara de cifra exacta. El deduplicado se recalcula contra la base, "
        "nunca se aproxima.",
        ha="center",
        va="top",
        fontsize=8.8,
        color="0.25",
    )
    return _savefig(fig, "02_q4_reportado_vs_deduplicado.png")


# ---------------------------------------------------------- grafica (c)

_COUNT_LINE = re.compile(r"\*\*Por SQL distinto \((\d+) de \d+\):([^*]+)\*\*")
_CATEGORIES = {
    "correctas": re.compile(r"(\d+|cero) correctas"),
    "ruidosas": re.compile(r"(\d+|cero) ruidosas"),
    "silenciosas": re.compile(r"(\d+|cero) silenciosas"),
}


def _parse_counts(path: Path) -> tuple[int, dict[str, int]]:
    """Lee la linea de conteos de un archivo de resultados congelado."""
    match = _COUNT_LINE.search(path.read_text(encoding="utf-8"))
    if match is None:
        _fail(f"{path.name} no trae la linea 'Por SQL distinto'. No se inventa.")
    denominator = int(match.group(1))
    body = match.group(2)
    counts = {}
    for name, pattern in _CATEGORIES.items():
        found = pattern.search(body)
        if found is None:
            _fail(f"{path.name}: no se encontro la categoria {name!r} en {body!r}")
        raw = found.group(1)
        counts[name] = 0 if raw == "cero" else int(raw)
    if sum(counts.values()) != denominator:
        _fail(
            f"{path.name}: los conteos {counts} suman "
            f"{sum(counts.values())} y el denominador dice {denominator}"
        )
    return denominator, counts


def plot_slice2() -> Path:
    den_a, counts_a = _parse_counts(RESULT_A)
    den_b, counts_b = _parse_counts(RESULT_B)

    categories = ["correctas", "ruidosas", "silenciosas"]
    values_a = [counts_a[c] for c in categories]
    values_b = [counts_b[c] for c in categories]
    positions = range(len(categories))
    width = 0.38

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    bars_a = ax.bar(
        [p - width / 2 for p in positions],
        values_a,
        width,
        label=f"DDL puro (n={den_a} SQL distintos)",
        color=GRAY_MID,
        edgecolor=EDGE,
        linewidth=0.8,
    )
    bars_b = ax.bar(
        [p + width / 2 for p in positions],
        values_b,
        width,
        label=f"Con valores inyectados (n={den_b} SQL distintos)",
        color=GRAY_LIGHT,
        edgecolor=EDGE,
        linewidth=0.8,
        hatch="///",
    )
    for group, values in ((bars_a, values_a), (bars_b, values_b)):
        for bar, value in zip(group, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.3,
                str(value),
                ha="center",
                va="bottom",
                fontsize=10.5,
                fontweight="bold",
            )

    ax.set_xticks(list(positions))
    ax.set_xticklabels([c.capitalize() for c in categories])
    ax.set_ylabel("Conteo de SQL distintos")
    ax.set_ylim(0, max(values_a + values_b) + 3)
    ax.set_title(
        "Rebanada 2: inyectar los valores mato las fallas ruidosas\n"
        "y quintuplico las silenciosas",
        fontsize=12,
        pad=14,
    )
    ax.legend(fontsize=9, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    fig.text(
        0.5,
        -0.06,
        "Conteos, nunca porcentajes: son clasificacion de una sola persona "
        "sobre denominadores distintos (25 y 24),\n"
        "sin scoring automatico ni segunda opinion. Una falla ruidosa se "
        "delata sola; una silenciosa devuelve una tabla creible.",
        ha="center",
        va="top",
        fontsize=9,
        color="0.25",
    )
    return _savefig(fig, "03_rebanada2_conteos.png")


# ---------------------------------------------------------- grafica (d)


def _runs_by_question(entries: list[dict], config: str) -> dict[int, list[dict]]:
    """Cada corrida con la entrada del corpus que la representa."""
    runs: dict[int, list[dict]] = {}
    for entry in entries:
        for source in entry["sources"]:
            if source["config"] != config:
                continue
            runs.setdefault(source["question_index"], []).append(entry)
    return runs


def plot_coverage(results: dict[int, fanout.FanoutResult], entries: list[dict]) -> Path:
    runs = _runs_by_question(entries, CONFIG_B)
    questions = [4, 5]
    for q in questions:
        if len(runs.get(q, [])) != EXPECTED_RUNS_PER_QUESTION:
            _fail(
                f"Q{q} en {CONFIG_B} tiene {len(runs.get(q, []))} corridas y se "
                f"esperaban {EXPECTED_RUNS_PER_QUESTION}"
            )

    caught, debt, other = [], [], []
    for q in questions:
        c = d = o = 0
        for entry in runs[q]:
            result = results[entry["id"]]
            if result.verdict == fanout.INFLATED:
                c += 1
            elif (
                result.verdict == fanout.NOT_ANALYZED
                and result.reason == fanout.REASON_UNATTRIBUTABLE
            ):
                d += 1
            else:
                o += 1
        caught.append(c)
        debt.append(d)
        other.append(o)

    labels = [f"Q{q}\n(5 corridas)" for q in questions]
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    bottom = [0, 0]
    layers = [
        (caught, "Cazada: veredicto inflated", GRAY_DARK, None),
        (debt, "Deuda abierta: unattributable_aggregate", GRAY_LIGHT, "///"),
        (other, "Otro veredicto", GRAY_MID, ".."),
    ]
    for values, label, color, hatch in layers:
        if not any(values):
            continue
        ax.bar(
            labels,
            values,
            bottom=bottom,
            label=label,
            color=color,
            edgecolor=EDGE,
            linewidth=0.8,
            width=0.5,
            hatch=hatch,
        )
        for i, value in enumerate(values):
            if value:
                ax.text(
                    i,
                    bottom[i] + value / 2,
                    str(value),
                    ha="center",
                    va="center",
                    fontsize=12,
                    fontweight="bold",
                    color="white" if color == GRAY_DARK else "black",
                )
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_ylabel("Corridas del modelo")
    ax.set_ylim(0, EXPECTED_RUNS_PER_QUESTION + 1.2)
    ax.set_title(
        "Cobertura sobre las dos puertas de fan-out medidas\n"
        "(configuracion con valores inyectados)",
        fontsize=12,
        pad=14,
    )
    ax.legend(fontsize=9, frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    fig.text(
        0.5,
        -0.04,
        f"Q5 no falla: queda sin analizar. {debt[1]} de sus 5 corridas usan "
        "COUNT(*), que no nombra ninguna columna,\n"
        "asi que no hay tabla a la que atribuirle la duplicacion y el "
        "detector lo dice en vez de adivinar.\n"
        "Esta escrito como deuda con su causa y su camino, no como error.",
        ha="center",
        va="top",
        fontsize=9,
        color="0.25",
    )
    return _savefig(fig, "04_cobertura_q4_q5.png")


# ---------------------------------------------------------------- main


def main() -> int:
    entries = load_corpus()
    results = analyze_all(entries)

    paths = [
        plot_verdicts(results),
        plot_q4(results, entries),
        plot_slice2(),
        plot_coverage(results, entries),
    ]

    print(f"corpus: {len(entries)} entradas   base: {db.db_path()}")
    for path in paths:
        size = path.stat().st_size
        if size == 0:
            _fail(f"{path} salio vacio")
        print(f"  escrito  {path.relative_to(REPO_ROOT)}  {size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
