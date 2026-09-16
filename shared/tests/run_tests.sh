#!/usr/bin/env bash
# run_tests.sh — ejecuta la suite completa de pruebas RFID
# Uso: bash shared/tests/run_tests.sh [--smoke] [--cov]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV="$ROOT_DIR/venv"

cd "$ROOT_DIR"
source "$VENV/bin/activate"

ARGS="-v --tb=short"
SMOKE=0
COV=0

for arg in "$@"; do
    case "$arg" in
        --smoke) SMOKE=1 ;;
        --cov)   COV=1   ;;
    esac
done

echo "========================================"
echo " Suite de pruebas RFID ITSOEH"
echo " Root: $ROOT_DIR"
echo "========================================"

if [[ $COV -eq 1 ]]; then
    pip install pytest-cov -q
    ARGS="$ARGS --cov=. --cov-report=term-missing --cov-report=html:shared/tests/htmlcov"
fi

if [[ $SMOKE -eq 0 ]]; then
    echo "[!] Omitiendo smoke tests (usa --smoke para incluirlos)"
    ARGS="$ARGS --ignore=shared/tests/test_smoke.py"
fi

echo ""
echo "[1/3] Pruebas unitarias (reader, db)..."
python -m pytest shared/tests/test_reader.py $ARGS || true

echo ""
echo "[2/3] Pruebas de integración Flask..."
python -m pytest shared/tests/test_crud_api.py shared/tests/test_dashboard_y_db.py $ARGS || true

if [[ $SMOKE -eq 1 ]]; then
    echo ""
    echo "[3/3] Smoke tests (servicios reales)..."
    python -m pytest shared/tests/test_smoke.py $ARGS || true
fi

echo ""
echo "========================================"
echo " Listo. Revisa la salida anterior."
if [[ $COV -eq 1 ]]; then
    echo " Cobertura HTML: shared/tests/htmlcov/index.html"
fi
echo "========================================"