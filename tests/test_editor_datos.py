"""Guardar disponibilidad y plazas por día desde las interfaces.

Regresión: `DataFrame.itertuples()` renombra las columnas que no son identificadores
válidos ("18" -> "_1"), así que al guardar no se encontraban los valores de cada día y se
escribía "D" (disponibilidad) o 0 (plazas) en todas las casillas.
"""
import shutil
from pathlib import Path

import openpyxl
import pytest

from turnos.interfaz.editor_datos import (
    guardar_disponibilidad_df,
    guardar_plazas_por_dia_df,
    leer_disponibilidad_df,
    leer_plazas_por_dia_df,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


@pytest.fixture
def excel(tmp_path):
    destino = tmp_path / "turnos.xlsx"
    shutil.copy2(FIXTURE, destino)
    wb = openpyxl.load_workbook(destino, read_only=True, data_only=True)
    cfg = {r[0]: r[1] for r in wb["CONFIG"].iter_rows(values_only=True) if r[0]}
    wb.close()
    dias = list(range(int(cfg["DIA_INICIO"]), int(cfg["DIA_FIN"]) + 1))
    return str(destino), dias


def _como_dict(df, clave):
    return {fila[clave]: {k: v for k, v in fila.items() if k != clave} for fila in df.to_dict(orient="records")}


def test_guardar_disponibilidad_solo_cambia_lo_editado(excel):
    ruta, dias = excel
    antes = leer_disponibilidad_df(ruta, dias)
    nombres = list(antes["NOMBRE"])
    esperado = _como_dict(antes, "NOMBRE")

    esperado[nombres[0]][str(dias[2])] = "X"
    esperado[nombres[1]][str(dias[-1])] = "R"
    df = antes.copy()
    df.loc[0, str(dias[2])] = "X"
    df.loc[1, str(dias[-1])] = "R"
    # Solo se envían las filas tocadas, como hace la web.
    guardar_disponibilidad_df(ruta, df.iloc[[0, 1]], dias)

    despues = _como_dict(leer_disponibilidad_df(ruta, dias), "NOMBRE")
    assert despues == esperado


def test_guardar_plazas_por_dia_solo_cambia_lo_editado(excel):
    ruta, dias = excel
    antes = leer_plazas_por_dia_df(ruta, dias)
    esperado = _como_dict(antes, "TURNO")
    turno = list(antes["TURNO"])[0]
    esperado[turno][str(dias[3])] = int(esperado[turno][str(dias[3])]) + 2

    df = antes.copy()
    df.loc[0, str(dias[3])] = esperado[turno][str(dias[3])]
    guardar_plazas_por_dia_df(ruta, df, dias)

    despues = _como_dict(leer_plazas_por_dia_df(ruta, dias), "TURNO")
    assert despues == esperado
