"""Interfaz Streamlit del optimizador de turnos.

Lanzar con:

    streamlit run turnos/interfaz/app.py

Cinco pantallas (barra lateral): Rejilla, Monitores, Disponibilidad,
Optimizar, Informe. La interfaz lee y escribe siempre sobre el Excel (nunca
sobre una base de datos): cada acción de guardado llama a las mismas
funciones que usa la CLI (`io_excel.escritor`, `interfaz.editor_datos`) y
luego vuelve a leer el fichero para refrescar el estado en memoria, así el
Excel sigue siendo la única fuente de verdad.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit ejecuta este fichero como script suelto (sin contexto de
# paquete), así que hay que añadir la raíz del proyecto a sys.path para
# poder hacer imports absolutos de `turnos`.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import pandas as pd
import streamlit as st

from turnos.interfaz import estado
from turnos.interfaz.editor_datos import (
    agregar_fijacion,
    guardar_disponibilidad_df,
    guardar_monitores_df,
    leer_disponibilidad_df,
    leer_monitores_df,
)
from turnos.io_excel.escritor import escribir_solucion
from turnos.modelo.construir import ErrorModeloInconsistente, construir_modelo
from turnos.nombres import ErrorNombreNoReconocido, ResolverNombres
from turnos.resolver import resolver_modelo
from turnos.validar import validar_previa

st.set_page_config(page_title="Turnos del campamento", layout="wide")
estado.inicializar_estado()


# ---------------------------------------------------------------------
# Barra lateral: carga del Excel, siempre visible
# ---------------------------------------------------------------------
def _barra_lateral():
    st.sidebar.title("Turnos del campamento")
    ruta = st.sidebar.text_input("Excel", value=st.session_state["ruta_excel"])
    if st.sidebar.button("Cargar / recargar"):
        if estado.cargar(ruta):
            st.sidebar.success("Cargado.")
        else:
            st.sidebar.error(st.session_state["error_carga"])

    if st.session_state.get("error_carga"):
        st.sidebar.error(st.session_state["error_carga"])

    datos = estado.datos_actuales()
    if datos:
        st.sidebar.markdown(
            f"**Horizonte:** {datos.cfg.dia_inicio}–{datos.cfg.dia_fin}  \n"
            f"**Re-optimizar desde:** día {datos.cfg.dia_reoptimizacion}  \n"
            f"**Monitores:** {len(datos.monitores)}  \n"
            f"**Dependientes:** {len(datos.dependientes)}"
        )
        if datos.avisos:
            with st.sidebar.expander(f"Avisos de lectura ({len(datos.avisos)})"):
                for a in datos.avisos:
                    st.write("- " + a)

    return st.sidebar.radio(
        "Pantalla", ["Rejilla", "Monitores", "Disponibilidad", "Optimizar", "Informe"]
    )


# ---------------------------------------------------------------------
# 1. Rejilla
# ---------------------------------------------------------------------
def _monitor_de_turno_dia(datos, solucion, turno, dia):
    if solucion is not None:
        return sorted(mo for (mo, t, d), v in solucion.x.items() if t == turno and d == dia and v == 1)
    return sorted(mo for (mo, t, d), v in datos.historico_x.items() if t == turno and d == dia and v == 1)


def _descansan_dia(datos, solucion, dia):
    if solucion is not None:
        return sorted(mo for (mo, d), v in solucion.r.items() if d == dia and v == 1)
    return sorted(mo for (mo, d), v in datos.historico_r.items() if d == dia)


def pagina_rejilla():
    st.header("Rejilla de turnos")
    datos = estado.datos_actuales()
    if not datos:
        st.info("Carga un Excel desde la barra lateral.")
        return

    solucion = st.session_state.get("solucion")
    dia_reopt = datos.cfg.dia_reoptimizacion

    st.caption(
        "Los días anteriores al de re-optimización (gris) están bloqueados. "
        "Escribe un nombre en un día futuro y pulsa 'Guardar fijaciones' para imponerlo "
        "(equivale a pintarlo de amarillo y añadirlo a FIJACIONES)."
    )

    cambios_pendientes = []

    for turno, tt in sorted(datos.turnos.items(), key=lambda kv: (kv[1].fila_ini or 0)):
        plazas_max = max((datos.plazas.get((turno, d), tt.plazas_default) for d in datos.dias), default=tt.plazas_default)
        plazas_max = max(plazas_max, 1)
        filas = {}
        for d in datos.dias:
            asignados = _monitor_de_turno_dia(datos, solucion, turno, d)
            columna = asignados + [""] * (plazas_max - len(asignados))
            filas[str(d)] = columna[:plazas_max]
        df = pd.DataFrame(filas)
        columnas_bloqueadas = [str(d) for d in datos.dias if d < dia_reopt]

        st.subheader(f"{turno}  (plazas: {', '.join(str(datos.plazas.get((turno, d), 0)) for d in datos.dias)})")
        editado = st.data_editor(
            df, disabled=columnas_bloqueadas, key=f"grid_{turno}", hide_index=True, width="stretch",
        )

        for d in datos.dias:
            if d < dia_reopt:
                continue
            col = str(d)
            originales = set(df[col]) - {""}
            nuevos = set(editado[col]) - {""}
            for nombre in nuevos - originales:
                cambios_pendientes.append((d, turno, nombre))

    st.subheader("DESCANSO (informativo, lo regenera el sistema al optimizar)")
    tabla_descanso = {str(d): ", ".join(_descansan_dia(datos, solucion, d)) for d in datos.dias}
    st.dataframe(pd.DataFrame([tabla_descanso]), hide_index=True, width="stretch")

    if cambios_pendientes:
        st.warning(f"{len(cambios_pendientes)} celda(s) nueva(s) sin guardar como fijación.")
        if st.button("Guardar fijaciones de la rejilla"):
            resolver = ResolverNombres.construir(datos.monitores.keys(), [])
            errores = []
            for dia, turno, nombre in cambios_pendientes:
                try:
                    canonico = resolver.resolver(nombre)
                except ErrorNombreNoReconocido:
                    errores.append(f"'{nombre}' no se reconoce como monitor (día {dia}, {turno})")
                    continue
                agregar_fijacion(st.session_state["ruta_excel"], dia, turno, canonico, "OBLIGA")
            if errores:
                st.error("\n".join(errores))
            else:
                st.success("Fijaciones guardadas. Recarga para verlas reflejadas.")
            estado.cargar(st.session_state["ruta_excel"], desde=dia_reopt)
            st.rerun()


# ---------------------------------------------------------------------
# 2. Monitores
# ---------------------------------------------------------------------
def pagina_monitores():
    st.header("Monitores")
    datos = estado.datos_actuales()
    if not datos:
        st.info("Carga un Excel desde la barra lateral.")
        return

    df = leer_monitores_df(st.session_state["ruta_excel"])
    st.caption(
        "Añade una fila para dar de alta a un monitor (se crea también su fila en "
        "DISPONIBILIDAD con 'D' todos los días). Borrar una fila NO borra su disponibilidad "
        "ni su histórico en TURNOS: revísalo a mano si hace falta."
    )
    editado = st.data_editor(
        df,
        num_rows="dynamic",
        column_config={
            "SEXO": st.column_config.SelectboxColumn(options=["M", "F"]),
            "PERMITE_DESCANSO": st.column_config.CheckboxColumn(),
            "PENALIZAR_DESCANSO": st.column_config.CheckboxColumn(),
        },
        hide_index=True,
        width="stretch",
        key="editor_monitores",
    )

    if st.button("Guardar monitores en Excel"):
        editado = editado.copy()
        editado["PERMITE_DESCANSO"] = editado["PERMITE_DESCANSO"].astype(int)
        editado["PENALIZAR_DESCANSO"] = editado["PENALIZAR_DESCANSO"].astype(int)
        avisos = guardar_monitores_df(st.session_state["ruta_excel"], editado, datos.dias)
        for a in avisos:
            st.warning(a)
        st.success("Monitores guardados.")
        estado.cargar(st.session_state["ruta_excel"], desde=datos.cfg.dia_reoptimizacion)
        st.rerun()


# ---------------------------------------------------------------------
# 3. Disponibilidad
# ---------------------------------------------------------------------
def pagina_disponibilidad():
    st.header("Disponibilidad (D = disponible, X = ausente, R = descanso impuesto)")
    datos = estado.datos_actuales()
    if not datos:
        st.info("Carga un Excel desde la barra lateral.")
        return

    df = leer_disponibilidad_df(st.session_state["ruta_excel"], datos.dias)
    columnas_dias = {
        str(d): st.column_config.SelectboxColumn(str(d), options=["D", "X", "R"], width="small")
        for d in datos.dias
    }
    editado = st.data_editor(
        df,
        column_config=columnas_dias,
        hide_index=True,
        width="stretch",
        key="editor_disponibilidad",
    )

    if st.button("Guardar disponibilidad en Excel"):
        guardar_disponibilidad_df(st.session_state["ruta_excel"], editado, datos.dias)
        st.success("Disponibilidad guardada.")
        estado.cargar(st.session_state["ruta_excel"], desde=datos.cfg.dia_reoptimizacion)
        st.rerun()


# ---------------------------------------------------------------------
# 4. Optimizar
# ---------------------------------------------------------------------
def pagina_optimizar():
    st.header("Optimizar")
    datos = estado.datos_actuales()
    if not datos:
        st.info("Carga un Excel desde la barra lateral.")
        return

    col1, col2 = st.columns(2)
    with col1:
        desde = st.number_input(
            "Re-optimizar desde el día",
            min_value=datos.cfg.dia_inicio,
            max_value=datos.cfg.dia_fin + 1,
            value=datos.cfg.dia_reoptimizacion,
        )
        if st.button("Aplicar día de re-optimización"):
            estado.cargar(st.session_state["ruta_excel"], desde=int(desde))
            st.rerun()
    with col2:
        dos_fases = st.checkbox("Resolver equidad en dos fases", value=False)

    informe = validar_previa(datos)
    if informe.errores:
        st.error("Errores de validación:\n\n" + "\n".join(f"- {e}" for e in informe.errores))
    if informe.avisos:
        with st.expander(f"Avisos de validación ({len(informe.avisos)})"):
            for a in informe.avisos:
                st.write("- " + a)

    forzar = informe.errores and st.checkbox("Intentar optimizar de todos modos (hay errores)")

    if st.button("Optimizar", disabled=bool(informe.errores) and not forzar):
        with st.spinner("Construyendo el modelo y resolviendo..."):
            try:
                modelo = construir_modelo(datos)
            except ErrorModeloInconsistente as exc:
                st.error(f"Error construyendo el modelo: {exc}")
                return
            solucion = resolver_modelo(modelo, datos, dos_fases=dos_fases)
        st.session_state["modelo"] = modelo
        st.session_state["solucion"] = solucion

    solucion = st.session_state.get("solucion")
    if solucion:
        st.subheader("Resultado")
        st.write(f"Estado: **{solucion.estado}**  |  Tiempo: {solucion.tiempo_s:.1f}s")
        if solucion.gap is not None:
            st.write(f"Gap: {solucion.gap:.2%}")
        if solucion.objetivo is not None:
            st.write(f"Objetivo: {solucion.objetivo:.2f}")

        if solucion.estado == "infactible":
            st.error("Modelo infactible. Diagnóstico (IIS):")
            for linea in solucion.diagnostico:
                st.write("- " + linea)
        else:
            total_falta = sum(solucion.falta.values()) if solucion.falta else 0
            if total_falta > 1e-6:
                st.warning(f"Quedan {total_falta:.0f} plazas sin cubrir.")
            else:
                st.success("Todos los turnos cubiertos.")

            cB, cC = st.columns(2)
            with cB:
                if st.button("Guardar en Excel (con copia de seguridad)"):
                    ruta = escribir_solucion(st.session_state["ruta_excel"], datos, solucion, dry_run=False)
                    st.success(f"Guardado en {ruta}")
                    estado.cargar(st.session_state["ruta_excel"], desde=datos.cfg.dia_reoptimizacion)
                    st.session_state["solucion"] = None
                    st.rerun()
            with cC:
                if st.button("Preparar descarga"):
                    ruta_tmp = escribir_solucion(
                        st.session_state["ruta_excel"], datos, solucion, dry_run=True
                    )
                    with open(ruta_tmp, "rb") as fh:
                        st.session_state["descarga_bytes"] = fh.read()
                        st.session_state["descarga_nombre"] = Path(ruta_tmp).name

    if st.session_state.get("descarga_bytes"):
        st.download_button(
            "Descargar Excel",
            data=st.session_state["descarga_bytes"],
            file_name=st.session_state["descarga_nombre"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ---------------------------------------------------------------------
# 5. Informe
# ---------------------------------------------------------------------
def pagina_informe():
    st.header("Informe")
    datos = estado.datos_actuales()
    solucion = st.session_state.get("solucion")
    if not datos or not solucion or solucion.estado == "infactible":
        st.info("Optimiza primero (pantalla 'Optimizar') para ver el informe.")
        return

    st.subheader("Esfuerzo normalizado por monitor")
    cargas = {}
    for mo in datos.monitores:
        dp = datos.dias_presente.get(mo, 0)
        if dp == 0:
            continue
        carga = sum(datos.turnos[t].esfuerzo for (m2, t, d), v in solucion.x.items() if m2 == mo and v == 1)
        carga += sum(datos.dependientes[p].esfuerzo for (m2, p, d), v in solucion.y.items() if m2 == mo and v == 1)
        cargas[mo] = carga / dp
    serie = pd.Series(cargas).sort_values(ascending=False)
    st.bar_chart(serie)

    st.subheader("Descansos por monitor")
    descansos = {}
    for (mo, d), v in solucion.r.items():
        if v == 1:
            descansos[mo] = descansos.get(mo, 0) + 1
    st.bar_chart(pd.Series(descansos).sort_values(ascending=False))

    st.subheader("Días de dependiente por monitor")
    dias_dep_monitor = {}
    for (mo, p, d), v in solucion.y.items():
        if v == 1:
            dias_dep_monitor[mo] = dias_dep_monitor.get(mo, 0) + 1
    if dias_dep_monitor:
        st.bar_chart(pd.Series(dias_dep_monitor).sort_values(ascending=False))
    else:
        st.caption("Nadie con días de dependiente en esta solución.")

    st.subheader("Días de dependiente por acampado")
    dias_dep_acampado = {}
    for (mo, p, d), v in solucion.y.items():
        if v == 1:
            dias_dep_acampado[p] = dias_dep_acampado.get(p, 0) + 1
    if dias_dep_acampado:
        st.bar_chart(pd.Series(dias_dep_acampado).sort_values(ascending=False))

    st.subheader("Turnos sin cubrir")
    falta = {f"{t} (día {d})": v for (t, d), v in solucion.falta.items() if v > 1e-6}
    if falta:
        st.bar_chart(pd.Series(falta).sort_values(ascending=False))
    else:
        st.success("No hay turnos sin cubrir.")


# ---------------------------------------------------------------------
def main():
    pagina = _barra_lateral()
    {
        "Rejilla": pagina_rejilla,
        "Monitores": pagina_monitores,
        "Disponibilidad": pagina_disponibilidad,
        "Optimizar": pagina_optimizar,
        "Informe": pagina_informe,
    }[pagina]()


main()
