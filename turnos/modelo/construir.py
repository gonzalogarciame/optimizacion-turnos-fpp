"""Datos -> ConcreteModel de Pyomo.

Regla de oro: este módulo NO lee el Excel. Solo consume el objeto `Datos`
que produce `io_excel.lector`. Así el modelo se puede testear con datos
sintéticos.

Aquí se generan los índices válidos de cada variable (§4.2 de las
instrucciones: "genera solo los índices válidos... un índice inexistente
reduce el modelo, no lo modeles como una variable fijada a 0") y se aplican,
en orden, las restricciones activas de la hoja RESTRICCIONES. Las
FIJACIONES (y las celdas amarillas de TURNOS) se aplican siempre, al final,
porque no son una "regla" enchufable sino datos de entrada directos del
usuario.
"""
from __future__ import annotations

from pyomo.environ import Binary, ConcreteModel, Constraint, Set, Var

from .datos import NO_PRESENTE, POR_DECIDIR, TURNO_DESCANSO, Datos
from .objetivo import construir_objetivo
from .restricciones import REGISTRO


class ErrorModeloInconsistente(Exception):
    """Los datos (normalmente FIJACIONES) contradicen la estructura del modelo."""


def _construir_x_idx(datos: Datos):
    idx = []
    for mo, mon in datos.monitores.items():
        for d in datos.dias:
            if datos.disponibilidad[(mo, d)] == "X":
                continue
            for t, tt in datos.turnos.items():
                if tt.sexo_req != "-" and tt.sexo_req != mon.sexo:
                    continue
                idx.append((mo, t, d))
    return idx


def _construir_r_idx(datos: Datos):
    idx = []
    for mo, mon in datos.monitores.items():
        if not mon.permite_descanso and not datos.finde_forzar_blanda:
            continue
        for d in datos.dias:
            if datos.disponibilidad[(mo, d)] == "X":
                continue
            idx.append((mo, d))
    return idx


def _construir_y_idx(datos: Datos):
    """Devuelve (y_idx, z_pares, monitores_y_libre).

    Si la celda (p,d) de ASIG_DEPENDIENTE ya trae un monitor fijo, se genera
    UN SOLO índice de `y` (el de ese monitor); no se crean variables para el
    resto de monitores elegibles, así el modelo no crece de más y las
    reglas 9-12 quedan satisfechas por construcción para ese monitor. Si la
    celda está vacía (POR_DECIDIR), se generan variables para todos los
    monitores elegibles por sexo y disponibilidad, y esos monitores entran
    en `monitores_y_libre`.
    """
    y_idx = []
    z_pares = set()
    monitores_y_libre = set()

    for p, dep in datos.dependientes.items():
        for d in datos.dias:
            asignado = datos.asig_dependiente.get((p, d), NO_PRESENTE)
            if asignado is NO_PRESENTE:
                continue
            if asignado == POR_DECIDIR:
                for mo, mon in datos.monitores.items():
                    if dep.sexo_monitor_req != "-" and dep.sexo_monitor_req != mon.sexo:
                        continue
                    if datos.disponibilidad[(mo, d)] == "X":
                        continue
                    y_idx.append((mo, p, d))
                    z_pares.add((mo, p))
                    monitores_y_libre.add(mo)
            else:
                y_idx.append((asignado, p, d))
                z_pares.add((asignado, p))

    return y_idx, z_pares, monitores_y_libre


def construir_modelo(datos: Datos) -> ConcreteModel:
    m = ConcreteModel(name="turnos_campamento")
    m.datos = datos

    m.MONITORES = Set(initialize=list(datos.monitores.keys()), ordered=True)
    m.TURNOS = Set(initialize=list(datos.turnos.keys()), ordered=True)
    m.DIAS = Set(initialize=datos.dias, ordered=True)
    m.DEPENDIENTES = Set(initialize=list(datos.dependientes.keys()), ordered=True)

    x_idx = _construir_x_idx(datos)
    m.x_idx = Set(initialize=x_idx, dimen=3)
    m.x = Var(m.x_idx, domain=Binary)

    r_idx = _construir_r_idx(datos)
    m.r_idx = Set(initialize=r_idx, dimen=2)
    m.r = Var(m.r_idx, domain=Binary)

    y_idx, z_pares, monitores_y_libre = _construir_y_idx(datos)
    m.y_idx = Set(initialize=y_idx, dimen=3)
    m.y = Var(m.y_idx, domain=Binary)
    m.monitores_y_libre = monitores_y_libre

    m.z_idx = Set(initialize=sorted(z_pares), dimen=2)
    m.z = Var(m.z_idx, domain=Binary)

    # Definición de z (bookkeeping estructural, no una "regla" de negocio):
    # z[m,p] = 1 si m atiende a p algún día.
    def _regla_y_le_z(m, mo, p, d):
        return m.y[mo, p, d] <= m.z[mo, p]

    m.c_y_le_z = Constraint(m.y_idx, rule=_regla_y_le_z)

    def _regla_z_le_suma_y(m, mo, p):
        dias_validos = [d for d in datos.dias if (mo, p, d) in m.y_idx]
        if not dias_validos:
            return Constraint.Skip
        return m.z[mo, p] <= sum(m.y[mo, p, d] for d in dias_validos)

    m.c_z_le_suma_y = Constraint(m.z_idx, rule=_regla_z_le_suma_y)

    # --- Restricciones enchufables activas según la hoja RESTRICCIONES ---
    aplicadas = []
    for nombre, info in REGISTRO.items():
        if datos.restriccion_activa(nombre):
            info["fn"](m, datos, datos.cfg)
            aplicadas.append(nombre)
    m.restricciones_aplicadas = aplicadas

    _aplicar_fijaciones(m, datos)

    construir_objetivo(m, datos, datos.cfg)
    return m


def _aplicar_fijaciones(m: ConcreteModel, datos: Datos) -> None:
    """FIJACIONES y celdas amarillas de TURNOS: fijan x[m,t,d] a 1 (OBLIGA)
    o a 0 (PROHIBE). No es una restricción enchufable: es dato de entrada
    directo, así que se aplica siempre, sin pasar por RESTRICCIONES.
    """
    for f in datos.fijaciones:
        idx = (f.monitor, f.turno, f.dia)
        if f.tipo == "OBLIGA":
            if idx not in m.x_idx:
                raise ErrorModeloInconsistente(
                    f"Fijación imposible ({f.origen}): '{f.monitor}' no puede hacer "
                    f"'{f.turno}' el día {f.dia} (ausente, o el turno no es de su sexo)"
                )
            if m.x[idx].fixed and m.x[idx].value != 1:
                raise ErrorModeloInconsistente(
                    f"Fijación contradictoria ({f.origen}): '{f.monitor}' ya estaba "
                    f"fijado a 0 en '{f.turno}' el día {f.dia}"
                )
            m.x[idx].fix(1)
        elif f.tipo == "PROHIBE":
            if idx not in m.x_idx:
                continue  # no hay nada que prohibir, ya está excluido
            if m.x[idx].fixed and m.x[idx].value != 0:
                raise ErrorModeloInconsistente(
                    f"Fijación contradictoria ({f.origen}): '{f.monitor}' ya estaba "
                    f"fijado a 1 en '{f.turno}' el día {f.dia}, y también se PROHIBE"
                )
            m.x[idx].fix(0)
