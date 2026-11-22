"""Función objetivo: suma ponderada de las penalizaciones registradas.

    min   W_FALTA        · Σ falta[t,d]
        + W_EQUIDAD      · (cmax - cmin)
        + 0.2·W_EQUIDAD  · Σ_m |carga_norm[m] - referencia|   (que nadie quede lejos del resto)
        + W_DESCANSO_LIM · Σ_{m: PENALIZAR_DESCANSO=1, d} r[m,d]
        + W_VARIEDAD     · Σ z[m,p]
        + W_REPETICION   · Σ rep[m,t,d]
        + W_FALTA_DESC   · Σ falta_desc[m,v]
        + W_FALTA        · Σ r[m,d] forzados del grupo FINDE (caso degradado)
        + W_EXTRA        · Σ extra[t,d]   (gente por encima de las plazas, ver PLAZAS_MAX_POR_DIA)

Cada restricción "blanda" (y `cobertura`, que aunque es dura genera holgura
penalizada) registra su expresión sin ponderar en `m._penalizaciones` con
`restricciones.base.registrar_penalizacion`. Este módulo solo sabe qué peso
de CONFIG le corresponde a cada nombre y las suma. Si una restricción no
está activa, su expresión nunca se registró y simplemente no aparece en la
suma: no hay que tocar este fichero para activar/desactivar penalizaciones,
solo la hoja RESTRICCIONES.
"""
from pyomo.environ import Objective, minimize

# Peso de la suma de desviaciones respecto a W_EQUIDAD. Con el peso entero el solver tarda mucho más
# y, con el límite de tiempo de un campamento real, a veces deja turnos sin cubrir; con 0.2 reparte
# mejor que con solo cmax-cmin y sigue cubriéndolo todo. Solo se usa si `descanso_porcentaje` está apagada.
FACTOR_DESVIACION = 0.2

# nombre de la restricción (o penalización interna) -> atributo de Config con su peso
PESO_POR_PENALIZACION = {
    "cobertura": "w_falta",
    "plazas_extra": "w_extra",
    "finde_sin_descanso_forzado": "w_falta",
    "penalizar_descanso_limitado": "w_descanso_lim",
    "variedad_dependiente": "w_variedad",
    "no_repetir_turno": "w_repeticion",
    "descanso_minimo": "w_falta_desc",
    "descanso_porcentaje": "w_descanso_pct",
}


def construir_objetivo(m, datos, cfg):
    penalizaciones = getattr(m, "_penalizaciones", {})

    expr = 0
    for nombre, expresion in penalizaciones.items():
        if nombre == "equidad_esfuerzo":
            continue  # se trata aparte, no es una suma de holguras
        peso_attr = PESO_POR_PENALIZACION.get(nombre)
        if peso_attr is None:
            continue
        peso = getattr(cfg, peso_attr)
        expr = expr + peso * expresion

    if hasattr(m, "cmax") and hasattr(m, "cmin"):
        expr = expr + cfg.w_equidad * (m.cmax - m.cmin)
    if hasattr(m, "dev_equidad"):
        expr = expr + FACTOR_DESVIACION * cfg.w_equidad * sum(m.dev_equidad[mo] for mo in m.equi_monitores)

    m.objetivo = Objective(expr=expr, sense=minimize)
    return m.objetivo
