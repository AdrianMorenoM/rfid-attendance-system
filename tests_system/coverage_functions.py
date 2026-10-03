#!/usr/bin/env python3
"""Cobertura de FUNCIONES (coverage.py solo reporta líneas y ramas).

Una función cuenta como cubierta si se ejecutó al menos una línea de su cuerpo.
Lee reports/.coverage (generado por run_all.sh --cov) y escribe reports/functions.json.
"""
import ast
import json
import sys
from pathlib import Path

import coverage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REP = HERE / "reports"
FUENTES = ["crud", "dashboard", "shared"]
EXCLUIR = {"tests", "venv", ".venv", "__pycache__", "backups", "tests_system"}


def archivos():
    for d in FUENTES:
        if (ROOT / d).is_dir():
            for p in sorted((ROOT / d).rglob("*.py")):
                if not EXCLUIR & set(p.relative_to(ROOT).parts):
                    yield p


def main():
    datos = REP / ".coverage"
    if not datos.exists():
        print("No hay datos de cobertura: ejecuta run_all.sh --cov primero.")
        return 1
    cov = coverage.Coverage(data_file=str(datos), config_file=str(HERE / ".coveragerc"))
    cov.load()
    total = cubiertas = 0
    sin_cubrir, por_archivo = [], {}
    for p in archivos():
        try:
            _, ejecutables, _, faltan, _ = cov.analysis2(str(p))
        except Exception:
            continue
        ejec, falt = set(ejecutables), set(faltan)
        t = c = 0
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            rango = set(range(n.body[0].lineno, (n.end_lineno or n.lineno) + 1)) & ejec
            if not rango:  # sin código ejecutable (docstring, pragma: no cover)
                continue
            t += 1
            if rango - falt:
                c += 1
            else:
                sin_cubrir.append(f"{p.relative_to(ROOT)}:{n.lineno}  {n.name}()")
        por_archivo[str(p.relative_to(ROOT))] = {"total": t, "cubiertas": c}
        total, cubiertas = total + t, cubiertas + c
    pct = 100 * cubiertas / total if total else 0.0
    (REP / "functions.json").write_text(json.dumps(
        {"total": total, "covered": cubiertas, "pct": round(pct, 2), "por_archivo": por_archivo,
         "sin_cubrir": sin_cubrir}, indent=2, ensure_ascii=False))
    print(f"Cobertura de funciones: {cubiertas}/{total} = {pct:.1f}%")
    for f, d in por_archivo.items():
        if d["total"]:
            print(f"  {f:<40} {d['cubiertas']:>3}/{d['total']:<3}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
