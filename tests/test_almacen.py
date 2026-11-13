"""Base de datos SQLite como alternativa al Excel: importar, leer y guardar una solución.

La prueba clave: leer un campamento desde la base de datos da exactamente el
mismo `Datos` que leerlo desde el Excel del que se importó.
"""
import copy
import dataclasses
import shutil
import sqlite3
from pathlib import Path

import pytest

from turnos.almacen.cargar import leer_datos_db
from turnos.almacen.guardar import escribir_solucion_db
from turnos.almacen.importar import importar_excel
from turnos.io_excel.lector import leer_datos
from turnos.modelo.construir import construir_modelo
from turnos.modelo.errores import ErrorDatos
from turnos.resolver import resolver_modelo

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


@pytest.fixture
def libro(tmp_path):
    destino = tmp_path / "turnos.xlsx"
    shutil.copy2(FIXTURE, destino)
    return str(destino)


@pytest.fixture
def bd(libro, tmp_path):
    ruta = str(tmp_path / "campamento.db")
    importar_excel(libro, ruta)
    return ruta


def _sin_filas(d):
    """Quita lo que solo tiene sentido en el Excel (nº de fila de cada bloque)."""
    d = copy.deepcopy(d)
    for t in d.turnos.values():
        t.fila_ini = t.fila_fin = None
    for p in d.dependientes.values():
        p.fila = 0
    return d


def _iguales(a, b):
    a, b = _sin_filas(a), _sin_filas(b)
    for f in dataclasses.fields(a):
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if f.name == "fijaciones":
            va, vb = sorted(map(dataclasses.astuple, va)), sorted(map(dataclasses.astuple, vb))
        assert va == vb, f"difiere el campo '{f.name}'"


def _ini_fin(libro):
    cfg = leer_datos(libro).cfg
    return cfg.dia_inicio, cfg.dia_fin


# ----------------------------------------------------------------------
# Equivalencia con el Excel
# ----------------------------------------------------------------------
@pytest.mark.parametrize("variante", ["tal_cual", "desde_inicio", "tramo", "tramo_en_medio"])
def test_la_base_de_datos_da_los_mismos_datos_que_el_excel(libro, bd, variante):
    ini, fin = _ini_fin(libro)
    desde, hasta = {
        "tal_cual": (None, None),
        "desde_inicio": (ini, None),
        "tramo": (ini, ini + 2),
        "tramo_en_medio": (ini + 1, fin - 1),
    }[variante]
    try:
        esperado = leer_datos(libro, desde=desde, hasta=hasta)
    except ErrorDatos as exc:
        # Si el Excel rechaza el caso (histórico incompleto), la base de datos lo rechaza igual.
        with pytest.raises(ErrorDatos):
            leer_datos_db(bd, desde=desde, hasta=hasta)
        assert "incompleto" in str(exc)
        return
    _iguales(esperado, leer_datos_db(bd, desde=desde, hasta=hasta))


def test_importar_no_modifica_el_excel(libro, tmp_path):
    antes = Path(libro).read_bytes()
    importar_excel(libro, str(tmp_path / "x.db"))
    assert Path(libro).read_bytes() == antes


def test_importar_no_pisa_una_base_existente(libro, bd):
    with pytest.raises(FileExistsError):
        importar_excel(libro, bd)
    importar_excel(libro, bd, sobrescribir=True)  # con la opción explícita sí
    assert not Path(bd + ".tmp").exists()


def test_importar_un_excel_roto_no_deja_ficheros(tmp_path):
    roto = tmp_path / "roto.xlsx"
    roto.write_bytes(b"no es un excel")
    destino = tmp_path / "roto.db"
    with pytest.raises(Exception):
        importar_excel(str(roto), str(destino))
    assert not destino.exists()
    assert not Path(str(destino) + ".tmp").exists()


