"""Revisión de una rejilla escrita a mano: avisos de las reglas que se incumplen.

El optimizador cumple las reglas por construcción, pero cuando se asigna a mano
nada impide romperlas (y, en el caso de los dependientes fijados, el propio
modelo no las vigila). Aquí se repasa lo que hay escrito y se devuelve un aviso
por cada regla activa que se incumple, con las casillas implicadas.

Solo cuentan las reglas que están activas en la hoja/tabla de restricciones. Las
reglas duras salen como «regla» y las blandas (que el optimizador solo intenta
cumplir) como «recomendación».
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .datos import Datos

VIGILANCIA = ("vigilancia_chicos", "vigilancia_chicas", "vigilancia_D_chicos", "vigilancia_D_chicas")
REGLA, RECOMENDACION = "regla", "recomendacion"


@dataclass
class Celda:
    clave: str      # identificador de la casilla en la pantalla (se devuelve tal cual en los avisos)
    tipo: str       # 'turno' | 'dependiente' | 'descanso'
    objeto: str     # nombre del turno, del acampado, o '' para descanso
    dia: int
    monitor: str


@dataclass
class Aviso:
    regla: str
    nivel: str
    dia: int                 # el último día que interviene (sirve para ignorar lo ya pasado)
    mensaje: str
    celdas: List[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {"regla": self.regla, "nivel": self.nivel, "dia": self.dia, "mensaje": self.mensaje, "celdas": self.celdas}


def _dias_texto(dias: Iterable[int]) -> str:
    dias = sorted(dias)
    return ", ".join(str(d) for d in dias[:6]) + ("…" if len(dias) > 6 else "")


def revisar_asignaciones(datos: Datos, celdas: Iterable[Celda], desde: Optional[int] = None) -> List[Aviso]:
    """Avisos de reglas incumplidas. Con `desde`, solo los que afectan a ese día o a los siguientes."""
    celdas = [c for c in celdas if c.monitor and c.monitor in datos.monitores and c.dia in datos.dias]
    activa = datos.restriccion_activa
    dias = datos.dias
    siguiente = {d: dias[i + 1] for i, d in enumerate(dias[:-1])}
    por_md: Dict[tuple, List[Celda]] = defaultdict(list)
    for c in celdas:
        por_md[(c.monitor, c.dia)].append(c)
    trabajo = lambda lista: [c for c in lista if c.tipo in ("turno", "dependiente")]  # noqa: E731
    donde = lambda c: c.objeto if c.tipo == "turno" else (f"dependiente {c.objeto}" if c.tipo == "dependiente" else "descanso")  # noqa: E731

    avisos: List[Aviso] = []

    def avisar(regla, nivel, dia, mensaje, cs):
        avisos.append(Aviso(regla, nivel, dia, mensaje, [c.clave for c in cs]))

    # --- Cuántos en cada turno ------------------------------------------------
    if activa("cobertura"):
        cuenta: Dict[tuple, List[Celda]] = defaultdict(list)
        for c in celdas:
            if c.tipo == "turno" and c.objeto in datos.turnos:
                cuenta[(c.objeto, c.dia)].append(c)
        for (turno, d), cs in sorted(cuenta.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            limite = max(datos.plazas.get((turno, d), 0), datos.plazas_max.get((turno, d), 0))
            if len(cs) > limite:
                if limite == 0:
                    avisar("cobertura", REGLA, d, f"Día {d}: «{turno}» no se hace ese día, pero hay {len(cs)} persona(s) asignada(s).", cs)
                else:
                    avisar("cobertura", REGLA, d, f"Día {d}: «{turno}» admite como mucho {limite} persona(s) y hay {len(cs)}.", cs)

    # --- Reglas de un monitor un día -----------------------------------------
    for (mo, d), cs in sorted(por_md.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        mon = datos.monitores[mo]
        if activa("un_turno_por_dia") and len(cs) > 1:
            avisar("un_turno_por_dia", REGLA, d, f"Día {d}: {mo} está en {len(cs)} sitios a la vez ({', '.join(donde(c) for c in cs)}).", cs)
        estado = datos.disponibilidad.get((mo, d), "D")
        if activa("disponibilidad") and estado == "X":
            avisar("disponibilidad", REGLA, d, f"Día {d}: {mo} figura como ausente y tiene asignado {donde(cs[0])}.", cs)
        if activa("descanso_forzado") and estado == "R" and trabajo(cs):
            avisar("descanso_forzado", REGLA, d, f"Día {d}: {mo} tiene descanso impuesto y tiene asignado {donde(trabajo(cs)[0])}.", trabajo(cs))
        for c in cs:
            if c.tipo == "turno" and activa("sexo_turno"):
                req = datos.turnos[c.objeto].sexo_req if c.objeto in datos.turnos else "-"
                if req != "-" and req != mon.sexo:
                    avisar("sexo_turno", REGLA, d, f"Día {d}: «{c.objeto}» es solo para {'chicos' if req == 'M' else 'chicas'} y {mo} no lo es.", [c])
            if c.tipo == "dependiente" and activa("sexo_dependiente"):
                req = datos.dependientes[c.objeto].sexo_monitor_req if c.objeto in datos.dependientes else "-"
                if req != "-" and req != mon.sexo:
                    avisar("sexo_dependiente", REGLA, d, f"Día {d}: {c.objeto} necesita {'un chico' if req == 'M' else 'una chica'} y {mo} no lo es.", [c])
            if c.tipo == "descanso" and activa("finde_sin_descanso") and not mon.permite_descanso:
                avisar("finde_sin_descanso", RECOMENDACION if datos.finde_forzar_blanda else REGLA, d,
                       f"Día {d}: {mo} es de fin de semana y prefiere no descansar.", [c])

    # --- Vigilancia de noche y comedor al día siguiente -----------------------
    if activa("vigilancia_no_comedor") and "comedor" in datos.turnos:
        for (mo, d), cs in sorted(por_md.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            vig = [c for c in cs if c.tipo == "turno" and c.objeto in VIGILANCIA]
            d1 = siguiente.get(d)
            if vig and d1 is not None:
                com = [c for c in por_md.get((mo, d1), []) if c.tipo == "turno" and c.objeto == "comedor"]
                if com:
                    avisar("vigilancia_no_comedor", REGLA, d1,
                           f"{mo} vigila de noche el día {d} y no puede ir a comedor el día {d1}.", vig + com)

    # --- Dependientes -----------------------------------------------------------
    deps_de: Dict[str, Dict[str, List[Celda]]] = defaultdict(lambda: defaultdict(list))
    for c in celdas:
        if c.tipo == "dependiente":
            deps_de[c.monitor][c.objeto].append(c)

    for mo, por_dep in sorted(deps_de.items()):
        todas = [c for cs in por_dep.values() for c in cs]
        if activa("max_2_dependientes") and len(por_dep) > 2:
            avisar("max_2_dependientes", REGLA, max(c.dia for c in todas),
                   f"{mo} lleva a {len(por_dep)} acampados distintos ({', '.join(sorted(por_dep))}); como mucho 2.", todas)
        if activa("max_3_dias_por_dep"):
            tope = datos.cfg.max_dias_por_dep
            for dep, cs in sorted(por_dep.items()):
                if len({c.dia for c in cs}) > tope:
                    avisar("max_3_dias_por_dep", REGLA, max(c.dia for c in cs),
                           f"{mo} lleva a {dep} {len({c.dia for c in cs})} días (días {_dias_texto(c.dia for c in cs)}); como mucho {tope}.", cs)
        if activa("bloques_no_intercalados") and len(por_dep) > 1:
            nombres = sorted(por_dep)
            for i, a in enumerate(nombres):
                for b in nombres[i + 1:]:
                    da, db = [c.dia for c in por_dep[a]], [c.dia for c in por_dep[b]]
                    if not (max(da) < min(db) or max(db) < min(da)):
                        avisar("bloques_no_intercalados", REGLA, max(max(da), max(db)),
                               f"{mo} alterna entre {a} y {b}: primero tiene que llevar a uno y después al otro.",
                               por_dep[a] + por_dep[b])
        if activa("dep_2_dias_tercero_descansa"):
            dias_dep = {c.dia for c in todas}
            for d in sorted(dias_dep):
                d1 = siguiente.get(d)
                d2 = siguiente.get(d1) if d1 is not None else None
                if d1 in dias_dep and d2 is not None:
                    mon = datos.monitores[mo]
                    if datos.disponibilidad.get((mo, d2), "D") == "X" or (not mon.permite_descanso and not datos.finde_forzar_blanda):
                        continue
                    trab = trabajo(por_md.get((mo, d2), []))
                    if trab:
                        avisar("dep_2_dias_tercero_descansa", REGLA, d2,
                               f"{mo} lleva dependientes los días {d} y {d1}: el día {d2} tiene que descansar y tiene asignado {donde(trab[0])}.",
                               [c for c in todas if c.dia in (d, d1)] + trab)

    # --- Recomendaciones (el optimizador solo intenta cumplirlas) ---------------
    if activa("no_repetir_turno"):
        for (mo, d), cs in sorted(por_md.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            d1 = siguiente.get(d)
            if d1 is None:
                continue
            for c in cs:
                if c.tipo == "turno":
                    otra = [x for x in por_md.get((mo, d1), []) if x.tipo == "turno" and x.objeto == c.objeto]
                    if otra:
                        avisar("no_repetir_turno", RECOMENDACION, d1, f"{mo} repite «{c.objeto}» los días {d} y {d1}.", [c] + otra)

    if activa("descanso_minimo"):
        ventana, minimo = datos.cfg.dias_ventana_descanso, datos.cfg.dias_descanso_minimo
        if ventana > 0 and len(dias) >= ventana:
            for mo, mon in datos.monitores.items():
                if not mon.permite_descanso or datos.dias_presente.get(mo, 0) < ventana:
                    continue
                ultimo_fin = None
                for i in range(len(dias) - ventana + 1):
                    v = dias[i:i + ventana]
                    if ultimo_fin is not None and v[0] <= ultimo_fin:
                        continue
                    celdas_v = [por_md.get((mo, d), []) for d in v]
                    if any(datos.disponibilidad.get((mo, d), "D") == "X" for d in v):
                        continue
                    if all(trabajo(cs) for cs in celdas_v) and not any(c.tipo == "descanso" for cs in celdas_v for c in cs):
                        if minimo > 0:
                            avisar("descanso_minimo", RECOMENDACION, v[-1],
                                   f"{mo} lleva {ventana} días seguidos trabajando (días {v[0]}–{v[-1]}) sin descansar.",
                                   [c for cs in celdas_v for c in cs])
                            ultimo_fin = v[-1]

    if desde is not None:
        avisos = [a for a in avisos if a.dia >= desde]
    avisos.sort(key=lambda a: (a.dia, 0 if a.nivel == REGLA else 1, a.mensaje))
    return avisos
