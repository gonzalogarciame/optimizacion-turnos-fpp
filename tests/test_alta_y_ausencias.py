"""Turnos y dependientes nuevos con día de inicio, y días de ausencia de los dependientes."""
import shutil
import sqlite3
from pathlib import Path

import pytest

from turnos.webapp import estado
from turnos.webapp.server import crear_app

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "TURNOS_2026_definitivo_original.xlsx"

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Falta el fixture TURNOS_2026_definitivo_original.xlsx")


@pytest.fixture
def cliente(tmp_path):
    xlsx = tmp_path / "campamento.xlsx"
    shutil.copy2(FIXTURE, xlsx)
    estado._estado["ruta"] = str(xlsx)
    c = crear_app().test_client()
    assert c.get("/api/estado").get_json()["cargado"]
    return c, str(tmp_path / "campamento.db")


def _plazas(db, turno):
    con = sqlite3.connect(db)
    try:
        return dict(con.execute("SELECT dia, plazas FROM plazas_dia WHERE turno = ?", (turno,)).fetchall())
    finally:
        con.close()


def test_turno_nuevo_empieza_el_dia_indicado(cliente):
    c, db = cliente
    info = c.get("/api/estado").get_json()
    dias, reopt = info["dias"], info["dia_reoptimizacion"]
    inicio = max(d for d in dias if d >= reopt)
    cuerpo = {"nombre": "biblioteca", "plazas": 2, "sexo_req": "-", "esfuerzo": 1, "dia_inicio": inicio}
    assert c.post("/api/tipos_turno/nuevo", json=cuerpo).status_code == 200
    p = _plazas(db, "biblioteca")
    assert all(p[d] == (2 if d >= inicio else 0) for d in dias)
    # sin día de inicio empieza el día desde el que se re-optimiza
    assert c.post("/api/tipos_turno/nuevo", json={**cuerpo, "nombre": "otro", "dia_inicio": None}).status_code == 200
    p = _plazas(db, "otro")
    assert all(p[d] == (2 if d >= reopt else 0) for d in dias)
    # un día que no existe, o ya cerrado, se rechaza
    assert c.post("/api/tipos_turno/nuevo", json={**cuerpo, "nombre": "x", "dia_inicio": dias[-1] + 5}).status_code == 400
    if reopt > dias[0]:
        assert c.post("/api/tipos_turno/nuevo", json={**cuerpo, "nombre": "y", "dia_inicio": dias[0]}).status_code == 400


def test_dependiente_nuevo_llega_el_dia_indicado(cliente):
    c, db = cliente
    info = c.get("/api/estado").get_json()
    dias, reopt = info["dias"], info["dia_reoptimizacion"]
    inicio = max(d for d in dias if d >= reopt)
    r = c.post("/api/dependientes/nuevo", json={"acampado": "Nuevo Acampado", "sexo_req": "-", "esfuerzo": 3, "dia_inicio": inicio})
    assert r.status_code == 200
    ausente = c.get("/api/dependientes/ausencias").get_json()["Nuevo Acampado"]
    assert ausente == [d for d in dias if d < inicio]


def test_ausencias_de_un_dependiente(cliente):
    c, db = cliente
    info = c.get("/api/estado").get_json()
    dias, reopt = info["dias"], info["dia_reoptimizacion"]
    libres = [d for d in dias if d >= reopt]
    nombre = next(iter(c.get("/api/dependientes/ausencias").get_json()))
    dia = libres[-1]

    # el día tenía a alguien asignado: al marcarlo ausente ya no hace falta nadie
    con = sqlite3.connect(db)
    con.execute("DELETE FROM dependiente_ausente WHERE acampado = ? AND dia = ?", (nombre, dia))
    con.execute("DELETE FROM asignaciones WHERE tipo = 'dependiente' AND clave = ? AND dia = ?", (nombre, dia))
    monitor = con.execute("SELECT nombre FROM monitores LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO asignaciones (tipo, clave, dia, pos, monitor, fijada) VALUES ('dependiente', ?, ?, 0, ?, 0)", (nombre, dia, monitor))
    con.commit()
    con.close()

    previas = [d for d in c.get("/api/dependientes/ausencias").get_json()[nombre] if d != dia]
    r = c.post("/api/dependientes/ausencias", json={"ausencias": {nombre: previas + [dia]}})
    assert r.status_code == 200
    assert dia in c.get("/api/dependientes/ausencias").get_json()[nombre]
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM asignaciones WHERE tipo = 'dependiente' AND clave = ? AND dia = ?", (nombre, dia)).fetchone()[0] == 0
    con.close()
    dep = next(s for s in c.get("/api/rejilla").get_json()["secciones"] if s["tipo"] == "dependiente")
    fila = next(f for f in dep["filas"] if f["etiqueta"] == nombre)
    assert fila["celdas"][str(dia)]["v"] == "-"

    # se puede volver a quitar la ausencia
    r = c.post("/api/dependientes/ausencias", json={"ausencias": {nombre: previas}})
    assert r.status_code == 200
    assert dia not in c.get("/api/dependientes/ausencias").get_json()[nombre]

    # errores: dependiente desconocido, día fuera del campamento
    assert c.post("/api/dependientes/ausencias", json={"ausencias": {"Nadie": [dia]}}).status_code == 400
    assert c.post("/api/dependientes/ausencias", json={"ausencias": {nombre: [dias[-1] + 9]}}).status_code == 400