def test_leer_una_base_que_no_existe_falla_sin_crearla(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_datos_db(str(tmp_path / "no_existe.db"))
    assert not (tmp_path / "no_existe.db").exists()


# ----------------------------------------------------------------------
# Guardar una solución y volver a leerla
# ----------------------------------------------------------------------
def _resolver_un_dia(bd, dia):
    datos = leer_datos_db(bd, desde=dia, hasta=dia)
    datos.cfg = dataclasses.replace(datos.cfg, solver="appsi_highs", time_limit_s=60)
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")
    return datos, sol


def test_guardar_solucion_solo_toca_los_dias_generados(bd):
    ini = leer_datos_db(bd).cfg.dia_inicio
    con = sqlite3.connect(bd)
    otros_antes = con.execute("SELECT * FROM asignaciones WHERE dia <> ? ORDER BY 1,2,3,4", (ini,)).fetchall()
    con.close()

    datos, sol = _resolver_un_dia(bd, ini)
    n = escribir_solucion_db(bd, datos, sol)
    assert n > 0

    con = sqlite3.connect(bd)
    assert con.execute("SELECT * FROM asignaciones WHERE dia <> ? ORDER BY 1,2,3,4", (ini,)).fetchall() == otros_antes
    # Cada turno del día queda con tantos monitores como plazas (más lo que ya aceptaba de extra)
    for turno in datos.turnos:
        puestos = con.execute(
            "SELECT COUNT(*) FROM asignaciones WHERE tipo='turno' AND clave=? AND dia=?", (turno, ini)
        ).fetchone()[0]
        assert puestos >= datos.plazas[(turno, ini)] - sol.falta.get((turno, ini), 0) - 1e-6
    con.close()


def test_lo_generado_queda_como_historia_para_seguir_generando(bd):
    """El día generado y guardado vale como pasado al generar los siguientes (incluye quién lleva a cada dependiente)."""
    ini = leer_datos_db(bd).cfg.dia_inicio
    datos, sol = _resolver_un_dia(bd, ini)
    escribir_solucion_db(bd, datos, sol)

    siguiente = leer_datos_db(bd, desde=ini + 1, hasta=ini + 1)  # no debe protestar por el día `ini`
    assert any(d == ini for (_, _, d) in siguiente.historico_x)
    asignados = {(a, d): m for (a, d), m in siguiente.asig_dependiente.items() if d == ini and m}
    assert asignados, "los cuidadores de dependientes del día ya generado deben quedar fijados"


def test_una_celda_fijada_se_respeta_al_generar(bd):
    ini = leer_datos_db(bd).cfg.dia_inicio
    datos = leer_datos_db(bd, desde=ini, hasta=ini)
    turno = next(iter(datos.turnos))
    # Un monitor disponible que no esté ya fijado ese día
    ocupados = {f.monitor for f in datos.fijaciones if f.dia == ini}
    candidato = next(
        m for m, mo in datos.monitores.items()
        if datos.disponibilidad[(m, ini)] == "D" and m not in ocupados and mo.sexo in ("M", "F")
        and datos.turnos[turno].sexo_req in ("-", mo.sexo) and mo.permite_descanso
    )
    con = sqlite3.connect(bd)
    con.execute("DELETE FROM asignaciones WHERE dia = ?", (ini,))
    con.execute("INSERT INTO asignaciones (tipo, clave, dia, pos, monitor, fijada) VALUES ('turno', ?, ?, 0, ?, 1)", (turno, ini, candidato))
    con.commit()
    con.close()

    datos, sol = _resolver_un_dia(bd, ini)
    assert sol.x.get((candidato, turno, ini)) == 1
    escribir_solucion_db(bd, datos, sol)
    con = sqlite3.connect(bd)
    fila = con.execute(
        "SELECT fijada FROM asignaciones WHERE tipo='turno' AND clave=? AND dia=? AND monitor=?", (turno, ini, candidato)
    ).fetchone()
    con.close()
    assert fila == (1,), "lo fijado sigue marcado como fijado tras guardar la solución"


def test_no_se_borra_un_monitor_con_turnos(bd):
    con = sqlite3.connect(bd)
    con.execute("PRAGMA foreign_keys = ON")
    nombre = con.execute("SELECT monitor FROM asignaciones LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM monitores WHERE nombre = ?", (nombre,))
    con.close()
