"""Valores de partida de un campamento nuevo: configuración, turnos habituales y reglas.

Los usan `nuevo.crear_en_blanco` (campamento vacío creado desde la web) y `demo` (campamento de ejemplo).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

CONFIG_BASE: List[Tuple[str, str, str]] = [
    ("SOLVER", "appsi_highs", "Solver de Pyomo (appsi_highs es gratuito; gurobi necesita licencia)"),
    ("TIME_LIMIT_S", "120", "Límite de tiempo del solver, en segundos"),
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


def pares_config(quincena: int, anio: int, mes: int, dia_inicio: int, dia_fin: int, **cambios: str) -> List[Tuple[str, str, str]]:
    """Filas de la tabla `config` de un campamento con esas fechas (`cambios` sobrescribe valores de CONFIG_BASE)."""
    cabecera = [
        ("QUINCENA", str(quincena), "Identificador de la quincena"),
        ("AÑO", str(anio), "Año del campamento"),
        ("MES", str(mes), "Mes (8=agosto). Necesario para saber qué días son fin de semana"),
        ("DIA_INICIO", str(dia_inicio), "Primer día del horizonte"),
        ("DIA_FIN", str(dia_fin), "Último día del horizonte"),
        ("DIA_REOPTIMIZACION", str(dia_inicio), "Los días anteriores a este son datos fijos e inmutables"),
    ]
    return cabecera + [(k, str(cambios.get(k, v)), d) for k, v, d in CONFIG_BASE]


# (turno, plazas por día, sexo requerido, nota)
TURNOS_HABITUALES = [
    ("lavaplatos", 3, "-", ""),
    ("limpieza", 5, "-", ""),
    ("cocina", 3, "-", ""),
    ("comedor", 4, "-", ""),
    ("paseo_piscina_siesta", 4, "-", ""),
    ("vigilancia_chicos", 2, "M", "Nocturno. Al día siguiente no puede ir a comedor."),
    ("vigilancia_chicas", 2, "F", "Nocturno. Al día siguiente no puede ir a comedor."),
    ("vigilancia_D_chicos", 1, "M", "Vigilancia de dependientes. Nocturno."),
    ("vigilancia_D_chicas", 1, "F", "Vigilancia de dependientes. Nocturno."),
]

D, B = "DURA", "BLANDA"
RESTRICCIONES: List[Tuple[str, str, str]] = [
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
