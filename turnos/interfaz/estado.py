"""Estado compartido de la app Streamlit: carga/guarda el Excel una vez y lo
deja en `st.session_state` para que las cinco páginas trabajen sobre los
mismos datos en memoria hasta que el usuario pulse "Guardar en Excel".

La interfaz NUNCA escribe directamente celdas sueltas del Excel: construye
un objeto `Datos` (o lo modifica) y usa siempre `io_excel.escritor` /
`io_excel.lector`, igual que la CLI. Así ambas vías quedan sincronizadas y
no hay dos formas distintas de tocar el fichero.
"""
from __future__ import annotations

import io
from dataclasses import replace
from typing import Optional

import streamlit as st

from ..io_excel.lector import ErrorLecturaExcel, leer_datos
from ..modelo.datos import Datos
from ..nombres import ErrorNombreNoReconocido

RUTA_POR_DEFECTO = "datos/2026-quincena2-18al30jul/turnos.xlsx"


def inicializar_estado() -> None:
    st.session_state.setdefault("ruta_excel", RUTA_POR_DEFECTO)
    st.session_state.setdefault("datos", None)
    st.session_state.setdefault("modelo", None)
    st.session_state.setdefault("solucion", None)
    st.session_state.setdefault("error_carga", None)
    st.session_state.setdefault("cambios_sin_guardar", False)


def cargar(ruta: str, desde: Optional[int] = None) -> bool:
    try:
        datos = leer_datos(ruta, desde=desde)
    except (ErrorLecturaExcel, ErrorNombreNoReconocido, ValueError) as exc:
        st.session_state["error_carga"] = str(exc)
        st.session_state["datos"] = None
        return False
    st.session_state["ruta_excel"] = ruta
    st.session_state["datos"] = datos
    st.session_state["modelo"] = None
    st.session_state["solucion"] = None
    st.session_state["error_carga"] = None
    st.session_state["cambios_sin_guardar"] = False
    return True


def datos_actuales() -> Optional[Datos]:
    return st.session_state.get("datos")


def marcar_cambio() -> None:
    st.session_state["cambios_sin_guardar"] = True
