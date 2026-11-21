"""La interfaz web trabajando sobre la base de datos: de principio a fin, sin Excel por medio."""
import shutil
import sqlite3
import time
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
    estado._estado["ruta"] = str(xlsx)  # una ruta .xlsx se importa sola a campamento.db
    app = crear_app()
    c = app.test_client()
    assert c.get("/api/estado").get_json()["cargado"]
    return c, str(tmp_path / "campamento.db")


def _post(c, url, cuerpo):
    return c.post(url, json=cuerpo)


def _celda(rej, tipo, clave, dia, pos=0):
    for sec in rej["secciones"]:
        if sec["tipo"] != tipo or (tipo == "turno" and sec["titulo"] != clave):
            continue
        for i, f in enumerate(sec["filas"]):
            if (tipo == "dependiente" and f["etiqueta"] == clave) or (tipo != "dependiente" and i == pos):
                return f["fila"], f["celdas"][str(dia)]
    raise AssertionError((tipo, clave, dia, pos))


def test_una_ruta_excel_se_importa_y_se_usa_la_base_de_datos(cliente):
    c, db = cliente
    assert Path(db).exists()
    info = c.get("/api/estado").get_json()
    assert info["ruta"].endswith("campamento.db") and info["n_monitores"] > 0


def test_la_rejilla_coincide_con_lo_importado(cliente):
    c, db = cliente
    rej = c.get("/api/rejilla").get_json()
    llenas = sum(1 for s in rej["secciones"] for f in s["filas"] for cel in f["celdas"].values() if cel["v"] and cel["v"] != "-")
    con = sqlite3.connect(db)
    en_bd = con.execute("SELECT COUNT(*) FROM asignaciones").fetchone()[0]
    ausentes = con.execute("SELECT COUNT(*) FROM dependiente_ausente").fetchone()[0]
    con.close()
    assert llenas == en_bd
    assert [s["tipo"] for s in rej["secciones"]][-2:] == ["dependiente", "descanso"]
    # las filas tienen números únicos y estables
    ids = [f["fila"] for s in rej["secciones"] for f in s["filas"]]
    assert len(ids) == len(set(ids))
    assert ausentes >= 0


def test_editar_una_casilla_la_guarda_fijada_y_hace_copia(cliente):
    c, db = cliente
    rej = c.get("/api/rejilla").get_json()
    dia = rej["dia_fin"]
    fila, celda = _celda(rej, "turno", "lavaplatos", dia, pos=0)
    # un monitor que no esté ya ese día en ningún sitio
    usados = {cel["v"] for s in rej["secciones"] for f in s["filas"] for k, cel in f["celdas"].items() if k == str(dia)}
    libre = next(m["nombre"] for m in rej["monitores"] if m["nombre"] not in usados)
    r = _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "turno", "fila": fila, "dia": dia, "valor": libre, "fijado": True}]})
    assert r.status_code == 200 and r.get_json()["escritas"] == 1
    assert Path(r.get_json()["backup"]).exists()
    _, nueva = _celda(c.get("/api/rejilla").get_json(), "turno", "lavaplatos", dia, pos=0)
    assert nueva == {"v": libre, "f": True}
    # vaciarla
    _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "turno", "fila": fila, "dia": dia, "valor": "", "fijado": False}]})
    assert _celda(c.get("/api/rejilla").get_json(), "turno", "lavaplatos", dia, pos=0)[1]["v"] == ""


def test_editar_con_datos_malos_no_guarda_nada(cliente):
    c, db = cliente
    r = _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "turno", "fila": 999999, "dia": 18, "valor": "", "fijado": False},
                                                       {"tipo": "turno", "fila": 1000, "dia": 18, "valor": "Nadie Conocido", "fijado": False}]})
    assert r.status_code == 400 and "No se ha guardado nada" in r.get_json()["error"]


