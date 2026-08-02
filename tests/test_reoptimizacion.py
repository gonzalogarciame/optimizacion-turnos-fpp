"""Prueba de aceptación de extremo a extremo sobre el Excel real (§11 y §8
de las instrucciones): resuelve todo el horizonte, comprueba el checklist de
reglas, vuelve a resolver re-optimizando desde el día 24 y comprueba que
18-23 salen carácter por carácter idénticos.

Usa `appsi_highs` (solver libre) en vez del `gurobi` que trae el Excel,
porque la licencia de prueba de `pip install gurobipy` limita el modelo a
2000 variables/restricciones y este problema genera unas 6500 (ver README
§7). El resto del pipeline es exactamente el mismo compile-y-resuelve que
usaría con Gurobi.

Usa una copia fija en `tests/fixtures/`, no el Excel de producción de la
raíz del repo: ese fichero lo edita el usuario (altas de monitores,
fijaciones, disponibilidad...) y sus datos reales pueden legítimamente dejar
de cumplir invariantes genéricos como "ningún monitor de fin de semana
descansa nunca" (p. ej. si un día se llena de fijaciones manuales y no
queda sitio, `finde_sin_descanso` se degrada a blanda a propósito). El test
necesita un fichero estable para poder afirmar esos invariantes con
seguridad.
"""
import shutil
from collections import defaultdict
from pathlib import Path

import openpyxl
import pytest

from turnos.io_excel.escritor import escribir_solucion
from turnos.io_excel.lector import leer_datos
from turnos.modelo.construir import construir_modelo
from turnos.resolver import resolver_modelo

RAIZ = Path(__file__).resolve().parents[1]
CANDIDATOS = [RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"]
CANDIDATOS = [p for p in CANDIDATOS if p.exists()]

pytestmark = pytest.mark.skipif(
    not CANDIDATOS,
    reason="No se encuentra tests/fixtures/TURNOS_2026_definitivo_original.xlsx",
)


def _copia_con_highs(tmp_path, sufijo=""):
    origen = CANDIDATOS[0]
    destino = tmp_path / f"prueba{sufijo}.xlsx"
    shutil.copy2(origen, destino)
    wb = openpyxl.load_workbook(destino)
    ws = wb["CONFIG"]
    for fila in range(2, ws.max_row + 1):
        clave = str(ws.cell(fila, 1).value or "").strip().upper()
        if clave == "SOLVER":
            ws.cell(fila, 2).value = "appsi_highs"
        if clave == "TIME_LIMIT_S":
            ws.cell(fila, 2).value = 60
    wb.save(destino)
    return destino


def _resolver(ruta, desde=None):
    datos = leer_datos(str(ruta), desde=desde)
    modelo = construir_modelo(datos)
    solucion = resolver_modelo(modelo, datos)
    return datos, solucion


def test_horizonte_completo_factible_y_cubierto(tmp_path):
    ruta = _copia_con_highs(tmp_path)
    datos, sol = _resolver(ruta)

    assert sol.estado == "optimo"
    assert sum(sol.falta.values()) < 1e-6, "debería cubrir todos los turnos (holgura positiva)"

    # Ningún monitor con dos cosas el mismo día.
    cosas = defaultdict(int)
    for (mo, t, d), v in sol.x.items():
        cosas[(mo, d)] += v
    for (mo, p, d), v in sol.y.items():
        cosas[(mo, d)] += v
    for (mo, d), v in sol.r.items():
        cosas[(mo, d)] += v
    assert all(c <= 1 for c in cosas.values())

    # Ningún monitor de fin de semana (PERMITE_DESCANSO=0) descansando.
    finde = {mo for mo, mon in datos.monitores.items() if not mon.permite_descanso}
    assert not any(mo in finde for (mo, d), v in sol.r.items() if v == 1)

    # Nadie vigila de noche y va a comedor al día siguiente.
    vig = {"vigilancia_chicos", "vigilancia_chicas", "vigilancia_D_chicos", "vigilancia_D_chicas"}
    activos = {(mo, t, d) for (mo, t, d), v in sol.x.items() if v == 1}
    for (mo, t, d) in activos:
        if t in vig:
            assert (mo, "comedor", d + 1) not in activos

    # Las 6 fijaciones de FIJACIONES se respetan.
    for f in datos.fijaciones:
        if f.origen != "FIJACIONES" or f.tipo != "OBLIGA":
            continue
        assert sol.x.get((f.monitor, f.turno, f.dia)) == 1, f"fijación no respetada: {f}"

    # Esfuerzo repartido: cmax-cmin no debería ser enorme.
    cargas = {}
    for mo in datos.monitores:
        dp = datos.dias_presente.get(mo, 0)
        if dp == 0:
            continue
        carga = sum(datos.turnos[t].esfuerzo for (m2, t, d), v in sol.x.items() if m2 == mo and v == 1)
        carga += sum(datos.dependientes[p].esfuerzo for (m2, p, d), v in sol.y.items() if m2 == mo and v == 1)
        cargas[mo] = carga / dp
    assert max(cargas.values()) - min(cargas.values()) < 10


def test_reoptimizar_no_toca_el_pasado(tmp_path):
    ruta = _copia_con_highs(tmp_path, "_A")
    datos1, sol1 = _resolver(ruta)
    assert sol1.estado == "optimo"
    escribir_solucion(str(ruta), datos1, sol1, dry_run=False)

    datos2, sol2 = _resolver(ruta, desde=24)
    assert sol2.estado == "optimo"
    ruta_salida = escribir_solucion(str(ruta), datos2, sol2, dry_run=True)

    wb1 = openpyxl.load_workbook(ruta)
    wb2 = openpyxl.load_workbook(ruta_salida)
    ws1, ws2 = wb1["TURNOS"], wb2["TURNOS"]

    # columnas B..G = días 18..23 (histórico bajo DIA_REOPTIMIZACION=24)
    for fila in range(1, ws1.max_row + 1):
        for col in range(2, 8):
            assert ws1.cell(fila, col).value == ws2.cell(fila, col).value, (
                f"celda ({fila},{col}) cambió al re-optimizar desde 24, debería ser histórica"
            )
