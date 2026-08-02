"""Construye el modelo con datos sintéticos, sin tocar el Excel.

Comprueba la "regla de oro" del README: `modelo.construir` solo necesita un
objeto `Datos`. Sirve también para fijar en un test rápido las reglas de
generación de índices de §4.2 de las instrucciones (un índice inexistente
en vez de una variable fijada a 0).
"""
from turnos.modelo.construir import construir_modelo
from turnos.modelo.datos import (
    Config,
    Datos,
    Dependiente,
    Monitor,
    RestriccionInfo,
    TipoTurno,
)


def _datos_sinteticos() -> Datos:
    cfg = Config(
        quincena=1, anio=2026, mes=7,
        dia_inicio=1, dia_fin=3, dia_reoptimizacion=1,
        solver="appsi_highs", time_limit_s=10, mip_gap=0.01,
        dias_descanso_minimo=1, dias_ventana_descanso=3,
        w_falta=1000, w_equidad=10, w_descanso_lim=5, w_variedad=2,
        w_repeticion=1, w_falta_desc=5,
    )
    dias = cfg.dias  # [1, 2, 3]

    monitores = {
        "Ana": Monitor(nombre="Ana", sexo="F", grupo="X", permite_descanso=True, penalizar_descanso=False),
        "Luis": Monitor(nombre="Luis", sexo="M", grupo="X", permite_descanso=True, penalizar_descanso=False),
        "Fin de Semana": Monitor(nombre="Fin de Semana", sexo="M", grupo="FINDE", permite_descanso=False, penalizar_descanso=False),
    }

    turnos = {
        "cocina": TipoTurno(turno="cocina", plazas_default=1, sexo_req="-", esfuerzo=2, fila_ini=2, fila_fin=2),
        "vigilancia_chicos": TipoTurno(turno="vigilancia_chicos", plazas_default=1, sexo_req="M", esfuerzo=2, fila_ini=3, fila_fin=3),
    }

    dependientes = {
        "Nino": Dependiente(acampado="Nino", sexo_monitor_req="-", esfuerzo=4, fila=4),
    }

    disponibilidad = {}
    for m in monitores:
        for d in dias:
            disponibilidad[(m, d)] = "D"
    disponibilidad[("Ana", 3)] = "X"  # Ana ausente el día 3

    plazas = {(t, d): tt.plazas_default for t, tt in turnos.items() for d in dias}

    asig_dependiente = {("Nino", d): "" for d in dias}  # por decidir todos los días

    dias_presente = {m: sum(1 for d in dias if disponibilidad[(m, d)] in ("D", "R")) for m in monitores}

    restricciones = {
        nombre: RestriccionInfo(nombre=nombre, activa=True, tipo="DURA")
        for nombre in [
            "cobertura", "un_turno_por_dia", "disponibilidad", "descanso_forzado",
            "sexo_turno", "sexo_dependiente", "finde_sin_descanso", "vigilancia_no_comedor",
            "cobertura_dependiente", "asignacion_dep_fijada", "max_2_dependientes",
            "max_3_dias_por_dep", "bloques_no_intercalados", "dep_2_dias_tercero_descansa",
            "historico_inmutable", "equidad_esfuerzo", "penalizar_descanso_limitado",
            "variedad_dependiente", "no_repetir_turno", "descanso_minimo",
        ]
    }

    return Datos(
        cfg=cfg, dias=dias, monitores=monitores, turnos=turnos, dependientes=dependientes,
        disponibilidad=disponibilidad, plazas=plazas, asig_dependiente=asig_dependiente,
        fijaciones=[], historico_x={}, historico_r={}, dias_presente=dias_presente,
        restricciones=restricciones,
    )


def test_ausente_no_genera_variables():
    datos = _datos_sinteticos()
    m = construir_modelo(datos)
    # Ana está ausente el día 3: ningún índice de x/y/r debe mencionarla ese día.
    assert not any(mo == "Ana" and d == 3 for (mo, t, d) in m.x_idx)
    assert not any(mo == "Ana" and d == 3 for (mo, d) in m.r_idx)


def test_sexo_turno_filtra_indices():
    datos = _datos_sinteticos()
    m = construir_modelo(datos)
    # vigilancia_chicos requiere sexo M: Ana (F) nunca debe aparecer ahí.
    assert not any(mo == "Ana" and t == "vigilancia_chicos" for (mo, t, d) in m.x_idx)
    assert any(mo == "Luis" and t == "vigilancia_chicos" for (mo, t, d) in m.x_idx)


def test_permite_descanso_0_no_genera_r():
    datos = _datos_sinteticos()
    m = construir_modelo(datos)
    assert not any(mo == "Fin de Semana" for (mo, d) in m.r_idx)


def test_modelo_resuelve_factible():
    from turnos.resolver import resolver_modelo

    datos = _datos_sinteticos()
    m = construir_modelo(datos)
    sol = resolver_modelo(m, datos)
    assert sol.estado in ("optimo", "factible (límite de tiempo o gap)")
    # Nadie debe tener dos cosas el mismo día.
    from collections import defaultdict
    cosas = defaultdict(int)
    for (mo, t, d), v in sol.x.items():
        if v == 1:
            cosas[(mo, d)] += 1
    for (mo, p, d), v in sol.y.items():
        if v == 1:
            cosas[(mo, d)] += 1
    for (mo, d), v in sol.r.items():
        if v == 1:
            cosas[(mo, d)] += 1
    assert all(c <= 1 for c in cosas.values())
