"""sexo_turno: vigilancia_chicos/vigilancia_D_chicos solo chicos;
vigilancia_chicas/vigilancia_D_chicas solo chicas.

Ya garantizado al generar `x_idx` en `modelo.construir` (se compara
`TIPOS_TURNO.SEXO_REQ` contra `MONITORES.SEXO` antes de crear cada índice).
Módulo no-op, solo para que exista el interruptor en RESTRICCIONES.
"""
from .base import restriccion


@restriccion("sexo_turno")
def aplicar(m, datos, cfg):
    return None
