"""Campamento de demostración con datos inventados.

    python -m turnos.demo                # crea datos/demo/campamento.db (si no existe) y abre la web
    python -m turnos.demo --generar 0    # con la rejilla vacía
    python -m turnos.demo --solo-crear   # sin abrir la web

Todos los nombres son inventados: sirve para enseñar la herramienta o para
probarla sin tener datos reales. Funciona sin conexión a internet.
"""
from __future__ import annotations

import argparse
import calendar
from pathlib import Path
from typing import Dict, List, Optional

from .almacen.esquema import abrir

RUTA_DEMO = "datos/demo/campamento.db"
ANIO, MES, DIA_INICIO, DIA_FIN = 2026, 8, 1, 13

CHICOS = ["Mateo Ruiz", "Hugo Navarro", "Iván Delgado", "Pablo Ortega", "Diego Santos", "Marcos Vidal",
          "Adrián Prieto", "Rubén Cabrera", "Óscar Molina", "Nicolás Reyes", "Samuel Campos", "Tomás Beltrán", "Gael Arroyo", "Bruno Salas"]
CHICAS = ["Lucía Marín", "Carla Soler", "Irene Fuentes", "Marta Blanco", "Julia Herrero", "Alba Peña",
          "Sara Cortés", "Noa Gallego", "Elena Ibáñez", "Paula Vega", "Claudia Rubio", "Inés Lozano", "Vera Ochoa", "Lola Aguilar"]
FINDE = [("Álex Montero", "M"), ("Rocío Padilla", "F")]  # solo vienen los fines de semana
NUEVOS = {"Samuel Campos", "Tomás Beltrán", "Inés Lozano", "Claudia Rubio"}
LIMITADOS = {"Óscar Molina", "Noa Gallego"}  # vienen pocos días: mejor no darles descanso

# (turno, plazas, sexo requerido, nota)
TURNOS = [
    ("lavaplatos", 2, "-", ""),
    ("limpieza", 2, "-", ""),
    ("cocina", 2, "-", ""),
    ("comedor", 3, "-", ""),
    ("paseo_piscina_siesta", 2, "-", ""),
    ("vigilancia_chicos", 1, "M", "Nocturno. Al día siguiente no puede ir a comedor."),
    ("vigilancia_chicas", 1, "F", "Nocturno. Al día siguiente no puede ir a comedor."),
    ("vigilancia_D_chicos", 1, "M", "Vigilancia de dependientes. Nocturno."),
    ("vigilancia_D_chicas", 1, "F", "Vigilancia de dependientes. Nocturno."),
]

# (acampado, sexo del monitor que necesita, esfuerzo)
DEPENDIENTES = [("Dani", "M", 4.0), ("Leo", "M", 3.0), ("Sofi", "F", 4.0), ("Nerea", "F", 3.0)]

CONFIG = [
    ("QUINCENA", "1", "Identificador de la quincena"),
    ("AÑO", str(ANIO), "Año del campamento"),
    ("MES", str(MES), "Mes (8=agosto). Necesario para saber qué días son fin de semana"),
    ("DIA_INICIO", str(DIA_INICIO), "Primer día del horizonte"),
    ("DIA_FIN", str(DIA_FIN), "Último día del horizonte"),
    ("DIA_REOPTIMIZACION", str(DIA_INICIO), "Los días anteriores a este son datos fijos e inmutables"),
    ("SOLVER", "appsi_highs", "Solver de Pyomo"),
    ("TIME_LIMIT_S", "60", "Límite de tiempo del solver, en segundos"),
    ("MIP_GAP", "0.01", "Gap relativo de parada (0.01 = 1%)"),
    ("DIAS_DESCANSO_MINIMO", "1", "Descansos deseados por cada DIAS_VENTANA_DESCANSO días"),
    ("DIAS_VENTANA_DESCANSO", "6", "Tamaño de la ventana para el descanso mínimo"),
    ("W_FALTA", "10000", "Peso: dejar un turno sin cubrir. Muy alto a propósito"),
    ("W_EQUIDAD", "100", "Peso: diferencia de esfuerzo entre el monitor más y el menos cargado"),
    ("W_DESCANSO_LIM", "30", "Peso: dar descanso a alguien de disponibilidad limitada"),
    ("W_VARIEDAD", "20", "Peso: cada pareja monitor-dependiente distinta"),
    ("W_REPETICION", "5", "Peso: repetir el mismo turno dos días seguidos"),
    ("W_FALTA_DESC", "50", "Peso: incumplir el descanso mínimo"),
]