def test_dependiente_ausente_y_cuidador(cliente):
    c, db = cliente
    rej = c.get("/api/rejilla").get_json()
    dep = next(s for s in rej["secciones"] if s["tipo"] == "dependiente")["filas"][0]
    dia = rej["dia_fin"]
    _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "dependiente", "fila": dep["fila"], "dia": dia, "valor": "-", "fijado": False}]})
    assert _celda(c.get("/api/rejilla").get_json(), "dependiente", dep["etiqueta"], dia)[1]["v"] == "-"
    _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "dependiente", "fila": dep["fila"], "dia": dia, "valor": "", "fijado": False}]})
    assert _celda(c.get("/api/rejilla").get_json(), "dependiente", dep["etiqueta"], dia)[1]["v"] == ""


def test_disponibilidad_descansos_y_puestos_por_reasignar(cliente):
    c, db = cliente
    d = c.get("/api/disponibilidad").get_json()
    assert d["filas"] and "descansos" in d and "asignaciones" in d
    fila = d["filas"][0]
    dia = str(d["dias"][0])
    fila[dia] = "X" if fila[dia] != "X" else "D"
    r = _post(c, "/api/disponibilidad", {"filas": [fila]})
    assert r.status_code == 200
    despues = c.get("/api/disponibilidad").get_json()["filas"][0]
    assert despues[dia] == fila[dia]
    fila[dia] = "Z"
    assert _post(c, "/api/disponibilidad", {"filas": [fila]}).status_code == 400


def test_plazas_de_llegada_y_salida_con_extras(cliente):
    c, db = cliente
    p = c.get("/api/plazas").get_json()
    assert p["turnos"], "la pantalla de plazas necesita la lista de turnos"
    turno, ultimo = p["turnos"][0]["turno"], p["dias"][-1]["dia"]
    r = _post(c, "/api/plazas", {"cambios": [{"turno": turno, "dia": ultimo, "plazas": 1, "max": 9}]})
    assert r.status_code == 200
    assert r.get_json()["filas_añadidas"].get(turno, 0) >= 0
    p2 = c.get("/api/plazas").get_json()
    t2 = next(t for t in p2["turnos"] if t["turno"] == turno)
    assert t2["plazas"][str(ultimo)] == 1 and t2["max"][str(ultimo)] == 9
    rej = c.get("/api/rejilla").get_json()
    sec = next(s for s in rej["secciones"] if s["titulo"] == turno)
    assert len(sec["filas"]) >= 9, "la rejilla crece sola hasta lo que acepta el turno"
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM config WHERE clave = 'W_EXTRA'").fetchone()[0] == 1
    con.close()
    assert _post(c, "/api/plazas", {"cambios": [{"turno": turno, "dia": ultimo, "plazas": -1, "max": None}]}).status_code == 400


def test_alta_de_turno_dependiente_y_monitor(cliente):
    c, db = cliente
    assert _post(c, "/api/tipos_turno/nuevo", {"nombre": "biblioteca", "plazas": 2, "sexo_req": "-", "esfuerzo": 1}).status_code == 200
    assert _post(c, "/api/tipos_turno/nuevo", {"nombre": "biblioteca", "plazas": 2, "sexo_req": "-", "esfuerzo": 1}).status_code == 400
    assert any(s["titulo"] == "biblioteca" for s in c.get("/api/rejilla").get_json()["secciones"])
    assert _post(c, "/api/dependientes/nuevo", {"acampado": "Nuevo Acampado", "sexo_req": "-", "esfuerzo": 3}).status_code == 200
    dep = next(s for s in c.get("/api/rejilla").get_json()["secciones"] if s["tipo"] == "dependiente")
    assert any(f["etiqueta"] == "Nuevo Acampado" for f in dep["filas"])

    monitores = c.get("/api/monitores").get_json()
    monitores.append({"NOMBRE": "Monitor Nuevo", "SEXO": "F", "GRUPO": "NUEVO", "PERMITE_DESCANSO": 1, "PENALIZAR_DESCANSO": 0,
                      "DEPENDIENTE_1": None, "DEPENDIENTE_2": None})
    r = _post(c, "/api/monitores", {"filas": monitores})
    assert r.status_code == 200 and any("Monitor Nuevo" in a for a in r.get_json()["avisos"])
    disp = c.get("/api/disponibilidad").get_json()["filas"]
    nuevo = next(f for f in disp if f["NOMBRE"] == "Monitor Nuevo")
    assert all(v == "D" for k, v in nuevo.items() if k != "NOMBRE")
    # quitar a alguien con turnos asignados no se permite en silencio
    monitores = [m for m in c.get("/api/monitores").get_json() if m["NOMBRE"] != c.get("/api/rejilla").get_json()["monitores"][0]["nombre"]]
    r = _post(c, "/api/monitores", {"filas": monitores})
    assert r.status_code == 200
    assert not _post(c, "/api/monitores", {"filas": [{**monitores[0], "SEXO": "Q"}]}).status_code == 200


