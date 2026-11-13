"""Generar solo unos días: horizonte recortado con `hasta` (interfaz: selector «Días»)."""
import dataclasses
import shutil
from pathlib import Path

import openpyxl
import pytest

from turnos.io_excel.escritor import escribir_solucion
from turnos.io_excel.lector import leer_datos
from turnos.modelo.construir import construir_modelo
from turnos.resolver import resolver_modelo

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


@pytest.fixture
def excel(tmp_path):
    destino = tmp_path / "turnos.xlsx"
    shutil.copy2(FIXTURE, destino)
    return str(destino)


def _inicio(ruta):
    return leer_datos(ruta).cfg.dia_inicio


def test_hasta_recorta_el_horizonte(excel):
    ini = _inicio(excel)
    datos = leer_datos(excel, desde=ini, hasta=ini + 1)
    assert datos.dias == [ini, ini + 1]
    assert datos.cfg.dia_fin == ini + 1
    assert all(d in datos.dias for (_, d) in datos.disponibilidad)
    # sin `hasta` se lee todo el horizonte, como siempre
    assert len(leer_datos(excel, desde=ini).dias) > 2


def test_hasta_invalido(excel):
    ini = _inicio(excel)
    fin = leer_datos(excel).cfg.dia_fin
    with pytest.raises(ValueError):
        leer_datos(excel, desde=ini + 2, hasta=ini + 1)
    with pytest.raises(ValueError):
        leer_datos(excel, desde=ini, hasta=fin + 1)
    with pytest.raises(ValueError):
        leer_datos(excel, desde=ini, hasta=ini - 1)


def test_generar_un_dia_no_toca_los_demas(excel):
    ini = _inicio(excel)
    datos = leer_datos(excel, desde=ini, hasta=ini)
    datos.cfg = dataclasses.replace(datos.cfg, solver="appsi_highs", time_limit_s=60)
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")
    assert all(d == ini for (_, _, d) in sol.x)

    salida = excel.replace("turnos.xlsx", "salida.xlsx")
    escribir_solucion(excel, datos, sol, ruta_salida=salida)

    def contenido(ruta):
        ws = openpyxl.load_workbook(ruta)["TURNOS"]
        return {
            (c.row, c.column): c.value
            for fila in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=3, max_col=ws.max_column)
            for c in fila
        }

    # La columna del segundo día en adelante (col 3 en adelante) queda igual que antes de generar.
    assert contenido(salida) == contenido(excel)