D, B = "DURA", "BLANDA"
RESTRICCIONES = [
    ("cobertura", D, "Cada turno se cubre con sus plazas (con holgura penalizada)"),
    ("un_turno_por_dia", D, "Un monitor hace como mucho una cosa al día: turno, dependiente o descanso"),
    ("disponibilidad", D, "Nadie recibe nada un día en que está ausente (X)"),
    ("descanso_forzado", D, "Las celdas R de DISPONIBILIDAD son descanso obligatorio"),
    ("sexo_turno", D, "Vigilancia de chicos solo chicos; de chicas solo chicas"),
    ("sexo_dependiente", D, "El monitor de un dependiente es de su mismo sexo, salvo AMBOS_SEXOS=1"),
    ("finde_sin_descanso", D, "PERMITE_DESCANSO=0 -> ese monitor nunca recibe descanso"),
    ("vigilancia_no_comedor", D, "Quien vigila de noche no va a comedor al día siguiente (las 4 vigilancias)"),
    ("cobertura_dependiente", D, "Cada dependiente presente tiene exactamente un monitor"),
    ("asignacion_dep_fijada", D, "Se respeta lo escrito en ASIG_DEPENDIENTE"),
    ("max_2_dependientes", D, "Un monitor lleva como mucho 2 acampados distintos"),
    ("max_3_dias_por_dep", D, "Como mucho 3 días con el mismo acampado"),
    ("bloques_no_intercalados", D, "Si lleva 2 acampados, primero uno y después el otro"),
    ("dep_2_dias_tercero_descansa", D, "Dos días seguidos de dependiente -> el tercero es descanso"),
    ("historico_inmutable", D, "Los días < DIA_REOPTIMIZACION quedan fijados"),
    ("equidad_esfuerzo", B, "Minimiza la diferencia de esfuerzo normalizado entre monitores"),
    ("penalizar_descanso_limitado", B, "Evita dar descanso a quien está pocos días"),
    ("variedad_dependiente", B, "Minimiza el número de parejas monitor-acampado"),
    ("no_repetir_turno", B, "Evita el mismo turno dos días seguidos"),
    ("descanso_minimo", B, "Al menos DIAS_DESCANSO_MINIMO por ventana"),
]


def _dias_finde() -> List[int]:
    return [d for d in range(DIA_INICIO, DIA_FIN + 1) if calendar.weekday(ANIO, MES, d) >= 5]


def _disponibilidad(monitores: List[tuple]) -> Dict[tuple, str]:
    """D (viene), X (no viene), R (descanso impuesto). Una disponibilidad realista y reproducible."""
    dias = list(range(DIA_INICIO, DIA_FIN + 1))
    finde = set(_dias_finde())
    disp = {(m[1], d): "D" for m in monitores for d in dias}
    for nombre, _sexo in FINDE:
        for d in dias:
            disp[(nombre, d)] = "D" if d in finde else "X"
    llegan_tarde = {"Diego Santos": 3, "Alba Peña": 2, "Samuel Campos": 4, "Elena Ibáñez": 3}
    se_van_antes = {"Rubén Cabrera": 10, "Julia Herrero": 11, "Tomás Beltrán": 9, "Paula Vega": 12}
    for nombre, primero in llegan_tarde.items():
        for d in dias:
            if d < primero:
                disp[(nombre, d)] = "X"
    for nombre, ultimo in se_van_antes.items():
        for d in dias:
            if d > ultimo:
                disp[(nombre, d)] = "X"
    for nombre in LIMITADOS:  # vienen solo unos días
        for d in dias:
            disp[(nombre, d)] = "D" if 6 <= d <= 11 else "X"
    for nombre, d in {"Marta Blanco": 7, "Hugo Navarro": 5, "Carla Soler": 10, "Mateo Ruiz": 8}.items():
        disp[(nombre, d)] = "X"  # un día suelto fuera
    for nombre, d in {"Irene Fuentes": 6, "Adrián Prieto": 9}.items():
        disp[(nombre, d)] = "R"  # descanso pedido
    return disp