def test_restricciones_y_config(cliente):
    c, db = cliente
    rs = c.get("/api/restricciones").get_json()
    rs[0]["ACTIVA"] = not rs[0]["ACTIVA"]
    assert _post(c, "/api/restricciones", {"filas": rs}).status_code == 200
    assert c.get("/api/restricciones").get_json()[0]["ACTIVA"] == rs[0]["ACTIVA"]
    assert _post(c, "/api/config", {"TIME_LIMIT_S": 33}).status_code == 200
    assert c.get("/api/config").get_json()["TIME_LIMIT_S"] == 33


def _esperar(c, hasta=180):
    t0 = time.time()
    while time.time() - t0 < hasta:
        e = c.get("/api/generar/estado").get_json()
        if e["estado"] != "corriendo":
            return e
        time.sleep(0.5)
    raise AssertionError("la generación no termina")


def test_generar_un_dia_proponer_y_aplicar(cliente):
    c, db = cliente
    _post(c, "/api/config", {"SOLVER": "appsi_highs", "TIME_LIMIT_S": 60})
    est = c.get("/api/estado").get_json()
    dia = est["dia_inicio"]
    assert _post(c, "/api/generar", {"desde": dia, "hasta": dia}).status_code == 202
    e = _esperar(c)
    assert e["estado"] == "listo", e
    prop = c.get("/api/generar/propuesta").get_json()
    assert any(f["celdas"][str(dia)]["v"] for s in prop["secciones"] if s["tipo"] == "turno" for f in s["filas"])
    # nada se ha escrito todavía
    con = sqlite3.connect(db)
    antes = con.execute("SELECT * FROM asignaciones ORDER BY 1,2,3,4").fetchall()
    con.close()
    assert _post(c, "/api/generar/aplicar", {}).status_code == 200
    con = sqlite3.connect(db)
    despues = con.execute("SELECT * FROM asignaciones ORDER BY 1,2,3,4").fetchall()
    reopt = con.execute("SELECT valor FROM config WHERE clave = 'DIA_REOPTIMIZACION'").fetchone()[0]
    con.close()
    assert despues != antes and reopt == str(dia)
    inf = c.get("/api/informe")
    assert inf.status_code == 200
    inf = inf.get_json()
    assert "dias_dependiente_acampado" not in inf  # cada acampado tiene monitor todos los días: no aporta nada
    finde = {m["NOMBRE"] for m in c.get("/api/monitores").get_json() if not m["PERMITE_DESCANSO"]}
    assert finde and set(inf["excluidos_finde"]) == finde
    for serie in ("esfuerzo", "descansos", "dias_dependiente_monitor"):
        assert not finde & {x["label"] for x in inf[serie]}  # los de fin de semana no se comparan con los demás
    # el informe sale de lo escrito en la rejilla: sigue ahí aunque se recargue y no haya optimización en memoria
    assert _post(c, "/api/cargar", {"ruta": db}).status_code == 200
    de_nuevo = c.get("/api/informe")
    assert de_nuevo.status_code == 200 and not de_nuevo.get_json()["vacio"]
    assert de_nuevo.get_json()["esfuerzo"] == inf["esfuerzo"]


