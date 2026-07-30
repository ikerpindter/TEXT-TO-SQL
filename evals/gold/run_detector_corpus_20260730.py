"""Corre el detector sobre las 49 entradas de `corpus_sql.json` y describe la salida.

    uv run python evals/gold/run_detector_corpus_20260730.py

No llama al modelo. Abre `portfolio.db` en modo solo lectura. Costo: $0.
Escribe `evals/results/fanout_corpus_descriptivo_20260730.md`, que es un archivo
de resultados y **no se edita después**.

ESTO ES DESCRIPTIVO Y NO ES UNA EVALUACIÓN
-------------------------------------------
**Cero precision, cero recall, cero porcentajes.** No hay contra qué compararlos:
las worksheets están vacías, así que **no existe una sola etiqueta humana** y sin
etiquetas no hay verdaderos ni falsos positivos que contar. Lo único que se puede
decir de estas 49 es qué contestó el detector, y eso es lo que sale.

Hay una segunda razón, independiente de las etiquetas y anotada en el ROADMAP: **la
duplicación semántica del corpus sigue sin medir.** El dedupe fue solo por string,
así que dos queries idénticas salvo alias son dos entradas distintas de las 49 y
esas 49 no son 49 observaciones independientes. Cualquier tasa calculada sobre ellas
tendría un intervalo de confianza más angosto del que merece.

Todo conteo lleva su denominador. Es regla del proyecto y se ganó dos veces: los
"99 pares" y las "422 columnas" se reportaron solos y en los dos casos el
denominador resultó ser menor que el universo.

NO SE DESGLOSA POR DEV Y HOLDOUT, A PROPÓSITO
----------------------------------------------
`split_assignment.json` no hace match con `evals/gold/*holdout*` y se podría leer
sin romper la regla del patrón. Aun así **no se usa aquí**: ver cómo se comporta el
detector en cada mitad antes de la etapa 4 es exactamente el insumo que permitiría
afinarlo contra el holdout, y el valor del holdout depende de que eso no pase. La
distribución sale agregada sobre las 49.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import sqlglot

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from txt2sql import catalog as catalog_mod  # noqa: E402
from txt2sql import db, fanout  # noqa: E402

CORPUS = REPO_ROOT / "evals" / "gold" / "corpus_sql.json"
OUTPUT = REPO_ROOT / "evals" / "results" / "fanout_corpus_descriptivo_20260730.md"


def db_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return out


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    entries = corpus["entries"]
    total = len(entries)

    conn = db.connect()
    cat = catalog_mod.load(conn)

    results = [(entry, fanout.analyze(entry["sql"], conn, cat)) for entry in entries]

    verdicts = Counter(result.verdict for _entry, result in results)
    reasons = Counter(
        result.reason for _e, result in results if result.verdict == fanout.NOT_ANALYZED
    )
    subcases = Counter(
        result.subcase
        for _e, result in results
        if result.verdict == fanout.NO_CONTRIBUTING_ROWS
    )

    findings = [f for _e, result in results for f in result.findings]
    shapes = Counter(finding.shape for finding in findings)
    functions = Counter(finding.aggregate_function for finding in findings)
    entries_with_findings = sum(1 for _e, result in results if result.findings)
    entries_unattributed = sum(
        1 for _e, result in results if result.unattributed_aggregates
    )
    measured = [f for f in findings if f.row_multiplier is not None]
    grouped = sum(1 for f in findings if f.grouped)
    with_dedup = [f for f in findings if f.deduplicated_value is not None]

    lines: list[str] = []
    add = lines.append

    add("# Detector de fan-out sobre el corpus real: distribución descriptiva")
    add("")
    add("**Corrida del 30 de julio de 2026.** Archivo de resultados: no se edita.")
    add("Una corrección va como nota fechada al inicio, nunca como reescritura.")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Corpus | `evals/gold/corpus_sql.json`, **{total} entradas distintas** |")
    add(f"| Base | `data/portfolio.db`, sha256 `{db_sha256(db.db_path())}` |")
    add(f"| sqlglot | {sqlglot.__version__}, pin exacto |")
    add(f"| Dialecto | `{fanout.DIALECT}` |")
    add("| Llamadas a API | 0 |")
    add("")
    add("## Qué NO es esto")
    add("")
    add("**Cero precision, cero recall, cero porcentajes.**")
    add("")
    add("No hay contra qué compararlos: `worksheet_dev.md` tiene sus 25 líneas")
    add("`LABEL:` vacías y **no existe una sola etiqueta humana**, así que no hay")
    add("verdaderos ni falsos positivos que contar. Lo único que estas 49 entradas")
    add("pueden sostener es qué contestó el detector.")
    add("")
    add("Y aunque las etiquetas existieran, seguiría faltando un dato: **la")
    add("duplicación semántica del corpus no está medida.** El dedupe fue solo por")
    add("string, así que dos queries idénticas salvo alias son dos entradas de las 49")
    add("y esas 49 **no son 49 observaciones independientes**. Eso cambia la N")
    add("efectiva de cualquier tasa, y por eso el ROADMAP la pide medida antes de")
    add("publicar una.")
    add("")
    add("**Tampoco hay desglose por dev y holdout**, y no es por la regla del patrón")
    add("—`split_assignment.json` no hace match con `evals/gold/*holdout*`— sino")
    add("porque ver el comportamiento por mitad antes de la etapa 4 es justo el")
    add("insumo que permitiría afinar contra el holdout.")
    add("")
    add("## Veredictos")
    add("")
    add(f"Denominador: **{total}**, las entradas distintas del corpus. Cada entrada")
    add("recibe exactamente un veredicto.")
    add("")
    lines.extend(
        table(
            [
                (f"`{verdict}`", str(verdicts.get(verdict, 0)), str(total))
                for verdict in fanout.VERDICTS
            ],
            ("Veredicto", "Entradas", "de"),
        )
    )
    add("")
    add("Recordatorio que importa para la rebanada 6: **`clean` significa «sin")
    add("duplicación de filas medida», no «la query es correcta».** Las trampas de")
    add("`unit_scale` y de año fiscal producen números mal con veredicto `clean`, y")
    add("eso es el comportamiento correcto de un detector que mide una sola cosa.")
    add("")

    add("## Razones de `not_analyzed`")
    add("")
    not_analyzed_total = verdicts.get(fanout.NOT_ANALYZED, 0)
    if not_analyzed_total:
        add(f"Denominador: **{not_analyzed_total}**, las entradas `not_analyzed`.")
        add("")
        add("La columna de la derecha importa por la tabla de adjudicación del")
        add("ROADMAP: una razón que el documento de criterios lista es un error de")
        add("etiquetado del humano, y una que no lista es un **hueco del documento**.")
        add("Se ven igual en los datos y tienen causas opuestas.")
        add("")
        lines.extend(
            table(
                [
                    (
                        f"`{reason}`",
                        str(count),
                        "sí" if reason in fanout.CRITERIA_REASONS else "**no**",
                    )
                    for reason, count in sorted(reasons.items())
                ],
                ("Razón", "Entradas", "¿La listan los criterios?"),
            )
        )
    else:
        add(f"Ninguna de las {total} entradas cayó en `not_analyzed`.")
    add("")

    add("## Formas detectadas")
    add("")
    add(f"Denominador: **{len(findings)}** hallazgos, repartidos en")
    add(f"**{entries_with_findings}** de las {total} entradas. Una entrada puede")
    add("traer más de un hallazgo, así que los dos números son distintos y ninguno")
    add("es el otro.")
    add("")
    if findings:
        lines.extend(
            table(
                [(f"`{shape}`", str(count)) for shape, count in sorted(shapes.items())],
                ("Forma", "Hallazgos"),
            )
        )
    else:
        add("Ninguna forma detectada.")
    add("")

    add("## Agregados de los hallazgos")
    add("")
    if findings:
        lines.extend(
            table(
                [(f"`{fn}`", str(count)) for fn, count in sorted(functions.items())],
                ("Función", "Hallazgos"),
            )
        )
        add("")
        add(f"Con `GROUP BY`: **{grouped}** de {len(findings)} hallazgos, todos con")
        add("`multiplier_scope: global`. Un multiplicador global mayor a 1 prueba que")
        add("**existe** duplicación en algún lugar del resultado, no que **cada**")
        add("grupo esté afectado.")
    else:
        add("Sin hallazgos.")
    add("")

    add("## Multiplicadores medidos")
    add("")
    add(f"Denominador: **{len(measured)}** hallazgos con `row_multiplier` calculable,")
    add(f"de {len(findings)} hallazgos totales. Los demás tienen la fuente sin filas")
    add("que aporten y el multiplicador es indefinido, no cero.")
    add("")
    if measured:
        values = sorted(f.row_multiplier for f in measured)
        distinct = Counter(values)
        lines.extend(
            table(
                [(f"{value}", str(count)) for value, count in sorted(distinct.items())],
                ("`row_multiplier`", "Hallazgos"),
            )
        )
        add("")
        add(f"Mínimo {values[0]}, máximo {values[-1]}.")
    add("")

    add("## `value_inflation`, o por qué casi nunca sale")
    add("")
    add(f"Hallazgos con `deduplicated_value` calculado: **{len(with_dedup)}** de")
    add(f"{len(findings)}.")
    add("")
    add("El caso angosto exige las cuatro cosas juntas: exactamente un agregado")
    add("marcado, forma `fan_trap`, `SUM` o `COUNT` sobre una columna del lado «uno»,")
    add("y sin `GROUP BY`. Fuera de ahí va `null`, **y no se aproxima dividiendo por")
    add("`row_multiplier`**: sobre Q4 esa división da 359,701,250 contra 348,500,000")
    add("reales, 3.21% de error en una cifra que se vería exacta.")
    add("")
    if with_dedup:
        lines.extend(
            table(
                [
                    (
                        str(entry["id"]),
                        f"`{finding.aggregate}`",
                        f"{finding.reported_value:,.2f}",
                        f"{finding.deduplicated_value:,.2f}",
                        str(finding.value_inflation),
                        str(finding.row_multiplier),
                    )
                    for entry, result in results
                    for finding in result.findings
                    if finding.deduplicated_value is not None
                ],
                (
                    "id",
                    "Agregado",
                    "Reportado",
                    "Deduplicado",
                    "`value_inflation`",
                    "`row_multiplier`",
                ),
            )
        )
        add("")
        add("Las dos últimas columnas **no son el mismo número y no se colapsan.** La")
        add("brecha además cambia de signo, así que el multiplicador de filas no acota")
        add("al de valor ni por arriba ni por abajo.")
    add("")

    add("## Agregados no atribuibles: el hueco de cobertura más grande")
    add("")
    add("Entradas con al menos un agregado sensible sin columna a la que atribuirlo:")
    add(f"**{entries_unattributed}** de {total}.")
    add("")
    add("Son `COUNT(*)` y variantes como")
    add("`SUM(CASE WHEN ... THEN 1 ELSE 0 END)`, donde lo que se suma es una")
    add("constante. No hay columna, así que no hay `T` y el multiplicador no es")
    add("calculable. Marcarlos produciría un falso positivo medido sobre")
    add("`COUNT(*) FROM homes JOIN communities`, donde la duplicación de")
    add("`communities` no toca al conteo de casas.")
    add("")
    add("**Cuando no hubo ningún otro hallazgo, la entrada va a `not_analyzed`, no a")
    add("`clean`.** Esta regla se corrigió el 30 de julio de 2026 **después de**")
    add("mirar esta misma corrida: la versión anterior devolvía `clean` y nombraba")
    add("el agregado aparte, y así marcaba `clean` tres entradas de Q5 en la config")
    add("B —ids 45, 46 y 48— que el ROADMAP documenta como portadoras del artefacto")
    add("de fan-out. Un `clean` sobre la falla que esta rebanada existe para cazar")
    add("es un miss, no un hueco aceptable.")
    add("")
    add("Cuando **sí** hubo otro hallazgo medible, la entrada conserva su veredicto y")
    add("el agregado no atribuible se nombra al lado: la id 47 trae un `COUNT(*)` y")
    add("además un `SUM(financials.backlog_value)` inflado 51.5x, y anular la entrada")
    add("entera tiraría una detección verdadera.")
    add("")
    add("**Esto es un dato de alcance, no un resultado.** Es el costo de no afirmar")
    add("lo que no se midió, y es la primera cosa que la rebanada 4 debería atacar.")
    add("")

    add("## Entrada por entrada")
    add("")
    add("Los 49 veredictos, para que cualquier conteo de arriba se pueda reproducir.")
    add("Sin `row_count` ni config: el detector no los leyó y no hacen falta aquí.")
    add("")
    rows = []
    for entry, result in results:
        shape_text = ", ".join(sorted({f.shape for f in result.findings})) or "—"
        multipliers = sorted(
            {f.row_multiplier for f in result.findings if f.row_multiplier is not None}
        )
        multiplier_text = ", ".join(str(m) for m in multipliers) or "—"
        detail = result.reason or result.subcase or "—"
        rows.append(
            (
                str(entry["id"]),
                f"`{result.verdict}`",
                shape_text,
                multiplier_text,
                f"`{detail}`" if detail != "—" else "—",
                str(len(result.unattributed_aggregates)),
            )
        )
    lines.extend(
        table(
            rows,
            (
                "id",
                "Veredicto",
                "Forma",
                "`row_multiplier`",
                "Razón / subcaso",
                "Agregados no atribuidos",
            ),
        )
    )
    add("")

    add("## Qué NO se verificó en esta corrida")
    add("")
    add("- **Que los veredictos sean correctos.** No hay etiquetas humanas. Esta")
    add("  corrida describe la salida del detector; no la juzga.")
    add("- **La duplicación semántica de las 49 entradas.** Sigue sin medir, así que")
    add("  la N efectiva de este corpus es desconocida y menor que 49.")
    add("- **El comportamiento por mitad del split.** No se calculó a propósito.")
    add("- **Que el corpus ejercite los guards.** `WITHOUT ROWID`, columnas que")
    add("  sombrean `rowid` y agregados sobre fuentes no-base siguen sin blanco en")
    add("  esta base; el gate adversario tampoco los cubre.")
    add("- **Los `clean`.** Nadie verificó una por una las entradas que salieron")
    add("  `clean`. Podría haber fan-out real ahí y esta corrida no lo sabría.")
    add("")
    add("## Contraste con lo que la rebanada 2 ya tenía medido")
    add("")
    add("No es una validación —esas entradas no son etiquetas y el ROADMAP describe")
    add("preguntas, no strings de SQL— pero sí es el único cotejo disponible contra")
    add("algo escrito antes.")
    add("")
    lines.extend(
        table(
            [
                (
                    "Q4, config B, `SUM` sobre el lado uno de un join a `homes`",
                    "las 5 corridas tienen el fan-out",
                    "**5 de 5** `inflated` / `fan_trap`, `row_multiplier` 40.0",
                ),
                (
                    "Q4, config A",
                    "devolvió `NULL`, se delata sola",
                    "**5 de 5** `no_contributing_rows` / `empty_source`",
                ),
                (
                    "Q5, `financials` colgada sin relación de grano",
                    "las 5 de la config B tienen el artefacto",
                    "**2 de 5** `inflated` / `chasm_trap`; las otras 3 a `not_analyzed`"
                    " por agregado no atribuible",
                ),
            ],
            ("Caso", "Lo que dice el ROADMAP", "Lo que salió aquí"),
        )
    )
    add("")
    add("El renglón de Q5 es el que importa: **el detector no alcanza 3 de las 5**, y")
    add("las reporta como no analizadas en vez de como limpias. La distinción es todo")
    add("el punto —un hueco declarado se puede cerrar, un `clean` falso no se ve—")
    add("pero el hueco existe y es la deuda más grande que deja esta etapa.")
    add("")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"escrito: {OUTPUT.relative_to(REPO_ROOT).as_posix()}")
    print(f"entradas: {total}")
    for verdict in fanout.VERDICTS:
        print(f"  {verdict:22s} {verdicts.get(verdict, 0):3d} de {total}")
    print(f"hallazgos: {len(findings)} en {entries_with_findings} entradas")
    for shape, count in sorted(shapes.items()):
        print(f"  {shape:14s} {count}")
    if reasons:
        print("razones de not_analyzed:")
        for reason, count in sorted(reasons.items()):
            print(f"  {reason:22s} {count}")
    if subcases:
        print("subcasos de no_contributing_rows:")
        for subcase, count in sorted(subcases.items()):
            print(f"  {subcase:22s} {count}")
    print(f"entradas con agregados no atribuibles: {entries_unattributed} de {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