def crear_demo(ruta: str = RUTA_DEMO, generar: int = 0) -> str:
    """Crea el campamento de demostración (vacío) y, si `generar` > 0, genera esos primeros días."""
    if Path(ruta).exists():
        raise FileExistsError(f"Ya existe '{ruta}'")
    todos = [(n, "M") for n in CHICOS] + [(n, "F") for n in CHICAS] + FINDE
    monitores = [(i, n, s) for i, (n, s) in enumerate(todos)]
    disp = _disponibilidad(monitores)
    dias = list(range(DIA_INICIO, DIA_FIN + 1))
    finde_nombres = {n for n, _ in FINDE}

    con = abrir(ruta, crear=True)
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES ('origen', 'demo')")
            con.executemany("INSERT INTO config (clave, valor, descripcion) VALUES (?, ?, ?)", CONFIG)
            for i, nombre, sexo in monitores:
                grupo = "FINDE" if nombre in finde_nombres else ("NUEVO" if nombre in NUEVOS else "ANTIGUO")
                con.execute(
                    "INSERT INTO monitores (orden, nombre, sexo, grupo, permite_descanso, penalizar_descanso) VALUES (?, ?, ?, ?, ?, ?)",
                    (i, nombre, sexo, grupo, 0 if grupo == "FINDE" else 1, 1 if nombre in LIMITADOS else 0))
            con.executemany("INSERT INTO disponibilidad (monitor, dia, codigo) VALUES (?, ?, ?)",
                            [(m, d, c) for (m, d), c in disp.items()])
            for i, (turno, plazas, sexo, nota) in enumerate(TURNOS):
                con.execute("INSERT INTO tipos_turno (orden, turno, plazas, sexo_req, esfuerzo, notas) VALUES (?, ?, ?, ?, ?, ?)",
                            (i, turno, plazas, sexo, 2.0, nota))
                con.executemany("INSERT INTO plazas_dia (turno, dia, plazas, maximo) VALUES (?, ?, ?, NULL)",
                                [(turno, d, plazas) for d in dias])
            for i, (acampado, sexo, esfuerzo) in enumerate(DEPENDIENTES):
                con.execute("INSERT INTO dependientes (orden, acampado, sexo_monitor_req, esfuerzo, notas) VALUES (?, ?, ?, ?, '')",
                            (i, acampado, sexo, esfuerzo))
            for i, (nombre, tipo, desc) in enumerate(RESTRICCIONES):
                con.execute("INSERT INTO restricciones (orden, nombre, activa, tipo, descripcion) VALUES (?, ?, 1, ?, ?)",
                            (i, nombre, tipo, desc))
    finally:
        con.close()

    if generar > 0:
        _generar_primeros_dias(ruta, generar)
    return ruta


def _generar_primeros_dias(ruta: str, n: int) -> None:
    from .almacen.cargar import leer_datos_db
    from .almacen.guardar import escribir_solucion_db
    from .almacen.edicion import guardar_config_valores
    from .modelo.construir import construir_modelo
    from .resolver import resolver_modelo

    datos = leer_datos_db(ruta, hasta=DIA_INICIO + n - 1)
    solucion = resolver_modelo(construir_modelo(datos), datos)
    escribir_solucion_db(ruta, datos, solucion)
    guardar_config_valores(ruta, {"DIA_REOPTIMIZACION": DIA_INICIO + n})  # lo generado pasa a ser el pasado


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(prog="python -m turnos.demo", description=__doc__.split("\n")[0])
    p.add_argument("--ruta", default=RUTA_DEMO, help=f"Dónde crear la base de datos (por defecto {RUTA_DEMO})")
    p.add_argument("--generar", type=int, default=5, metavar="N", help="Días con turnos ya generados al crearla (por defecto 5; 0 = rejilla vacía)")
    p.add_argument("--solo-crear", action="store_true", help="Crea el campamento pero no abre la web")
    p.add_argument("--rehacer", action="store_true", help="Borra la demo anterior y la vuelve a crear")
    args = p.parse_args(argv)

    ruta = Path(args.ruta)
    if args.rehacer and ruta.exists():
        ruta.unlink()
    if ruta.exists():
        print(f"Usando la demo que ya existe: {ruta}")
    else:
        crear_demo(str(ruta), generar=args.generar)
        print(f"Campamento de demostración creado: {ruta}")
    if args.solo_crear:
        return
    from .webapp.server import main as abrir_web
    abrir_web([ruta.as_posix()])


if __name__ == "__main__":
    main()