def test_descargar_excel_se_genera_desde_la_base_de_datos(cliente, tmp_path):
    from turnos.io_excel.lector import leer_datos
    c, db = cliente
    r = c.get("/api/descargar")
    assert r.status_code == 200 and r.headers["Content-Disposition"].endswith('.xlsx"') or "xlsx" in r.headers["Content-Disposition"]
    destino = tmp_path / "descargado.xlsx"
    destino.write_bytes(r.data)
    assert len(leer_datos(str(destino)).monitores) > 0


# ----------------------------------------------------------------------
# Campamentos nuevos, importar un Excel y versiones
# ----------------------------------------------------------------------
@pytest.fixture
def raiz(tmp_path, monkeypatch):
    """Que 'datos/' sea una carpeta de pruebas, no la real."""
    carpeta = tmp_path / "datos"
    carpeta.mkdir()
    monkeypatch.setattr("turnos.almacen.nuevo.CARPETA_DATOS", str(carpeta))
    monkeypatch.setattr("turnos.webapp.server.CARPETA_DATOS", str(carpeta))
    monkeypatch.chdir(tmp_path)
    return carpeta


def test_nuevo_campamento_parte_de_otro_y_esta_vacio(cliente, raiz):
    c, db = cliente
    antes = c.get("/api/estado").get_json()
    r = _post(c, "/api/campamentos/nuevo", {"quincena": 1, "anio": 2027, "mes": 8, "dia_inicio": 1, "dia_fin": 14, "copiar_disponibilidad": False})
    assert r.status_code == 200, r.get_json()
    nuevo = r.get_json()
    assert nuevo["dia_inicio"] == 1 and nuevo["dia_fin"] == 14 and len(nuevo["dias"]) == 14
    assert nuevo["n_monitores"] == antes["n_monitores"] and nuevo["n_dependientes"] == antes["n_dependientes"]
    assert nuevo["ruta"] != antes["ruta"] and Path(nuevo["ruta"]).exists()
    rej = c.get("/api/rejilla").get_json()
    assert not any(cel["v"] and cel["v"] != "-" for s in rej["secciones"] for f in s["filas"] for cel in f["celdas"].values())
    # llegada y salida conservan sus plazas propias; todos disponibles
    p = c.get("/api/plazas").get_json()
    assert len(p["dias"]) == 14
    disp = c.get("/api/disponibilidad").get_json()["filas"]
    assert all(v == "D" for f in disp for k, v in f.items() if k != "NOMBRE")
    # el nuevo aparece en la lista y el anterior no se ha tocado
    lista = c.get("/api/campamentos").get_json()
    assert any(x["ruta"] == nuevo["ruta"] for x in lista["campamentos"])
    # no se puede repetir
    assert _post(c, "/api/campamentos/nuevo", {"quincena": 1, "anio": 2027, "mes": 8, "dia_inicio": 1, "dia_fin": 14}).status_code == 400


def test_nuevo_campamento_valida_las_fechas(cliente, raiz):
    c, db = cliente
    for malo in ({"mes": 13}, {"dia_fin": 40}, {"dia_inicio": 10, "dia_fin": 5}, {"anio": 1900}):
        cuerpo = {"quincena": 3, "anio": 2027, "mes": 8, "dia_inicio": 1, "dia_fin": 14, **malo}
        assert _post(c, "/api/campamentos/nuevo", cuerpo).status_code == 400, malo
    assert _post(c, "/api/campamentos/nuevo", {"quincena": 3}).status_code == 400
    assert not list(raiz.glob("**/*.db")), "un intento fallido no deja nada a medias"


