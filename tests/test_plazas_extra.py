"""Turnos que aceptan más gente que sus plazas (PLAZAS_MAX_POR_DIA) y rejilla que crece.

Caso de uso: el día de llegada/salida hay pocos turnos y sobra gente; los monitores
de fin de semana prefieren no descansar, así que algún turno tiene que aceptar
más personas de las que necesita.
"""
import copy
import dataclasses
import shutil
from collections import Counter
from pathlib import Path

import openpyxl
import pytest

from turnos.io_excel.escritor import escribir_solucion, hacer_copia_seguridad
from turnos.io_excel.estructura import ErrorPlazas, guardar_plazas
from turnos.io_excel.lector import leer_datos
from turnos.io_excel.rejilla import leer_rejilla
from turnos.modelo.construir import construir_modelo
from turnos.modelo.datos import Monitor
from turnos.resolver import resolver_modelo

from .test_construir_sintetico import _datos_sinteticos

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"
necesita_fixture = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


# ----------------------------------------------------------------------
# Modelo (datos sintéticos)
# ----------------------------------------------------------------------
def _con_muchos_de_finde():
    """3 monitores de siempre + 3 de fin de semana: 6 personas para 3 puestos (cocina, vigilancia, dependiente)."""
    datos = _datos_sinteticos()
    for i in (1, 2, 3):
        nombre = f"Finde{i}"
        datos.monitores[nombre] = Monitor(nombre=nombre, sexo="F", grupo="FINDE", permite_descanso=False, penalizar_descanso=False)
        for d in datos.dias:
            datos.disponibilidad[(nombre, d)] = "D"
        datos.dias_presente[nombre] = len(datos.dias)
    # Ana descansa o trabaja como el resto; lo que importa es que los de FINDE no pueden descansar.
    return datos


def test_sin_sitio_para_los_de_finde_es_infactible():
    datos = _con_muchos_de_finde()
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado == "infactible"


def test_turno_que_acepta_extras_absorbe_a_los_de_finde():
    datos = _con_muchos_de_finde()
    datos.plazas_max = {("cocina", d): 5 for d in datos.dias}  # cocina: 1 plaza, acepta hasta 5
    m = construir_modelo(datos)
    assert len(m.extra_idx) == len(datos.dias)

    sol = resolver_modelo(m, datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")
    assert sum(sol.falta.values()) == pytest.approx(0)
    assert not any(mo.startswith("Finde") and v == 1 for (mo, d), v in sol.r.items())  # nadie de finde descansa
    por_turno_dia = Counter((t, d) for (mo, t, d), v in sol.x.items() if v == 1)
    assert all(n <= datos.tope(t, d) for (t, d), n in por_turno_dia.items())
    assert any(n > datos.plazas[(t, d)] for (t, d), n in por_turno_dia.items())  # se usaron extras de verdad


def test_sin_plazas_max_el_modelo_es_el_de_siempre():
    datos = _datos_sinteticos()
    m = construir_modelo(datos)
    assert len(m.extra_idx) == 0
    assert "plazas_extra" not in m._penalizaciones


def test_lo_ya_escrito_por_encima_de_las_plazas_no_vuelve_infactible_el_modelo():
    """Una casilla de más fijada a mano (o en un día histórico) amplía el tope de ese día."""
    from turnos.modelo.datos import Fijacion

    datos = _datos_sinteticos()
    datos.fijaciones = [
        Fijacion(dia=1, turno="cocina", monitor="Ana", tipo="OBLIGA"),
        Fijacion(dia=1, turno="cocina", monitor="Luis", tipo="OBLIGA"),  # cocina solo tiene 1 plaza
    ]
    datos.plazas_tope = {("cocina", 1): 2}
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")


# ----------------------------------------------------------------------
# Excel: guardar plazas y ampliar la rejilla (fixture)
# ----------------------------------------------------------------------
@pytest.fixture
def excel(tmp_path):
    destino = tmp_path / "turnos.xlsx"
    shutil.copy2(FIXTURE, destino)
    wb = openpyxl.load_workbook(destino, read_only=True, data_only=True)
    dia_inicio = int(next(r[1] for r in wb["CONFIG"].iter_rows(values_only=True) if r[0] == "DIA_INICIO"))
    wb.close()
    return str(destino), dia_inicio


def _contenido(rej):
    """Qué hay en cada casilla, sin depender de en qué fila está."""
    salida = {}
    for sec in rej["secciones"]:
        for fila in sec["filas"]:
            for dia, c in fila["celdas"].items():
                if not c["v"]:
                    continue
                clave = (sec["clave"], fila["etiqueta"] if sec["tipo"] == "dependiente" else None, dia)
                salida.setdefault(clave, []).append(c["v"])
    return {k: sorted(v) for k, v in salida.items()}


@necesita_fixture
def test_ampliar_la_rejilla_no_pierde_ni_mueve_datos(excel):
    ruta, dia_inicio = excel
    datos = leer_datos(ruta, desde=dia_inicio)
    antes = _contenido(leer_rejilla(ruta, datos))
    asig_antes = dict(datos.asig_dependiente)

    dia = datos.dias[0]
    res = guardar_plazas(ruta, datos, [
        {"turno": "limpieza", "dia": dia, "plazas": 0, "max": 12},
        {"turno": "comedor", "dia": dia, "plazas": 4, "max": 9},
    ], hacer_copia_seguridad)
    assert res["filas_añadidas"]["limpieza"] == 12 - 5 and Path(res["backup"]).exists()

    despues = leer_datos(ruta, desde=dia_inicio)
    bloques = sorted((t.fila_ini, t.fila_fin, t.turno) for t in despues.turnos.values())
    assert all(a[1] < b[0] for a, b in zip(bloques, bloques[1:])), "los bloques de turnos se solapan"
    assert despues.turnos["limpieza"].fila_fin - despues.turnos["limpieza"].fila_ini + 1 >= 12
    assert despues.turnos["comedor"].fila_fin - despues.turnos["comedor"].fila_ini + 1 >= 9
    assert despues.plazas_max[("limpieza", dia)] == 12 and despues.plazas_max[("comedor", dia)] == 9
    assert despues.tope("limpieza", dia) == 12 and despues.plazas[("limpieza", dia)] == 0
    assert despues.asig_dependiente == asig_antes

    assert _contenido(leer_rejilla(ruta, despues)) == antes  # lo escrito sigue donde estaba

    wb = openpyxl.load_workbook(ruta)
    ws = wb["TURNOS"]
    etiquetas = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)]
    assert etiquetas.count("DESCANSO") == 1
    assert min(d.fila for d in despues.dependientes.values()) > max(t.fila_fin for t in despues.turnos.values())
    assert any(str(r) == f"A{despues.turnos['limpieza'].fila_ini}:A{despues.turnos['limpieza'].fila_fin}" for r in ws.merged_cells.ranges)
    assert [r[1] for r in wb["CONFIG"].iter_rows(values_only=True) if r[0] == "W_EXTRA"] == [40]


