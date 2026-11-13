"""Lectura/escritura celda a celda de la rejilla TURNOS (interfaz web).

Trabaja siempre sobre una copia temporal del fixture congelado: nunca sobre
los Excel de `datos/`.
"""
import hashlib
import shutil
from pathlib import Path

import openpyxl
import pytest

from turnos.io_excel.lector import leer_datos
from turnos.io_excel.rejilla import ErrorEdicionRejilla, guardar_cambios_rejilla, leer_rejilla

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


@pytest.fixture
def excel(tmp_path):
    destino = tmp_path / "turnos.xlsx"
    shutil.copy2(FIXTURE, destino)
    cfg_wb = openpyxl.load_workbook(destino, read_only=True, data_only=True)
    dia_inicio = next(r[1] for r in cfg_wb["CONFIG"].iter_rows(values_only=True) if r[0] == "DIA_INICIO")
    cfg_wb.close()
    return str(destino), leer_datos(str(destino), desde=int(dia_inicio))


def _huella(ruta):
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def _celda(rejilla, tipo, fila, dia):
    for sec in rejilla["secciones"]:
        for f in sec["filas"]:
            if sec["tipo"] == tipo and f["fila"] == fila:
                return f["celdas"][str(dia)]
    raise AssertionError((tipo, fila, dia))


def test_lee_todas_las_secciones(excel):
    ruta, datos = excel
    rej = leer_rejilla(ruta, datos)
    tipos = [s["tipo"] for s in rej["secciones"]]
    assert tipos.count("turno") == len(datos.turnos)
    assert tipos.count("dependiente") == 1 and tipos.count("descanso") == 1
    dependientes = next(s for s in rej["secciones"] if s["tipo"] == "dependiente")
    assert len(dependientes["filas"]) == len(datos.dependientes)
    for sec in rej["secciones"]:
        for fila in sec["filas"]:
            assert set(fila["celdas"]) == {str(d) for d in datos.dias}


def test_editar_un_dia_cualquiera_y_fijarlo(excel):
    ruta, datos = excel
    rej = leer_rejilla(ruta, datos)
    sec = next(s for s in rej["secciones"] if s["tipo"] == "turno")
    fila = sec["filas"][0]["fila"]
    dia = datos.dias[0]  # el primer día: histórico en cuanto se re-optimice desde más adelante
    monitor = next(iter(datos.monitores))

    res = guardar_cambios_rejilla(ruta, datos, [
        {"tipo": "turno", "fila": fila, "dia": dia, "valor": monitor, "fijado": True},
    ])
    assert res["escritas"] == 1 and Path(res["backup"]).exists()

    celda = _celda(leer_rejilla(ruta, datos), "turno", fila, dia)
    assert celda == {"v": monitor, "f": True}

    # Vaciar y desfijar deja la casilla como nueva.
    guardar_cambios_rejilla(ruta, datos, [
        {"tipo": "turno", "fila": fila, "dia": dia, "valor": "", "fijado": False},
    ])
    assert _celda(leer_rejilla(ruta, datos), "turno", fila, dia) == {"v": "", "f": False}


def test_editar_dependiente_escribe_asig_dependiente(excel):
    ruta, datos = excel
    dep = next(iter(datos.dependientes.values()))
    dia = datos.dias[0]
    monitor = next(m for m in datos.monitores.values() if dep.sexo_monitor_req in ("-", m.sexo)).nombre

    guardar_cambios_rejilla(ruta, datos, [
        {"tipo": "dependiente", "fila": dep.fila, "dia": dia, "valor": monitor, "fijado": True},
    ])
    datos2 = leer_datos(ruta, desde=datos.dias[0])
    assert datos2.asig_dependiente[(dep.acampado, dia)] == monitor  # lo que lee el modelo
    assert _celda(leer_rejilla(ruta, datos2), "dependiente", dep.fila, dia)["v"] == monitor

    guardar_cambios_rejilla(ruta, datos, [
        {"tipo": "dependiente", "fila": dep.fila, "dia": dia, "valor": "-", "fijado": False},
    ])
    datos3 = leer_datos(ruta, desde=datos.dias[0])
    assert datos3.asig_dependiente[(dep.acampado, dia)] is None  # "no presente"


def test_apodos_se_guardan_con_el_nombre_canonico(excel):
    ruta, datos = excel
    wb = openpyxl.load_workbook(ruta, read_only=True)
    alias = [(r[0], r[1]) for r in wb["ALIAS"].iter_rows(min_row=2, values_only=True) if r[0] and r[1]]
    wb.close()
    if not alias:
        pytest.skip("El fixture no tiene apodos")
    variante, canonico = alias[0]
    fila = next(t.fila_ini for t in datos.turnos.values() if t.fila_ini is not None)
    guardar_cambios_rejilla(ruta, datos, [{"tipo": "turno", "fila": fila, "dia": datos.dias[0], "valor": variante}])
    valor = _celda(leer_rejilla(ruta, datos), "turno", fila, datos.dias[0])["v"]
    assert valor in datos.monitores  # canónico, no el apodo


def test_cambios_invalidos_no_tocan_el_fichero(excel):
    ruta, datos = excel
    antes = _huella(ruta)
    fila = next(t.fila_ini for t in datos.turnos.values() if t.fila_ini is not None)
    monitor = next(iter(datos.monitores))
    malos = [
        {"tipo": "turno", "fila": fila, "dia": datos.dias[0], "valor": monitor},         # válido
        {"tipo": "turno", "fila": fila, "dia": datos.dias[0], "valor": "Nadie Inventado"},
        {"tipo": "turno", "fila": 9999, "dia": datos.dias[0], "valor": monitor},
        {"tipo": "turno", "fila": fila, "dia": 999, "valor": monitor},
        {"tipo": "turno", "fila": fila, "dia": datos.dias[0], "valor": "-"},              # '-' solo vale en dependientes
    ]
    with pytest.raises(ErrorEdicionRejilla) as exc:
        guardar_cambios_rejilla(ruta, datos, malos)
    assert len(exc.value.errores) == 4
    assert _huella(ruta) == antes  # ni siquiera el cambio válido se escribió
    assert not list(Path(ruta).parent.glob("*_backup_*"))


def test_notas_al_pie_de_plazas_no_son_turnos(excel):
    """Una nota de texto bajo PLAZAS_POR_DIA no genera aviso; un turno inventado con cifras, sí."""
    ruta, datos = excel
    wb = openpyxl.load_workbook(ruta)
    ws = wb["PLAZAS_POR_DIA"]
    fila = ws.max_row + 2
    ws.cell(fila, 1).value = "Nota: los dias de llegada y salida llevan menos turnos."
    wb.save(ruta)
    dia0 = datos.dias[0]
    assert not [a for a in leer_datos(ruta, desde=dia0).avisos if "no existe en TIPOS_TURNO" in a]

    wb = openpyxl.load_workbook(ruta)
    ws = wb["PLAZAS_POR_DIA"]
    ws.cell(fila + 1, 1).value = "turno_inventado"
    ws.cell(fila + 1, 2).value = 3
    wb.save(ruta)
    assert [a for a in leer_datos(ruta, desde=dia0).avisos if "turno_inventado" in a]