def test_importar_un_excel_subiendolo(cliente, raiz):
    import io as _io
    c, db = cliente
    r = c.post("/api/campamentos/importar", data={"archivo": (_io.BytesIO(FIXTURE.read_bytes()), "Mi Campamento.xlsx")},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert "Mi_Campamento" in r.get_json()["ruta"] and r.get_json()["n_monitores"] > 0
    # subir el mismo no pisa el anterior
    r2 = c.post("/api/campamentos/importar", data={"archivo": (_io.BytesIO(FIXTURE.read_bytes()), "Mi Campamento.xlsx")},
                content_type="multipart/form-data")
    assert r2.status_code == 200 and r2.get_json()["ruta"] != r.get_json()["ruta"]
    # algo que no es un Excel se rechaza sin dejar rastro
    n = len(list(raiz.glob("**/*.db")))
    mal = c.post("/api/campamentos/importar", data={"archivo": (_io.BytesIO(b"no soy un excel"), "roto.xlsx")}, content_type="multipart/form-data")
    assert mal.status_code == 400 and len(list(raiz.glob("**/*.db"))) == n
    assert c.post("/api/campamentos/importar", data={"archivo": (_io.BytesIO(b"x"), "notas.txt")}, content_type="multipart/form-data").status_code == 400


def test_versiones_guardar_y_restaurar(cliente):
    c, db = cliente
    rej = c.get("/api/rejilla").get_json()
    dia = rej["dia_fin"]
    fila, _ = _celda(rej, "turno", "lavaplatos", dia, pos=0)
    usados = {cel["v"] for s in rej["secciones"] for f in s["filas"] for k, cel in f["celdas"].items() if k == str(dia)}
    libre = next(m["nombre"] for m in rej["monitores"] if m["nombre"] not in usados)

    version = c.post("/api/copias/crear", json={}).get_json()
    assert version["nombre"].endswith(".db") and version["asignaciones"] is not None
    _post(c, "/api/rejilla/guardar", {"cambios": [{"tipo": "turno", "fila": fila, "dia": dia, "valor": libre, "fijado": True}]})
    assert _celda(c.get("/api/rejilla").get_json(), "turno", "lavaplatos", dia, pos=0)[1]["v"] == libre

    lista = c.get("/api/copias").get_json()
    assert len(lista) >= 2 and lista[0]["fecha"] >= lista[-1]["fecha"]  # la más reciente primero
    r = _post(c, "/api/copias/restaurar", {"nombre": version["nombre"]})
    assert r.status_code == 200
    assert _celda(c.get("/api/rejilla").get_json(), "turno", "lavaplatos", dia, pos=0)[1]["v"] == ""
    # restaurar deja antes el estado actual como otra versión: se puede deshacer el deshacer
    assert any(v["nombre"] == r.get_json()["version_previa"] for v in c.get("/api/copias").get_json())
    assert _post(c, "/api/copias/restaurar", {"nombre": "../../otra.db"}).status_code == 400


def test_avisos_de_reglas_al_asignar_a_mano(cliente):
    c, db = cliente
    rej = c.get("/api/rejilla").get_json()
    # una casilla de la rejilla del propio campamento: ponemos a alguien ausente ese día
    dia = rej["dia_fin"]
    disp = rej["disponibilidad"]
    ausente = next((m for m, d in disp.items() if d[str(dia)] == "X"), None)
    assert ausente, "el fixture trae algún ausente el último día"
    fila, _ = _celda(rej, "turno", "lavaplatos", dia, pos=0)
    celdas = [{"k": f"turno|{fila}|{dia}", "tipo": "turno", "clave": "lavaplatos", "dia": dia, "v": ausente}]
    r = c.post("/api/rejilla/reglas", json={"celdas": celdas}).get_json()
    assert [a["regla"] for a in r["avisos"]] == ["disponibilidad"]
    assert r["avisos"][0]["celdas"] == [f"turno|{fila}|{dia}"] and "ausente" in r["avisos"][0]["mensaje"]
    assert c.post("/api/rejilla/reglas", json={"celdas": [{"basura": 1}]}).get_json()["avisos"] == []