@necesita_fixture
def test_plazas_invalidas_no_tocan_el_fichero(excel):
    ruta, dia_inicio = excel
    datos = leer_datos(ruta, desde=dia_inicio)
    antes = Path(ruta).read_bytes()
    with pytest.raises(ErrorPlazas) as exc:
        guardar_plazas(ruta, datos, [
            {"turno": "limpieza", "dia": datos.dias[0], "plazas": 3, "max": 6},   # válida
            {"turno": "no_existe", "dia": datos.dias[0], "plazas": 1, "max": None},
            {"turno": "limpieza", "dia": 999, "plazas": 1, "max": None},
            {"turno": "limpieza", "dia": datos.dias[0], "plazas": -2, "max": None},
        ], hacer_copia_seguridad)
    assert len(exc.value.errores) == 3
    assert Path(ruta).read_bytes() == antes
    assert not list(Path(ruta).parent.glob("*_backup_*"))


@necesita_fixture
def test_generar_con_extras_y_escribir_sin_modificar_datos(excel):
    ruta, dia_inicio = excel
    datos = leer_datos(ruta, desde=dia_inicio)
    cambios = [{"turno": "limpieza", "dia": d, "plazas": datos.plazas[("limpieza", d)], "max": datos.plazas[("limpieza", d)] + 3}
               for d in datos.dias]
    guardar_plazas(ruta, datos, cambios, hacer_copia_seguridad)

    datos = leer_datos(ruta, desde=dia_inicio)
    datos.cfg = dataclasses.replace(datos.cfg, solver="appsi_highs", time_limit_s=60)
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")
    por_turno_dia = Counter((t, d) for (mo, t, d), v in sol.x.items() if v == 1)
    assert all(n <= datos.tope(t, d) for (t, d), n in por_turno_dia.items())

    filas_antes = {t: (v.fila_ini, v.fila_fin) for t, v in datos.turnos.items()}
    previa = str(Path(ruta).with_name("previa.xlsx"))
    escribir_solucion(ruta, datos, sol, ruta_salida=previa)
    assert {t: (v.fila_ini, v.fila_fin) for t, v in datos.turnos.items()} == filas_antes  # `datos` no se toca

    # Lo escrito es exactamente la solución, también si la rejilla ha tenido que crecer.
    rej = leer_rejilla(previa, leer_datos(previa, desde=dia_inicio))
    escritos = Counter()
    for sec in rej["secciones"]:
        if sec["tipo"] == "turno":
            for fila in sec["filas"]:
                for dia, c in fila["celdas"].items():
                    if c["v"]:
                        escritos[(c["v"], sec["titulo"], int(dia))] += 1
    assert escritos == Counter({(mo, t, d): 1 for (mo, t, d), v in sol.x.items() if v == 1})
