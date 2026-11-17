"""Avisos de reglas incumplidas al asignar a mano (modelo/revision.py)."""
import dataclasses

from turnos.modelo.datos import Dependiente, TipoTurno
from turnos.modelo.revision import RECOMENDACION, REGLA, Celda, revisar_asignaciones

from .test_construir_sintetico import _datos_sinteticos


def _datos(n=8):
    d = _datos_sinteticos()
    d.cfg = dataclasses.replace(d.cfg, dia_fin=n, dias_ventana_descanso=3)
    d.dias = d.cfg.dias
    d.turnos["comedor"] = TipoTurno("comedor", 2, "-", 2, None, None)
    d.turnos["vigilancia_chicas"] = TipoTurno("vigilancia_chicas", 1, "F", 2, None, None)
    for nombre in ("Pepe", "Lola"):
        d.dependientes[nombre] = Dependiente(nombre, "-", 4, 0)
    d.disponibilidad = {(m, dia): "D" for m in d.monitores for dia in d.dias}
    d.plazas = {(t, dia): tt.plazas_default for t, tt in d.turnos.items() for dia in d.dias}
    d.dias_presente = {m: n for m in d.monitores}
    return d


_n = [0]


def T(mo, turno, dia):
    _n[0] += 1
    return Celda(f"k{_n[0]}", "turno", turno, dia, mo)


def D(mo, acampado, dia):
    _n[0] += 1
    return Celda(f"k{_n[0]}", "dependiente", acampado, dia, mo)


def R(mo, dia):
    _n[0] += 1
    return Celda(f"k{_n[0]}", "descanso", "", dia, mo)


def reglas(avisos):
    return sorted(a.regla for a in avisos)


def test_una_asignacion_correcta_no_avisa():
    d = _datos()
    cs = [T("Luis", "cocina", 1), T("Ana", "comedor", 1), R("Ana", 2), T("Luis", "comedor", 2)]
    assert [a for a in revisar_asignaciones(d, cs) if a.nivel == REGLA] == []


def test_mas_gente_de_la_que_admite_el_turno():
    d = _datos()
    avisos = revisar_asignaciones(d, [T("Luis", "cocina", 1), T("Ana", "cocina", 1)])
    assert reglas(avisos) == ["cobertura"] and "admite como mucho 1" in avisos[0].mensaje and len(avisos[0].celdas) == 2
    d.plazas_max[("cocina", 1)] = 2  # si el turno acepta extras, ya no avisa
    assert revisar_asignaciones(d, [T("Luis", "cocina", 1), T("Ana", "cocina", 1)]) == []
    d.plazas[("cocina", 2)] = 0
    assert "no se hace ese día" in revisar_asignaciones(d, [T("Luis", "cocina", 2)])[0].mensaje


def test_ausente_descanso_impuesto_y_en_dos_sitios():
    d = _datos()
    d.disponibilidad[("Ana", 2)] = "X"
    d.disponibilidad[("Luis", 3)] = "R"
    cs = [T("Ana", "cocina", 2), T("Luis", "cocina", 3), T("Ana", "comedor", 4), T("Ana", "cocina", 4)]
    assert reglas(revisar_asignaciones(d, cs)) == ["descanso_forzado", "disponibilidad", "un_turno_por_dia"]


def test_sexo_del_turno_y_del_dependiente():
    d = _datos()
    d.dependientes["Pepe"].sexo_monitor_req = "F"
    cs = [T("Ana", "vigilancia_chicos", 1), T("Luis", "vigilancia_chicas", 1), D("Luis", "Pepe", 2)]
    assert reglas(revisar_asignaciones(d, cs)) == ["sexo_dependiente", "sexo_turno", "sexo_turno"]


def test_monitor_de_fin_de_semana_descansando():
    d = _datos()
    a = revisar_asignaciones(d, [R("Fin de Semana", 1)])
    assert reglas(a) == ["finde_sin_descanso"] and a[0].nivel == REGLA
    d.finde_forzar_blanda = True  # si no hay sitio para todos, pasa a ser solo una recomendación
    assert revisar_asignaciones(d, [R("Fin de Semana", 1)])[0].nivel == RECOMENDACION


def test_vigilancia_de_noche_y_comedor_al_dia_siguiente():
    d = _datos()
    a = revisar_asignaciones(d, [T("Luis", "vigilancia_chicos", 2), T("Luis", "comedor", 3)])
    assert reglas(a) == ["vigilancia_no_comedor"] and a[0].dia == 3 and len(a[0].celdas) == 2
    assert revisar_asignaciones(d, [T("Luis", "vigilancia_chicos", 2), T("Luis", "comedor", 4)]) == []


def test_reglas_de_dependientes():
    d = _datos()
    tres = [D("Luis", "Nino", 1), D("Luis", "Pepe", 3), D("Luis", "Lola", 5)]
    assert "max_2_dependientes" in reglas(revisar_asignaciones(d, tres))
    cuatro_dias = [D("Luis", "Nino", x) for x in (1, 2, 4, 5)]
    a = revisar_asignaciones(d, cuatro_dias)
    assert "max_3_dias_por_dep" in reglas(a) and "como mucho 3" in [x for x in a if x.regla == "max_3_dias_por_dep"][0].mensaje
    alterna = [D("Luis", "Nino", 1), D("Luis", "Pepe", 2), D("Luis", "Nino", 3)]
    assert "bloques_no_intercalados" in reglas(revisar_asignaciones(d, alterna))
    en_bloques = [D("Luis", "Nino", 1), D("Luis", "Pepe", 2)]
    assert "bloques_no_intercalados" not in reglas(revisar_asignaciones(d, en_bloques))


def test_dos_dias_de_dependiente_el_tercero_descansa():
    d = _datos()
    mal = [D("Luis", "Nino", 1), D("Luis", "Pepe", 2), T("Luis", "cocina", 3)]
    a = [x for x in revisar_asignaciones(d, mal) if x.regla == "dep_2_dias_tercero_descansa"]
    assert len(a) == 1 and a[0].dia == 3
    bien = [D("Luis", "Nino", 1), D("Luis", "Nino", 2), R("Luis", 3)]
    assert "dep_2_dias_tercero_descansa" not in reglas(revisar_asignaciones(d, bien))


def test_recomendaciones_repetir_turno_y_sin_descanso():
    d = _datos()
    a = revisar_asignaciones(d, [T("Luis", "cocina", 1), T("Luis", "cocina", 2), T("Luis", "comedor", 3)])
    assert {x.regla: x.nivel for x in a} == {"no_repetir_turno": RECOMENDACION, "descanso_minimo": RECOMENDACION}
    con_descanso = [T("Luis", "cocina", 1), T("Luis", "comedor", 2), R("Luis", 3)]
    assert "descanso_minimo" not in reglas(revisar_asignaciones(d, con_descanso))


def test_regla_desactivada_no_avisa_y_desde_filtra_lo_pasado():
    d = _datos()
    cs = [T("Luis", "vigilancia_chicos", 2), T("Luis", "comedor", 3)]
    assert len(revisar_asignaciones(d, cs)) == 1
    assert revisar_asignaciones(d, cs, desde=4) == []          # ya es pasado
    assert len(revisar_asignaciones(d, cs, desde=3)) == 1
    d.restricciones["vigilancia_no_comedor"].activa = False
    assert revisar_asignaciones(d, cs) == []
