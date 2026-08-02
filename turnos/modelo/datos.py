"""Estructuras de datos del problema.

Estas clases son el contrato entre `io_excel.lector` y `modelo.construir`:
el lector produce un objeto `Datos` ya validado: el constructor del modelo
SOLO consume `Datos` y nunca toca el Excel. Así el modelo se puede testear
con datos sintéticos, sin abrir ningún fichero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Códigos de disponibilidad válidos en la hoja DISPONIBILIDAD.
DISPONIBLE = "D"
AUSENTE = "X"
DESCANSO_IMPUESTO = "R"
CODIGOS_DISPONIBILIDAD = {DISPONIBLE, AUSENTE, DESCANSO_IMPUESTO}

# Sentinela para "el acampado no está presente ese día" en ASIG_DEPENDIENTE.
NO_PRESENTE = None
# Sentinela para "la celda está vacía, que lo decida el modelo".
POR_DECIDIR = ""

TURNO_DESCANSO = "descanso"


@dataclass
class Config:
    quincena: int
    anio: int
    mes: int
    dia_inicio: int
    dia_fin: int
    dia_reoptimizacion: int
    solver: str
    time_limit_s: float
    mip_gap: float
    dias_descanso_minimo: int
    dias_ventana_descanso: int
    w_falta: float
    w_equidad: float
    w_descanso_lim: float
    w_variedad: float
    w_repeticion: float
    w_falta_desc: float
    max_dias_por_dep: int = 3

    @property
    def dias(self) -> List[int]:
        return list(range(self.dia_inicio, self.dia_fin + 1))


@dataclass
class Monitor:
    nombre: str
    sexo: str
    grupo: str
    permite_descanso: bool
    penalizar_descanso: bool
    dependiente_1: Optional[str] = None
    dependiente_2: Optional[str] = None


@dataclass
class TipoTurno:
    turno: str
    plazas_default: int
    sexo_req: str  # 'M', 'F' o '-'
    esfuerzo: float
    fila_ini: Optional[int]
    fila_fin: Optional[int]


@dataclass
class Dependiente:
    acampado: str
    sexo_monitor_req: str  # 'M', 'F' o '-'
    esfuerzo: float
    fila: int


@dataclass
class Fijacion:
    dia: int
    turno: str
    monitor: str
    tipo: str  # 'OBLIGA' o 'PROHIBE'
    origen: str = "FIJACIONES"


@dataclass
class RestriccionInfo:
    nombre: str
    activa: bool
    tipo: str  # 'DURA' o 'BLANDA'
    descripcion: str = ""


@dataclass
class Datos:
    cfg: Config
    dias: List[int]
    monitores: Dict[str, Monitor]
    turnos: Dict[str, TipoTurno]  # solo turnos de trabajo, sin 'descanso'
    dependientes: Dict[str, Dependiente]

    disponibilidad: Dict[Tuple[str, int], str]  # (monitor, dia) -> D/X/R
    plazas: Dict[Tuple[str, int], int]          # (turno, dia) -> plazas necesarias

    # (acampado, dia) -> nombre canónico del monitor (fijado) | None (no
    # presente, celda '-') | "" (presente pero sin decidir todavía).
    asig_dependiente: Dict[Tuple[str, int], Optional[str]]

    fijaciones: List[Fijacion]

    # Datos leídos de la rejilla TURNOS para días < DIA_REOPTIMIZACION:
    # asignaciones de trabajo y de descanso que hay que fijar tal cual.
    historico_x: Dict[Tuple[str, str, int], int]  # (monitor,turno,dia)->1
    historico_r: Dict[Tuple[str, int], int]        # (monitor,dia)->1

    dias_presente: Dict[str, int]  # nº de días con disponibilidad D o R

    restricciones: Dict[str, RestriccionInfo]

    # True si en algún día no hay plazas suficientes para que TODOS los
    # monitores de PERMITE_DESCANSO=0 trabajen (ver validar.py). En ese caso
    # 'finde_sin_descanso' se degrada a blanda para no dejar el modelo
    # infactible.
    finde_forzar_blanda: bool = False

    avisos: List[str] = field(default_factory=list)

    def turno_de_fila(self, fila: int) -> Optional[str]:
        for t in self.turnos.values():
            if t.fila_ini is not None and t.fila_ini <= fila <= t.fila_fin:
                return t.turno
        return None

    def restriccion_activa(self, nombre: str) -> bool:
        info = self.restricciones.get(nombre)
        return bool(info and info.activa)


@dataclass
class Solucion:
    x: Dict[Tuple[str, str, int], int]        # (monitor,turno,dia) -> 0/1
    y: Dict[Tuple[str, str, int], int]         # (monitor,acampado,dia) -> 0/1
    r: Dict[Tuple[str, int], int]              # (monitor,dia) -> 0/1
    falta: Dict[Tuple[str, int], float]        # (turno,dia) -> plazas sin cubrir
    estado: str                                # 'optimo', 'factible', 'infactible', ...
    gap: Optional[float] = None
    tiempo_s: Optional[float] = None
    objetivo: Optional[float] = None
    diagnostico: List[str] = field(default_factory=list)

    def turno_de(self, monitor: str, dia: int) -> Optional[str]:
        for (m, t, d), v in self.x.items():
            if m == monitor and d == dia and v == 1:
                return t
        return None
