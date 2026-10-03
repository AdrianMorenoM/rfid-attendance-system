#!/usr/bin/env python3
"""Genera reports/reporte.html a partir de junit_*.xml, coverage.xml, functions.json y perf.json."""
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REP = HERE / "reports"
SECCIONES = OrderedDict([
    ("01", "01 · RFID end-to-end"), ("02", "02 · Seguridad"), ("03", "03 · Resiliencia"),
    ("04", "04 · Rendimiento"), ("05", "05 · Backups"), ("06", "06 · Integraciones"),
    ("ex", "Suite existente (shared/tests)"),
])
UMBRAL = {"lineas": float(os.environ.get("COV_MIN_LINES", 75)),
          "ramas": float(os.environ.get("COV_MIN_BRANCHES", 60)),
          "funciones": float(os.environ.get("COV_MIN_FUNCTIONS", 75))}


def humaniza(texto):
    return re.sub(r"(?<!^)(?=[A-Z])", " ", texto.replace("Test", "", 1)).strip()


def leer_junit(path):
    out = []
    for tc in ET.parse(path).getroot().iter("testcase"):
        clase, estado, detalle = tc.get("classname", ""), "pass", ""
        for tag, est in (("failure", "fail"), ("error", "fail"), ("skipped", "skip")):
            el = tc.find(tag)
            if el is not None:
                estado, detalle = est, f"{el.get('message') or ''}\n{el.text or ''}".strip()
                break
        m = re.search(r"test_(\d\d)_", clase)
        partes = clase.split(".")
        if m:
            grupo = humaniza(partes[-1]) if partes[-1].startswith("Test") else "General"
        else:
            grupo = clase or "General"
        out.append({"sec": m.group(1) if m else "ex", "grupo": grupo, "nombre": tc.get("name", ""),
                    "t": float(tc.get("time") or 0), "estado": estado, "detalle": detalle})
    return out


def esc(x):
    return html.escape(str(x))


def tabla_seccion(tests):
    grupos = OrderedDict()
    for t in tests:
        grupos.setdefault(t["grupo"], []).append(t)
    filas = []
    for g, lst in grupos.items():
        n = {e: sum(1 for t in lst if t["estado"] == e) for e in ("pass", "fail", "skip")}
        filas.append(f"<tr class='g'><td colspan='3'><b>{esc(g)}</b> "
                     f"<span class='ok'>{n['pass']} ✓</span> <span class='ko'>{n['fail']} ✗</span> "
                     f"<span class='sk'>{n['skip']} ⏭</span></td></tr>")
        for t in lst:
            icono = {"pass": "✓", "fail": "✗", "skip": "⏭"}[t["estado"]]
            nombre = esc(t["nombre"].replace("test_", "", 1).replace("_", " "))
            det = f"<details><summary>{nombre}</summary><pre>{esc(t['detalle'])}</pre></details>" \
                if t["detalle"] else nombre
            filas.append(f"<tr class='{t['estado']}'><td class='i'>{icono}</td><td>{det}</td>"
                         f"<td class='t'>{t['t']:.2f}s</td></tr>")
    return "<table>" + "".join(filas) + "</table>"


def cobertura():
    caja = []
    cx = REP / "coverage.xml"
    if cx.exists():
        r = ET.parse(cx).getroot()
        caja.append(("Líneas", float(r.get("line-rate", 0)) * 100, UMBRAL["lineas"],
                     f"{r.get('lines-covered')}/{r.get('lines-valid')}"))
        caja.append(("Ramas", float(r.get("branch-rate", 0)) * 100, UMBRAL["ramas"],
                     f"{r.get('branches-covered')}/{r.get('branches-valid')}"))
    fj = REP / "functions.json"
    if fj.exists():
        d = json.loads(fj.read_text())
        caja.append(("Funciones", d["pct"], UMBRAL["funciones"], f"{d['covered']}/{d['total']}"))
    if not caja:
        return "<p class='sk'>Sin datos de cobertura. Ejecuta <code>run_all.sh --cov</code>.</p>"
    tarjetas = "".join(
        f"<div class='card {'okb' if p >= u else 'kob'}'><div class='big'>{p:.1f}%</div>"
        f"<div>{n}</div><small>{det} · mínimo {u:.0f}%</small></div>" for n, p, u, det in caja)
    extra = ""
    if (REP / "htmlcov" / "index.html").exists():
        extra += "<a href='htmlcov/index.html'>Reporte HTML detallado (líneas y ramas)</a> · "
    if (REP / "coverage.xml").exists():
        extra += "<a href='coverage.xml'>coverage.xml</a>"
    sin = ""
    if fj.exists():
        lst = json.loads(fj.read_text()).get("sin_cubrir", [])[:40]
        if lst:
            sin = "<details><summary>Funciones sin cubrir (primeras 40)</summary><pre>" + \
                  esc("\n".join(lst)) + "</pre></details>"
    return f"<div class='cards'>{tarjetas}</div><p>{extra}</p>{sin}"


