"""El campamento de demostración se crea, es válido y no se puede confundir con datos reales."""
from turnos.almacen.cargar import leer_datos_db
from turnos.demo import crear_demo
from turnos.modelo.revision import Celda, revisar_asignaciones
from turnos.validar import validar_previa


def test_demo_vacia_es_valida(tmp_path):
    ruta = crear_demo(str(tmp_path / "demo" / "campamento.db"))
    datos = leer_datos_db(ruta)
    assert validar_previa(datos).ok
    assert len(datos.dias) == 13 and len(datos.monitores) >= 20 and datos.dependientes


def test_demo_con_dias_generados_no_incumple_reglas(tmp_path):
    ruta = crear_demo(str(tmp_path / "campamento.db"), generar=2)
    datos = leer_datos_db(ruta)
    assert datos.cfg.dia_reoptimizacion == 3  # los dos primeros días quedan como pasado
    from turnos.almacen.rejilla import asignaciones_trabajo_db  # noqa: F401  (comprueba que se puede leer)
    import sqlite3
    con = sqlite3.connect(ruta)
    filas = con.execute("SELECT tipo, clave, dia, monitor FROM asignaciones").fetchall()
    con.close()
    assert filas
    celdas = [Celda(f"{i}", t, c if t != "descanso" else "", d, m) for i, (t, c, d, m) in enumerate(filas)]
    avisos = [a for a in revisar_asignaciones(datos, celdas) if a.nivel == "regla"]
    assert avisos == []
