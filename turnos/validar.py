"""Validación previa (factibilidad "a ojo") y diagnóstico de infactibilidad.

§7 de las instrucciones: antes de resolver, se comprueba en lenguaje llano
la misma lógica que la hoja `RESUMEN` (holgura por día, por sexo,
dependientes sin monitor elegible, fijaciones contradictorias...). Si pese a
eso Gurobi devuelve infactible, `diagnosticar_infactibilidad` calcula el IIS
y traduce las restricciones en conflicto a mensajes legibles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .modelo.datos import NO_PRESENTE, POR_DECIDIR, Datos

VIGILANCIA_CHICOS = ["vigilancia_chicos", "vigilancia_D_chicos"]
VIGILANCIA_CHICAS = ["vigilancia_chicas", "vigilancia_D_chicas"]


@dataclass
class InformeValidacion:
    errores: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores

    def texto(self) -> str:
        lineas = []
        if self.errores:
            lineas.append("ERRORES (impiden resolver):")
            lineas += [f"  - {e}" for e in self.errores]
        if self.avisos:
            lineas.append("Avisos:")
            lineas += [f"  - {a}" for a in self.avisos]
        if not self.errores and not self.avisos:
            lineas.append("Sin incidencias.")
        return "\n".join(lineas)


def validar_previa(datos: Datos) -> InformeValidacion:
    informe = InformeValidacion()
    informe.avisos.extend(datos.avisos)

    if not datos.monitores:
        informe.errores.append("No hay ningún monitor: añádelos en la pestaña «Monitores» antes de generar turnos.")
        return informe

    _validar_holgura_por_dia(datos, informe)
    _validar_holgura_por_sexo(datos, informe)
    _validar_dependientes_sin_monitor(datos, informe)
    _validar_fijaciones_contradictorias(datos, informe)
    _validar_permite_descanso_vs_disponibilidad(datos, informe)

    return informe


def _monitores_disponibles(datos: Datos, dia: int, sexo: str = None):
    return [
        m
        for m in datos.monitores
        if datos.disponibilidad[(m, dia)] in ("D", "R")
        and (sexo is None or datos.monitores[m].sexo == sexo)
    ]


def _dependientes_presentes(datos: Datos, dia: int):
    return [
        p
        for p in datos.dependientes
        if datos.asig_dependiente.get((p, dia), NO_PRESENTE) is not NO_PRESENTE
    ]


def _validar_holgura_por_dia(datos: Datos, informe: InformeValidacion) -> None:
    for d in datos.dias:
        disponibles = len(_monitores_disponibles(datos, d))
        plazas = sum(datos.plazas.get((t, d), 0) for t in datos.turnos)
        dependientes = len(_dependientes_presentes(datos, d))
        necesarios = plazas + dependientes
        holgura = disponibles - necesarios
        if holgura < 0:
            informe.avisos.append(
                f"Día {d}: hacen falta {necesarios} monitores y hay {disponibles} disponibles "
                f"(holgura {holgura}). El modelo seguirá siendo factible gracias a la holgura de "
                f"'cobertura', pero quedarán turnos sin cubrir salvo que ajustes plazas o disponibilidad."
            )


def _validar_holgura_por_sexo(datos: Datos, informe: InformeValidacion) -> None:
    for d in datos.dias:
        chicos = len(_monitores_disponibles(datos, d, "M"))
        chicas = len(_monitores_disponibles(datos, d, "F"))
        plazas_chicos = sum(datos.plazas.get((t, d), 0) for t in VIGILANCIA_CHICOS if t in datos.turnos)
        plazas_chicas = sum(datos.plazas.get((t, d), 0) for t in VIGILANCIA_CHICAS if t in datos.turnos)
        dep_chicos = sum(
            1
            for p in _dependientes_presentes(datos, d)
            if datos.dependientes[p].sexo_monitor_req == "M"
        )
        dep_chicas = sum(
            1
            for p in _dependientes_presentes(datos, d)
            if datos.dependientes[p].sexo_monitor_req == "F"
        )
        if chicos < plazas_chicos + dep_chicos:
            informe.errores.append(
                f"Día {d}: se necesitan {plazas_chicos} plazas de vigilancia de chicos + "
                f"{dep_chicos} dependientes que requieren monitor chico, pero solo hay {chicos} "
                f"chicos disponibles."
            )
        if chicas < plazas_chicas + dep_chicas:
            informe.errores.append(
                f"Día {d}: se necesitan {plazas_chicas} plazas de vigilancia de chicas + "
                f"{dep_chicas} dependientes que requieren monitor chica, pero solo hay {chicas} "
                f"chicas disponibles."
            )


def _validar_dependientes_sin_monitor(datos: Datos, informe: InformeValidacion) -> None:
    for p, dep in datos.dependientes.items():
        for d in datos.dias:
            asignado = datos.asig_dependiente.get((p, d), NO_PRESENTE)
            if asignado is NO_PRESENTE:
                continue
            if asignado not in (POR_DECIDIR, None) and asignado != "":
                continue  # ya fijado a mano, no hace falta que haya "elegibles" libres
            elegibles = [
                m
                for m in datos.monitores
                if (dep.sexo_monitor_req == "-" or datos.monitores[m].sexo == dep.sexo_monitor_req)
                and datos.disponibilidad[(m, d)] in ("D", "R")
            ]
            if not elegibles:
                informe.errores.append(
                    f"Día {d}: el dependiente '{p}' no tiene ningún monitor elegible "
                    f"(requiere sexo '{dep.sexo_monitor_req}') y su celda no está fijada a mano."
                )


def _validar_fijaciones_contradictorias(datos: Datos, informe: InformeValidacion) -> None:
    por_monitor_dia = {}
    for f in datos.fijaciones:
        if f.tipo != "OBLIGA":
            continue
        clave = (f.monitor, f.dia)
        if clave in por_monitor_dia and por_monitor_dia[clave] != f.turno:
            informe.errores.append(
                f"Fijaciones contradictorias: '{f.monitor}' está OBLIGAdo a "
                f"'{por_monitor_dia[clave]}' y a '{f.turno}' el mismo día {f.dia}."
            )
        por_monitor_dia[clave] = f.turno

    for f in datos.fijaciones:
        if datos.disponibilidad.get((f.monitor, f.dia)) == "X":
            informe.errores.append(
                f"Fijación imposible ({f.origen}): '{f.monitor}' está marcado como ausente (X) "
                f"el día {f.dia} pero hay una fijación de '{f.turno}' ese día."
            )


def _validar_permite_descanso_vs_disponibilidad(datos: Datos, informe: InformeValidacion) -> None:
    for m, mon in datos.monitores.items():
        if mon.permite_descanso:
            continue
        for d in datos.dias:
            if datos.disponibilidad[(m, d)] == "R":
                informe.errores.append(
                    f"'{m}' tiene PERMITE_DESCANSO=0 pero DISPONIBILIDAD marca 'R' el día {d} "
                    f"(descanso impuesto). Esto es contradictorio: corrige uno de los dos datos."
                )


# ---------------------------------------------------------------------
# Diagnóstico de infactibilidad (IIS)
# ---------------------------------------------------------------------

def diagnosticar_infactibilidad(modelo, datos: Datos) -> List[str]:
    """Recalcula el IIS con Gurobi y traduce las restricciones en conflicto.

    Requiere resolver otra vez con la interfaz `gurobi_persistent` de Pyomo
    (es la única forma de llegar al `computeIIS()` nativo de Gurobi). Si el
    solver configurado no es Gurobi, se devuelve un mensaje genérico.
    """
    mensajes: List[str] = []
    if "gurobi" not in datos.cfg.solver:
        mensajes.append(
            f"El solver configurado ('{datos.cfg.solver}') no es Gurobi: no se puede calcular "
            f"el IIS automáticamente. Revisa manualmente las restricciones marcadas como DURA."
        )
        return mensajes

    import pyomo.environ as pyo

    opt = pyo.SolverFactory("gurobi_persistent")
    opt.set_instance(modelo)
    opt.solve(tee=False, load_solutions=False)

    gm = opt._solver_model
    gm.computeIIS()

    mapa_con = opt._solver_con_to_pyomo_con_map
    mapa_var = opt._solver_var_to_pyomo_var_map

    for c in gm.getConstrs():
        if c.IISConstr:
            pc = mapa_con.get(c)
            nombre = pc.name if pc is not None else c.ConstrName
            mensajes.append(f"Restricción en conflicto: {nombre}  ({pc.expr if pc is not None else ''})")

    for v in gm.getVars():
        if getattr(v, "IISLB", False) or getattr(v, "IISUB", False):
            pv = mapa_var.get(v)
            nombre = pv.name if pv is not None else v.VarName
            mensajes.append(f"Variable fijada en conflicto: {nombre} = {v.LB}")

    mensajes.append(
        "Causa más probable (§5.2 de las instrucciones): se ha aplicado una regla de "
        "dependiente (max_2_dependientes, max_3_dias_por_dep, bloques_no_intercalados o "
        "dep_2_dias_tercero_descansa) sobre variables 'y' ya fijadas por ASIG_DEPENDIENTE. "
        "Revisa primero `modelo.monitores_y_libre`."
    )
    return mensajes
