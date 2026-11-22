"""Cada monitor descansa entre el 30 % y el 50 % de los días que está disponible."""
import sqlite3

from turnos.almacen.cargar import leer_datos_db
from turnos.almacen.plantilla import completar_campamento
from turnos.demo import crear_demo
from turnos.modelo.construir import construir_modelo
from turnos.modelo.derivados import limites_descanso
from turnos.resolver import resolver_modelo


def test_limites_se_redondean_hacia_dentro():
    assert limites_descanso(10, 30, 50) == (3, 5)   # 30 % de 10 = 3 (no 4 por redondeo de coma flotante)
    assert limites_descanso(13, 30, 50) == (4, 6)
    assert limites_descanso(4, 30, 50) == (2, 2)
    lo, hi = limites_descanso(1, 30, 50)            # con 1 día no cabe ningún entero: no se aplica
    assert lo > hi


def test_el_optimizador_respeta_el_margen(tmp_path):
    ruta = str(tmp_path / "campamento.db")
    crear_demo(ruta)
    datos = leer_datos_db(ruta)
    sol = resolver_modelo(construir_modelo(datos), datos)
    assert sol.estado == "optimo" or sol.estado.startswith("factible"), sol.estado
    n = 0
    for mo, mon in datos.monitores.items():
        if not mon.permite_descanso:
            continue
        lo, hi = limites_descanso(datos.dias_presente[mo], 30, 50)
        if lo > hi:
            continue
        desc = sum(1 for (m2, d), v in sol.r.items() if m2 == mo and v == 1)
        assert lo <= desc <= hi, f"{mo}: {desc} descansos de {datos.dias_presente[mo]} días (margen {lo}-{hi})"
        n += 1
    assert n >= 20


def test_un_campamento_antiguo_recibe_la_regla_y_los_parametros(tmp_path):
    ruta = str(tmp_path / "campamento.db")
    crear_demo(ruta)
    con = sqlite3.connect(ruta)
    con.execute("DELETE FROM restricciones WHERE nombre = 'descanso_porcentaje'")
    con.execute("DELETE FROM config WHERE clave LIKE 'DESCANSO_%' OR clave = 'W_DESCANSO_PCT'")
    con.commit()
    con.close()
    completar_campamento(ruta)
    completar_campamento(ruta)  # idempotente
    con = sqlite3.connect(ruta)
    assert con.execute("SELECT COUNT(*) FROM restricciones WHERE nombre = 'descanso_porcentaje' AND activa = 1").fetchone()[0] == 1
    assert con.execute("SELECT valor FROM config WHERE clave = 'DESCANSO_MAX_PCT'").fetchone()[0] == "50"
    con.close()
    assert leer_datos_db(ruta).restriccion_activa("descanso_porcentaje")
