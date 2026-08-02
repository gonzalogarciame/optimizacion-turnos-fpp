"""Importa todos los módulos rNN_*.py para que se registren en REGISTRO.

`modelo.construir` solo necesita `from modelo.restricciones import REGISTRO`
(vía este `__init__`) para tener disponibles todas las reglas. Para añadir
una restricción nueva: crea `rNN_tu_regla.py` siguiendo el patrón de
`base.py`, impórtalo aquí abajo y añade la fila correspondiente en la hoja
RESTRICCIONES del Excel. No hay que tocar nada más.
"""
from .base import REGISTRO, registrar_penalizacion, restriccion  # noqa: F401

from . import r01_cobertura  # noqa: F401
from . import r02_un_turno_por_dia  # noqa: F401
from . import r03_disponibilidad  # noqa: F401
from . import r04_descanso_forzado  # noqa: F401
from . import r05_sexo_turno  # noqa: F401
from . import r06_sexo_dependiente  # noqa: F401
from . import r07_finde_sin_descanso  # noqa: F401
from . import r08_vigilancia_no_comedor  # noqa: F401
from . import r09_cobertura_dependiente  # noqa: F401
from . import r10_asignacion_dep_fijada  # noqa: F401
from . import r11_max_2_dependientes  # noqa: F401
from . import r12_max_3_dias_por_dep  # noqa: F401
from . import r13_bloques_no_intercalados  # noqa: F401
from . import r14_dep_2_dias_tercero_descansa  # noqa: F401
from . import r15_historico_inmutable  # noqa: F401
from . import r16_equidad_esfuerzo  # noqa: F401
from . import r17_penalizar_descanso_limitado  # noqa: F401
from . import r18_variedad_dependiente  # noqa: F401
from . import r19_no_repetir_turno  # noqa: F401
from . import r20_descanso_minimo  # noqa: F401
