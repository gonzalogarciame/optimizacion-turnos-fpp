"""Primer uso: sin ningún campamento, la web permite crear uno desde cero (sin Excel, sin internet)."""
import pytest

from turnos.almacen.cargar import leer_datos_db
from turnos.almacen.nuevo import crear_en_blanco
from turnos.validar import validar_previa
from turnos.webapp import estado
from turnos.webapp.server import crear_app


@pytest.fixture
def web_vacia(tmp_path, monkeypatch):
    """Una web recién instalada: la carpeta datos/ no existe todavía."""
    monkeypatch.chdir(tmp_path)
    estado._estado.update({"ruta": "", "datos": None, "error_carga": None})
    return crear_app().test_client()


def test_en_blanco_tiene_turnos_y_reglas_pero_ni_monitores_ni_dependientes(tmp_path):
    ruta = crear_en_blanco(1, 2026, 9, 1, 10, raiz=str(tmp_path))
    datos = leer_datos_db(ruta)
    assert len(datos.dias) == 10 and len(datos.turnos) == 9 and len(datos.restricciones) >= 15
    assert not datos.monitores and not datos.dependientes
    assert any("monitor" in e for e in validar_previa(datos).errores)  # avisa de qué falta
    with pytest.raises(ValueError):
        crear_en_blanco(1, 2026, 9, 1, 10, raiz=str(tmp_path))  # ya existe
    with pytest.raises(ValueError):
        crear_en_blanco(1, 2026, 2, 1, 31, raiz=str(tmp_path))  # febrero no tiene 31 días


def test_primer_uso_sin_campamentos_no_da_error(web_vacia):
    info = web_vacia.get("/api/estado").get_json()
    assert info["cargado"] is False and not info["error"]
    assert web_vacia.get("/api/campamentos").get_json()["campamentos"] == []


def test_crear_en_blanco_desde_la_web_y_añadir_monitores(web_vacia):
    r = web_vacia.post("/api/campamentos/nuevo", json={"base": "blanco", "quincena": 1, "anio": 2026, "mes": 9, "dia_inicio": 1, "dia_fin": 7})
    assert r.status_code == 200
    info = r.get_json()
    assert info["cargado"] and info["n_monitores"] == 0 and len(info["dias"]) == 7
    # la rejilla se abre aunque aún no haya nadie
    assert web_vacia.get("/api/rejilla").status_code == 200
    # se añaden monitores desde la pestaña Monitores
    filas = [{"NOMBRE": n, "SEXO": s, "GRUPO": "NUEVO", "PERMITE_DESCANSO": 1, "PENALIZAR_DESCANSO": 0,
              "DEPENDIENTE_1": None, "DEPENDIENTE_2": None} for n, s in (("Ana Prueba", "F"), ("Luis Prueba", "M"))]
    assert web_vacia.post("/api/monitores", json={"filas": filas}).status_code == 200
    assert web_vacia.get("/api/estado").get_json()["n_monitores"] == 2
    # el campamento sin copia de nadie no pide tener otro abierto
    assert any(c["ruta"] == info["ruta"] for c in web_vacia.get("/api/campamentos").get_json()["campamentos"])


def test_copiar_sin_campamento_abierto_pide_crear_uno_en_blanco(web_vacia):
    r = web_vacia.post("/api/campamentos/nuevo", json={"quincena": 1, "anio": 2026, "mes": 9, "dia_inicio": 1, "dia_fin": 7})
    assert r.status_code == 400 and "en blanco" in r.get_json()["error"]


def test_demo_desde_la_pantalla_de_inicio(web_vacia, monkeypatch):
    monkeypatch.setattr("turnos.demo._generar_primeros_dias", lambda ruta, n: None)  # sin resolver nada: solo la creación
    r = web_vacia.post("/api/campamentos/demo")
    assert r.status_code == 200 and r.get_json()["cargado"] and r.get_json()["n_monitores"] >= 20
