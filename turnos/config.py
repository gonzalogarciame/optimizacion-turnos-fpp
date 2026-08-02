"""Lectura de la hoja CONFIG -> objeto Config.

CONFIG es una lista de pares clave/valor en las columnas A y B (a partir de
la fila 2). Aquí solo se interpreta esa hoja; el resto de hojas las lee
`io_excel.lector`. Los pesos del objetivo (W_*) se leen SIEMPRE de aquí:
nunca deben quedar fijos en el código.
"""
from __future__ import annotations

from typing import Any, Dict

from .modelo.datos import Config

# Claves obligatorias y su tipo de conversión.
_CLAVES_OBLIGATORIAS = {
    "QUINCENA": int,
    "AÑO": int,
    "MES": int,
    "DIA_INICIO": int,
    "DIA_FIN": int,
    "DIA_REOPTIMIZACION": int,
    "SOLVER": str,
    "TIME_LIMIT_S": float,
    "MIP_GAP": float,
    "DIAS_DESCANSO_MINIMO": int,
    "DIAS_VENTANA_DESCANSO": int,
    "W_FALTA": float,
    "W_EQUIDAD": float,
    "W_DESCANSO_LIM": float,
    "W_VARIEDAD": float,
    "W_REPETICION": float,
    "W_FALTA_DESC": float,
}

# Claves opcionales: si no aparecen, se usa el valor por defecto de Config.
_CLAVES_OPCIONALES = {
    "MAX_DIAS_POR_DEP": int,
}

# La hoja puede traer el nombre de la clave de año con o sin tilde según la
# codificación con la que se guardó el Excel.
_ALIAS_CLAVE = {"ANO": "AÑO", "AÑO": "AÑO"}


def leer_pares_clave_valor(ws) -> Dict[str, Any]:
    """Lee cualquier hoja con formato clave (col A) / valor (col B)."""
    pares: Dict[str, Any] = {}
    for fila in range(2, ws.max_row + 1):
        clave = ws.cell(fila, 1).value
        if clave is None or str(clave).strip() == "":
            continue
        clave = str(clave).strip().upper()
        clave = _ALIAS_CLAVE.get(clave, clave)
        valor = ws.cell(fila, 2).value
        pares[clave] = valor
    return pares


def leer_config(ws) -> Config:
    """Construye el objeto Config a partir de la hoja CONFIG."""
    pares = leer_pares_clave_valor(ws)

    faltantes = [c for c in _CLAVES_OBLIGATORIAS if c not in pares]
    if faltantes:
        raise ValueError(
            "CONFIG: faltan las claves obligatorias " + ", ".join(faltantes)
        )

    valores: Dict[str, Any] = {}
    for clave, tipo in _CLAVES_OBLIGATORIAS.items():
        crudo = pares[clave]
        try:
            valores[clave] = tipo(crudo)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CONFIG!{clave}: valor '{crudo}' no se puede interpretar como {tipo.__name__}"
            ) from exc

    kwargs = dict(
        quincena=valores["QUINCENA"],
        anio=valores["AÑO"],
        mes=valores["MES"],
        dia_inicio=valores["DIA_INICIO"],
        dia_fin=valores["DIA_FIN"],
        dia_reoptimizacion=valores["DIA_REOPTIMIZACION"],
        solver=str(valores["SOLVER"]).strip().lower(),
        time_limit_s=valores["TIME_LIMIT_S"],
        mip_gap=valores["MIP_GAP"],
        dias_descanso_minimo=valores["DIAS_DESCANSO_MINIMO"],
        dias_ventana_descanso=valores["DIAS_VENTANA_DESCANSO"],
        w_falta=valores["W_FALTA"],
        w_equidad=valores["W_EQUIDAD"],
        w_descanso_lim=valores["W_DESCANSO_LIM"],
        w_variedad=valores["W_VARIEDAD"],
        w_repeticion=valores["W_REPETICION"],
        w_falta_desc=valores["W_FALTA_DESC"],
    )

    for clave, tipo in _CLAVES_OPCIONALES.items():
        if clave in pares and pares[clave] not in (None, ""):
            kwargs["max_dias_por_dep"] = tipo(pares[clave])

    cfg = Config(**kwargs)

    if cfg.dia_inicio > cfg.dia_fin:
        raise ValueError("CONFIG: DIA_INICIO no puede ser posterior a DIA_FIN")
    if not (cfg.dia_inicio <= cfg.dia_reoptimizacion <= cfg.dia_fin + 1):
        raise ValueError(
            "CONFIG: DIA_REOPTIMIZACION debe estar entre DIA_INICIO y DIA_FIN+1 "
            "(DIA_FIN+1 significa 'no re-optimizar nada, todo es histórico')"
        )
    return cfg


def sobrescribir_dia_reoptimizacion(cfg: Config, dia: int) -> Config:
    """Devuelve una copia de `cfg` con DIA_REOPTIMIZACION cambiado a `dia`.

    Usado por la CLI (--desde) y la interfaz para re-optimizar sin editar
    el Excel a mano.
    """
    from dataclasses import replace

    if not (cfg.dia_inicio <= dia <= cfg.dia_fin + 1):
        raise ValueError(
            f"--desde {dia} fuera de rango [{cfg.dia_inicio}, {cfg.dia_fin + 1}]"
        )
    return replace(cfg, dia_reoptimizacion=dia)
