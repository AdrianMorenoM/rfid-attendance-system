#!/usr/bin/env bash
# run_all.sh — ejecuta la suite de sistema y genera reports/reporte.html
#
# Uso:  bash tests_system/run_all.sh [opciones] [argumentos extra de pytest]
#   --no-live       omite las pruebas contra los servicios reales
#   --destructive   permite reinicios, kill -9 y bloqueos de BD en el sistema real
#   --hardware      permite la prueba con el lector RC522 real (con --destructive)
#   --cov           mide cobertura (líneas, ramas y funciones) incluyendo la suite existente
#   --existing      ejecuta también la suite existente (shared/tests, sin smoke)
# Ejemplos:  run_all.sh --no-live            run_all.sh --cov            run_all.sh -k seguridad
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"
[ -f venv/bin/activate ] && source venv/bin/activate
REP="$HERE/reports"
mkdir -p "$REP"
rm -f "$REP"/junit_*.xml "$REP"/.coverage* "$REP"/functions.json "$REP"/coverage.xml "$REP"/perf.json
rm -rf "$REP/htmlcov"

COV=0; EXISTING=0; EXTRA=()
for a in "$@"; do
  case "$a" in
    --cov) COV=1 ;;
    --existing) EXISTING=1 ;;
    *) EXTRA+=("$a") ;;
  esac
done

RC=0
COV_FIRST=(); COV_LAST=()
if [ $COV -eq 1 ]; then
  COV_FIRST=(--cov --cov-config="$HERE/.coveragerc" --cov-report=)
  COV_LAST=(--cov --cov-append --cov-config="$HERE/.coveragerc" --cov-report=term:skip-covered
            --cov-report="html:$REP/htmlcov" --cov-report="xml:$REP/coverage.xml")
fi

if [ $EXISTING -eq 1 ] || [ $COV -eq 1 ]; then
  echo "== Suite existente (shared/tests) =="
  python -m pytest -c shared/tests/pytest.ini shared/tests --ignore=shared/tests/test_smoke.py \
    -p no:cacheprovider -q --junitxml="$REP/junit_existente.xml" "${COV_FIRST[@]}" || RC=$?
fi

echo "== Suite de sistema (tests_system) =="
python -m pytest -c "$HERE/pytest.ini" "$HERE" -p no:cacheprovider \
  --junitxml="$REP/junit_sistema.xml" "${COV_LAST[@]}" "${EXTRA[@]}" || RC=$?

[ $COV -eq 1 ] && python "$HERE/coverage_functions.py"
python "$HERE/make_report.py"
echo
echo "Para verlo desde tu PC (Tailscale):  cd $REP && python3 -m http.server 8088"
TS_IP="$(tailscale ip -4 2>/dev/null | head -1)"
echo "y abre  http://${TS_IP:-<ip-de-tailscale>}:8088/reporte.html"
exit $RC