def rendimiento():
    pj = REP / "perf.json"
    if not pj.exists():
        return ""
    d = json.loads(pj.read_text())
    filas = "".join(f"<tr><td>{esc(k)}</td><td><code>{esc(json.dumps(v, ensure_ascii=False))}</code></td></tr>"
                    for k, v in sorted(d.items()))
    return f"<h2>Mediciones de rendimiento</h2><table>{filas}</table>"


def main():
    tests = []
    for f in sorted(REP.glob("junit_*.xml")):
        tests += leer_junit(f)
    tot = {e: sum(1 for t in tests if t["estado"] == e) for e in ("pass", "fail", "skip")}
    secciones = []
    for clave, titulo in SECCIONES.items():
        lst = [t for t in tests if t["sec"] == clave]
        if not lst:
            continue
        n = {e: sum(1 for t in lst if t["estado"] == e) for e in ("pass", "fail", "skip")}
        abierto = "open" if n["fail"] else ""
        secciones.append(
            f"<details class='sec' {abierto}><summary><b>{esc(titulo)}</b> — "
            f"<span class='ok'>{n['pass']} ✓</span> <span class='ko'>{n['fail']} ✗</span> "
            f"<span class='sk'>{n['skip']} ⏭</span></summary>{tabla_seccion(lst)}</details>")
    estado = "ko" if tot["fail"] else "ok"
    doc = f"""<!doctype html><html lang="es"><meta charset="utf-8">
<title>Reporte de pruebas — RFID</title>
<style>
body{{font:15px system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#222}}
.ok{{color:#1a7f37}}.ko{{color:#cf222e}}.sk{{color:#9a6700}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0}}td{{padding:3px 8px;border-bottom:1px solid #eee;vertical-align:top}}
tr.g td{{background:#f6f8fa}}tr.fail td{{background:#fff1f0}}td.i{{width:1.5rem;text-align:center}}td.t{{width:4.5rem;color:#888;text-align:right}}
.sec{{border:1px solid #d0d7de;border-radius:6px;margin:.6rem 0;padding:.4rem .8rem}}summary{{cursor:pointer}}
.cards{{display:flex;gap:1rem;flex-wrap:wrap}}.card{{border-radius:8px;padding:1rem 1.4rem;min-width:150px}}
.okb{{background:#dafbe1}}.kob{{background:#ffebe9}}.big{{font-size:2rem;font-weight:700}}
pre{{white-space:pre-wrap;background:#f6f8fa;padding:.6rem;border-radius:6px;font-size:12px}}
code{{font-size:12px}}h1 .{estado}{{font-weight:700}}
@media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}tr.g td{{background:#161b22}}td{{border-color:#30363d}}
.sec{{border-color:#30363d}}pre{{background:#161b22}}tr.fail td{{background:#3d1d20}}.okb{{background:#12351f}}.kob{{background:#3d1d20}}}}
</style>
<h1>Reporte de pruebas — sistema RFID</h1>
<p>Generado {datetime.now():%Y-%m-%d %H:%M:%S} ·
<b class="ok">{tot['pass']} pasaron</b> · <b class="ko">{tot['fail']} fallaron</b> · <b class="sk">{tot['skip']} omitidas</b></p>
{''.join(secciones) or '<p>No se encontraron resultados (junit_*.xml).</p>'}
<h2>07 · Cobertura</h2>{cobertura()}
{rendimiento()}
</html>"""
    (REP / "reporte.html").write_text(doc, encoding="utf-8")
    print(f"Reporte: {REP / 'reporte.html'}  ({tot['pass']} ok, {tot['fail']} fallos, {tot['skip']} omitidas)")


if __name__ == "__main__":
    main()
