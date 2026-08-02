"""Mecanismo de restricciones enchufables.

Cada restricción es un módulo `rNN_nombre.py` que registra su función con el
decorador `@restriccion("nombre_exacto_de_la_hoja_RESTRICCIONES")`.
`modelo.construir` recorre `REGISTRO`, mira en la hoja `RESTRICCIONES` cuáles
tienen `ACTIVA = 1` y llama solo a esas, en el orden en que se registraron.

Añadir una regla nueva = crear un fichero `rNN_algo.py` con este patrón e
importarlo en `modelo/restricciones/__init__.py`, más una fila nueva en la
hoja `RESTRICCIONES`. No hace falta tocar `construir.py` ni ningún otro
módulo existente.

Ejemplo mínimo:

    # modelo/restricciones/r08_vigilancia_no_comedor.py
    from pyomo.environ import Constraint
    from .base import restriccion

    VIGILANCIA = ["vigilancia_chicos", "vigilancia_chicas",
                  "vigilancia_D_chicos", "vigilancia_D_chicas"]

    @restriccion("vigilancia_no_comedor")
    def aplicar(m, datos, cfg):
        dias = datos.dias
        def regla(m, mon, i):
            d, d1 = dias[i], dias[i + 1]
            izq = sum(m.x[mon, t, d] for t in VIGILANCIA if (mon, t, d) in m.x_idx)
            if (mon, "comedor", d1) not in m.x_idx:
                return Constraint.Skip
            return izq + m.x[mon, "comedor", d1] <= 1
        m.c_vigilancia_no_comedor = Constraint(
            m.MONITORES, range(len(dias) - 1), rule=regla)
"""
from __future__ import annotations

from typing import Callable, Dict

REGISTRO: Dict[str, dict] = {}


def restriccion(nombre: str, tipo: str = "DURA"):
    """Decorador: registra `fn(m, datos, cfg)` bajo `nombre`.

    `nombre` debe coincidir exactamente con la columna NOMBRE de la hoja
    RESTRICCIONES. `tipo` es solo documental (DURA/BLANDA); lo que de verdad
    manda si la regla se aplica es la columna ACTIVA de esa hoja.
    """

    def deco(fn: Callable):
        if nombre in REGISTRO:
            raise ValueError(f"La restricción '{nombre}' ya está registrada (colisión de nombre)")
        REGISTRO[nombre] = {"fn": fn, "tipo": tipo}
        return fn

    return deco


def registrar_penalizacion(m, nombre: str, expresion) -> None:
    """Añade una expresión (sin ponderar) a la bolsa de penalizaciones.

    `modelo.objetivo` multiplica cada expresión por el peso `W_*` de CONFIG
    que le corresponda y las suma todas. Las restricciones "duras" que
    generan holgura (p. ej. `cobertura`) también pasan por aquí: lo que las
    hace duras es que la igualdad/desigualdad en sí no se puede saltar, no
    que su holgura sea gratis.
    """
    if not hasattr(m, "_penalizaciones"):
        m._penalizaciones = {}
    m._penalizaciones[nombre] = expresion
