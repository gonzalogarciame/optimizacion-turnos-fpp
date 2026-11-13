"""Rutas Flask de la interfaz web local.

Cada ruta es una fina envoltura JSON alrededor de las mismas funciones que
usa la CLI y la interfaz Streamlit (`io_excel`, `interfaz.editor_datos`,
`modelo.construir`, `resolver`, `validar`): esta capa no contiene lógica de
negocio propia, solo serializa `Datos`/`DataFrame` a JSON y de vuelta.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from flask import Flask, jsonify, request, send_file, send_from_directory

from . import estado
from ..interfaz.editor_datos import (
    agregar_dependiente,
    agregar_tipo_turno,
    guardar_config_valores,
    guardar_dependientes_df,
    guardar_disponibilidad_df,
    guardar_monitores_df,
    guardar_plazas_por_dia_df,
    guardar_restricciones_df,
    guardar_tipos_turno_df,
    leer_config_editable,
    leer_dependientes_df,
    leer_disponibilidad_df,
    leer_monitores_df,
    leer_plazas_por_dia_df,
    leer_restricciones_df,
    leer_tipos_turno_df,
)
from ..io_excel.escritor import escribir_solucion
from ..io_excel.escritor import hacer_copia_seguridad
from ..io_excel.estructura import ErrorPlazas, guardar_plazas
from ..io_excel.lector import ErrorLecturaExcel, leer_datos
from ..io_excel.rejilla import (
    ErrorEdicionRejilla,
    guardar_cambios_rejilla,
    asignaciones_trabajo,
    descansos_asignados,
    info_dias,
    leer_rejilla,
)
from ..modelo.construir import ErrorModeloInconsistente, construir_modelo
from ..nombres import ErrorNombreNoReconocido
from ..resolver import resolver_modelo
from ..validar import validar_previa

RAIZ = Path(__file__).resolve().parents[2]


def _sanear(valor):
    if valor is None:
        return None
    if isinstance(valor, float) and pd.isna(valor):
        return None
    if isinstance(valor, np.floating):
        return None if np.isnan(valor) else float(valor)
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    return valor


def _filas_json(df: pd.DataFrame) -> list:
    return [{k: _sanear(v) for k, v in fila.items()} for fila in df.to_dict(orient="records")]


def _df_desde_peticion() -> pd.DataFrame:
    cuerpo = request.get_json(force=True) or {}
    return pd.DataFrame(cuerpo.get("filas", []))


def _error(mensaje: str, codigo: int = 400):
    return jsonify({"error": mensaje}), codigo


def _con_datos():
    """Devuelve (datos, ruta) o None si no hay Excel cargado (ya responde el error)."""
    datos = estado.datos_actuales()
    if datos is None:
        return None
    return datos, estado.ruta_actual()


_MENSAJE_EXCEL_ABIERTO = (
    "No se puede escribir en el Excel. Si lo tienes abierto en Excel, ciérralo y vuelve a intentarlo."
)
SOLVER_ALTERNATIVO = "appsi_highs"


def _generando() -> bool:
    trabajo = estado.get("trabajo")
    return bool(trabajo and trabajo["estado"] == "corriendo")


def _payload_rejilla(datos, ruta: str, rejilla: dict) -> dict:
    """Rejilla + todo lo que la pantalla necesita para validar al editar."""
    monitores = [
        {"nombre": m.nombre, "sexo": m.sexo, "grupo": m.grupo, "alias": rejilla["alias"].get(m.nombre, []),
         "descansa": bool(m.permite_descanso)}
        for m in sorted(datos.monitores.values(), key=lambda m: m.nombre.lower())
    ]
    return {
        "ruta": ruta,
        "dias": info_dias(datos),
        "desde": estado.desde(),
        "dia_inicio": datos.cfg.dia_inicio,
        "dia_fin": datos.cfg.dia_fin,
        "monitores": monitores,
        "disponibilidad": {
            nombre: {str(d): datos.disponibilidad[(nombre, d)] for d in datos.dias}
            for nombre in datos.monitores
        },
        "secciones": rejilla["secciones"],
    }


def _solver_disponible(nombre: str) -> bool:
    try:
        return bool(pyo.SolverFactory(nombre).available(exception_flag=False))
    except Exception:
        return False


def _terminar(trabajo: dict, estado_final: str, **campos) -> None:
    trabajo.update(campos)
    trabajo["fin"] = time.time()
    trabajo["estado"] = estado_final


def _ejecutar_generacion(trabajo: dict, ruta: str, desde: int, dos_fases: bool, hasta: int = None) -> None:
    """Valida, construye el modelo, resuelve y prepara la vista previa.

    Corre en un hilo aparte para que la pantalla pueda mostrar el progreso.
    No toca el Excel: solo deja una propuesta en `trabajo` (ver /aplicar).
    """
    try:
        try:
            datos = leer_datos(ruta, desde=desde, hasta=hasta)
        except (ErrorLecturaExcel, ErrorNombreNoReconocido, ValueError) as exc:
            mensaje = str(exc).replace(
                "Corrige la rejilla o baja DIA_REOPTIMIZACION.",
                "En la rejilla, la fila «Sin puesto» indica quién falta: colócalo en una casilla de ese día "
                "o elige un día de inicio anterior.",
            )
            _terminar(trabajo, "error", mensaje=mensaje)
            return

        informe = validar_previa(datos)
        trabajo["avisos"] = informe.avisos
        if informe.errores:
            _terminar(trabajo, "error_validacion", errores=informe.errores)
            return

        # El Excel puede pedir Gurobi (sin licencia/instalación en este equipo).
        solver = datos.cfg.solver
        aviso_solver = None
        if not _solver_disponible(solver) and solver != SOLVER_ALTERNATIVO:
            if not _solver_disponible(SOLVER_ALTERNATIVO):
                _terminar(trabajo, "error", mensaje=(
                    f"El solver '{solver}' no está disponible y tampoco '{SOLVER_ALTERNATIVO}'. "
                    "Instala highspy (pip install highspy)."))
                return
            aviso_solver = f"No se ha podido usar {solver} (no está instalado o su licencia no es válida): se ha usado HiGHS, un solver gratuito."
            datos.cfg = replace(datos.cfg, solver=SOLVER_ALTERNATIVO)

        trabajo["fase"] = "Construyendo el modelo…"
        try:
            modelo = construir_modelo(datos)
        except ErrorModeloInconsistente as exc:
            _terminar(trabajo, "error", mensaje=f"Error construyendo el modelo: {exc}")
            return

        trabajo["fase"] = f"Resolviendo con {datos.cfg.solver}…"
        try:
            solucion = resolver_modelo(modelo, datos, dos_fases=dos_fases)
        except Exception as exc:
            if datos.cfg.solver == SOLVER_ALTERNATIVO:
                raise
            # Típico: licencia de prueba de Gurobi (límite de 2000 variables).
            aviso_solver = f"No se ha podido usar {datos.cfg.solver} (licencia caducada o no válida): se ha usado HiGHS, un solver gratuito."
            datos.cfg = replace(datos.cfg, solver=SOLVER_ALTERNATIVO)
            trabajo["fase"] = f"Resolviendo con {SOLVER_ALTERNATIVO}…"
            modelo = construir_modelo(datos)
            solucion = resolver_modelo(modelo, datos, dos_fases=dos_fases)

        if solucion.estado == "infactible":
            _terminar(trabajo, "infactible", diagnostico=solucion.diagnostico)
            return
        if solucion.estado.startswith("sin_solucion"):
            _terminar(trabajo, "error", mensaje=solucion.estado, diagnostico=solucion.diagnostico)
            return

        trabajo["fase"] = "Preparando la vista previa…"
        directorio = tempfile.mkdtemp(prefix="turnos_previa_")
        try:
            ruta_previa = str(Path(directorio) / "previa.xlsx")
            escribir_solucion(ruta, datos, solucion, ruta_salida=ruta_previa)
            # La vista previa puede tener más filas (turnos que aceptan extras): se lee con su propio diseño.
            datos_previa = leer_datos(ruta_previa, desde=datos.dias[0])
            propuesta = leer_rejilla(ruta_previa, datos_previa)
        finally:
            shutil.rmtree(directorio, ignore_errors=True)

        estado.set("solucion", solucion)
        _terminar(
            trabajo, "listo", datos=datos, solucion=solucion, propuesta=propuesta,
            resumen={
                "estado": solucion.estado,
                "gap": solucion.gap,
                "tiempo_s": solucion.tiempo_s,
                "objetivo": solucion.objetivo,
                "total_falta": sum(solucion.falta.values()) if solucion.falta else 0,
                "solver": datos.cfg.solver,
                "aviso_solver": aviso_solver,
            },
        )
    except Exception as exc:  # el hilo nunca debe morir en silencio
        _terminar(trabajo, "error", mensaje=f"{type(exc).__name__}: {exc}")


def crear_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    estado.cargar(estado.ruta_actual())

    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.template_folder, "index.html")

    # ------------------------------------------------------------------
    # Carga del Excel / resumen general
    # ------------------------------------------------------------------
    @app.get("/api/estado")
    def api_estado():
        datos = estado.datos_actuales()
        if datos is None:
            return jsonify({
                "cargado": False,
                "ruta": estado.ruta_actual(),
                "error": estado.error_carga(),
            })
        return jsonify({
            "cargado": True,
            "ruta": estado.ruta_actual(),
            "dia_inicio": datos.cfg.dia_inicio,
            "dia_fin": datos.cfg.dia_fin,
            "dia_reoptimizacion": estado.desde(),
            "dias": datos.dias,
            "n_monitores": len(datos.monitores),
            "n_dependientes": len(datos.dependientes),
            "avisos": datos.avisos,
        })

    @app.post("/api/cargar")
    def api_cargar():
        cuerpo = request.get_json(force=True) or {}
        ruta = cuerpo.get("ruta") or estado.ruta_actual()
        desde = cuerpo.get("desde")
        ok = estado.cargar(ruta, desde=int(desde) if desde not in (None, "") else None)  # None: conserva el actual
        if not ok:
            return _error(estado.error_carga())
        return api_estado()

    # ------------------------------------------------------------------
    # Monitores
    # ------------------------------------------------------------------
    @app.get("/api/monitores")
    def api_monitores_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        return jsonify(_filas_json(leer_monitores_df(ruta)))

    @app.post("/api/monitores")
    def api_monitores_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        df = _df_desde_peticion()
        for col in ("PERMITE_DESCANSO", "PENALIZAR_DESCANSO"):
            if col in df.columns:
                df[col] = df[col].astype(int)
        avisos = guardar_monitores_df(ruta, df, datos.dias)
        estado.cargar(ruta)
        return jsonify({"avisos": avisos})

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------
    @app.get("/api/disponibilidad")
    def api_disponibilidad_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        return jsonify({
            "dias": datos.dias,
            "dias_info": info_dias(datos),
            "monitores": {
                m.nombre: {"sexo": m.sexo, "grupo": m.grupo, "descansa": bool(m.permite_descanso)}
                for m in datos.monitores.values()
            },
            "filas": _filas_json(leer_disponibilidad_df(ruta, datos.dias)),
            # Descansos que ya hay asignados en la rejilla (hoja TURNOS), por monitor.
            "descansos": descansos_asignados(ruta, datos),
            # Turnos y dependientes ya escritos en la rejilla, para avisar si se les quita la disponibilidad.
            "asignaciones": asignaciones_trabajo(ruta, datos),
        })

    @app.post("/api/disponibilidad")
    def api_disponibilidad_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        if _generando():
            return _error("Hay una generación en curso: espera a que termine para guardar.", 409)
        datos, ruta = ctx
        df = _df_desde_peticion()
        # Solo valen D (disponible), X (no viene) y R (descanso impuesto).
        malos = [
            f"{fila['NOMBRE']}, día {dia}: '{fila.get(str(dia))}'"
            for fila in df.to_dict(orient="records")
            for dia in datos.dias
            if str(fila.get(str(dia), "D")).strip().upper() not in ("D", "X", "R")
        ]
        if malos:
            return _error("Códigos no válidos (solo D, X o R):\n" + "\n".join(malos[:10]))
        try:
            hacer_copia_seguridad(ruta)
            guardar_disponibilidad_df(ruta, df, datos.dias)
        except PermissionError:
            return _error(_MENSAJE_EXCEL_ABIERTO, 409)
        estado.cargar(ruta)
        return jsonify({"ok": True, "filas": len(df)})

    # ------------------------------------------------------------------
    # Turnos (tipos + plazas por día + alta de turno nuevo)
    # ------------------------------------------------------------------
    @app.get("/api/tipos_turno")
    def api_tipos_turno_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        return jsonify(_filas_json(leer_tipos_turno_df(ruta)))

    @app.post("/api/tipos_turno")
    def api_tipos_turno_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        guardar_tipos_turno_df(ruta, _df_desde_peticion())
        estado.cargar(ruta)
        return jsonify({"ok": True})

    @app.get("/api/plazas_por_dia")
    def api_plazas_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        return jsonify({
            "dias": datos.dias,
            "filas": _filas_json(leer_plazas_por_dia_df(ruta, datos.dias)),
        })

    @app.post("/api/plazas_por_dia")
    def api_plazas_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        guardar_plazas_por_dia_df(ruta, _df_desde_peticion(), datos.dias)
        estado.cargar(ruta)
        return jsonify({"ok": True})

    @app.post("/api/tipos_turno/nuevo")
    def api_tipos_turno_nuevo():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        try:
            agregar_tipo_turno(
                ruta,
                cuerpo.get("nombre", ""),
                int(cuerpo.get("plazas", 0)),
                cuerpo.get("sexo_req", "-"),
                float(cuerpo.get("esfuerzo", 0)),
                datos.dias,
                estado.desde(),
            )
        except ValueError as exc:
            return _error(str(exc))
        estado.cargar(ruta)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Dependientes (+ alta de dependiente nuevo)
    # ------------------------------------------------------------------
    @app.get("/api/dependientes")
    def api_dependientes_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        return jsonify(_filas_json(leer_dependientes_df(ruta)))

    @app.post("/api/dependientes")
    def api_dependientes_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        guardar_dependientes_df(ruta, _df_desde_peticion())
        estado.cargar(ruta)
        return jsonify({"ok": True})

    @app.post("/api/dependientes/nuevo")
    def api_dependientes_nuevo():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        try:
            agregar_dependiente(
                ruta,
                cuerpo.get("acampado", ""),
                cuerpo.get("sexo_req", "-"),
                float(cuerpo.get("esfuerzo", 0)),
                datos.dias,
                estado.desde(),
            )
        except ValueError as exc:
            return _error(str(exc))
        estado.cargar(ruta)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Restricciones + parámetros de CONFIG
    # ------------------------------------------------------------------
    @app.get("/api/restricciones")
    def api_restricciones_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        return jsonify(_filas_json(leer_restricciones_df(ruta)))

    @app.post("/api/restricciones")
    def api_restricciones_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        guardar_restricciones_df(ruta, _df_desde_peticion())
        estado.cargar(ruta)
        return jsonify({"ok": True})

    @app.get("/api/config")
    def api_config_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, _ = ctx
        cfg = datos.cfg
        return jsonify({
            "SOLVER": cfg.solver,
            "TIME_LIMIT_S": cfg.time_limit_s,
            "MIP_GAP": cfg.mip_gap,
            "DIAS_DESCANSO_MINIMO": cfg.dias_descanso_minimo,
            "DIAS_VENTANA_DESCANSO": cfg.dias_ventana_descanso,
            "MAX_DIAS_POR_DEP": cfg.max_dias_por_dep,
            "W_FALTA": cfg.w_falta,
            "W_EQUIDAD": cfg.w_equidad,
            "W_DESCANSO_LIM": cfg.w_descanso_lim,
            "W_VARIEDAD": cfg.w_variedad,
            "W_REPETICION": cfg.w_repeticion,
            "W_FALTA_DESC": cfg.w_falta_desc,
        })

    @app.post("/api/config")
    def api_config_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        guardar_config_valores(ruta, cuerpo)
        estado.cargar(ruta)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------
    # Rejilla: lectura y edición celda a celda (cualquier día, también el pasado)
    # ------------------------------------------------------------------
    @app.get("/api/rejilla")
    def api_rejilla_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, ruta = ctx
        return jsonify(_payload_rejilla(datos, ruta, leer_rejilla(ruta, datos)))

    @app.post("/api/rejilla/guardar")
    def api_rejilla_guardar():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        if _generando():
            return _error("Hay una generación en curso: espera a que termine para guardar.", 409)
        datos, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        try:
            resultado = guardar_cambios_rejilla(ruta, datos, cuerpo.get("cambios", []))
        except ErrorEdicionRejilla as exc:
            return _error("No se ha guardado nada:\n" + "\n".join(f"- {e}" for e in exc.errores))
        except PermissionError:
            return _error(_MENSAJE_EXCEL_ABIERTO, 409)
        estado.cargar(ruta)
        return jsonify(resultado)

    # ------------------------------------------------------------------
    # Plazas por día: necesarias y "acepta hasta"
    # ------------------------------------------------------------------
    @app.get("/api/plazas")
    def api_plazas_dia_get():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, _ = ctx
        turnos = []
        for tt in sorted((t for t in datos.turnos.values() if t.fila_ini is not None), key=lambda t: t.fila_ini):
            turnos.append({
                "turno": tt.turno,
                "sexo_req": tt.sexo_req,
                "plazas": {str(d): int(datos.plazas.get((tt.turno, d), 0)) for d in datos.dias},
                "max": {str(d): datos.plazas_max.get((tt.turno, d)) for d in datos.dias},
            })
        presentes = {
            str(d): sum(1 for p in datos.dependientes if datos.asig_dependiente.get((p, d), None) is not None)
            for d in datos.dias
        }
        disponibles = {
            str(d): sum(1 for m in datos.monitores if datos.disponibilidad[(m, d)] in ("D", "R")) for d in datos.dias
        }
        finde = {
            str(d): sum(1 for m, mo in datos.monitores.items()
                        if not mo.permite_descanso and datos.disponibilidad[(m, d)] in ("D", "R"))
            for d in datos.dias
        }
        # Monitores que ya tienen sitio fijado a mano ese día (celdas amarillas, FIJACIONES o dependiente escrito).
        fijados, finde_fijados = {}, {}
        for d in datos.dias:
            nombres = {f.monitor for f in datos.fijaciones if f.dia == d and f.tipo == "OBLIGA"}
            nombres |= {v for (p, dd), v in datos.asig_dependiente.items() if dd == d and v}
            nombres = {m for m in nombres if m in datos.monitores and datos.disponibilidad[(m, d)] in ("D", "R")}
            fijados[str(d)] = len(nombres)
            finde_fijados[str(d)] = sum(1 for m in nombres if not datos.monitores[m].permite_descanso)
        return jsonify({"dias": info_dias(datos), "turnos": turnos, "dependientes": presentes,
                        "disponibles": disponibles, "finde": finde, "fijados": fijados,
                        "finde_fijados": finde_fijados})

    @app.post("/api/plazas")
    def api_plazas_dia_post():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        if _generando():
            return _error("Hay una generación en curso: espera a que termine.", 409)
        datos, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        try:
            resultado = guardar_plazas(ruta, datos, cuerpo.get("cambios", []), hacer_copia_seguridad)
        except ErrorPlazas as exc:
            return _error("No se ha guardado nada:\n" + "\n".join(f"- {e}" for e in exc.errores))
        except PermissionError:
            return _error(_MENSAJE_EXCEL_ABIERTO, 409)
        estado.cargar(ruta)
        return jsonify({**resultado, "filas_añadidas": resultado["filas_añadidas"]})

    @app.post("/api/desde")
    def api_desde():
        cuerpo = request.get_json(force=True) or {}
        try:
            estado.fijar_desde(int(cuerpo.get("dia")))
        except (TypeError, ValueError):
            return _error("Día no válido")
        return jsonify({"desde": estado.desde()})

    # ------------------------------------------------------------------
    # Generar con el optimizador (en segundo plano) -> propuesta -> aplicar
    # ------------------------------------------------------------------
    @app.post("/api/generar")
    def api_generar():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        cuerpo = request.get_json(force=True) or {}
        try:
            desde = int(cuerpo.get("desde"))
        except (TypeError, ValueError):
            return _error("Indica el día desde el que generar")
        try:
            hasta = int(cuerpo["hasta"]) if cuerpo.get("hasta") not in (None, "") else None
        except (TypeError, ValueError):
            return _error("El último día a generar no es válido")
        with estado.cerrojo:
            if _generando():
                return _error("Ya hay una generación en curso", 409)
            estado.fijar_desde(desde)
            trabajo = {
                "estado": "corriendo", "fase": "Leyendo el Excel…", "desde": estado.desde(), "hasta": hasta,
                "inicio": time.time(), "fin": None, "avisos": [], "errores": [],
            }
            estado.set("trabajo", trabajo)
        hilo = threading.Thread(
            target=_ejecutar_generacion,
            args=(trabajo, ruta, estado.desde(), bool(cuerpo.get("dos_fases")), hasta),
            daemon=True,
        )
        hilo.start()
        return jsonify({"ok": True}), 202

    @app.get("/api/generar/estado")
    def api_generar_estado():
        trabajo = estado.get("trabajo")
        if trabajo is None:
            return jsonify({"estado": "ninguno"})
        fin = trabajo["fin"] or time.time()
        publico = {k: trabajo.get(k) for k in (
            "estado", "fase", "desde", "hasta", "avisos", "errores", "mensaje", "diagnostico", "resumen")}
        publico["segundos"] = round(fin - trabajo["inicio"], 1)
        return jsonify(publico)

    @app.get("/api/generar/propuesta")
    def api_generar_propuesta():
        ctx = _con_datos()
        trabajo = estado.get("trabajo")
        if ctx is None or trabajo is None or trabajo["estado"] != "listo":
            return _error("No hay ninguna propuesta lista", 409)
        datos, ruta = ctx
        return jsonify(_payload_rejilla(datos, ruta, trabajo["propuesta"]))

    @app.post("/api/generar/aplicar")
    def api_generar_aplicar():
        ctx = _con_datos()
        trabajo = estado.get("trabajo")
        if ctx is None or trabajo is None or trabajo["estado"] != "listo":
            return _error("No hay ninguna propuesta lista para aplicar", 409)
        _, ruta = ctx
        try:
            # Copia de seguridad automática dentro de escribir_solucion.
            escribir_solucion(ruta, trabajo["datos"], trabajo["solucion"], dry_run=False)
            # Todo lo anterior a este día queda congelado también para la CLI.
            guardar_config_valores(ruta, {"DIA_REOPTIMIZACION": trabajo["desde"]})
        except PermissionError:
            return _error(_MENSAJE_EXCEL_ABIERTO, 409)
        except ValueError as exc:
            return _error(str(exc))
        solucion = trabajo["solucion"]
        estado.cargar(ruta, desde=trabajo["desde"])
        estado.set("solucion", solucion)  # para la pantalla Informe
        return jsonify({"ok": True})

    @app.post("/api/generar/descartar")
    def api_generar_descartar():
        with estado.cerrojo:
            if _generando():
                return _error("La generación sigue en curso", 409)
            estado.set("trabajo", None)
        return jsonify({"ok": True})

    @app.get("/api/descargar")
    def api_descargar():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        _, ruta = ctx
        return send_file(ruta, as_attachment=True, download_name=Path(ruta).name)

    # ------------------------------------------------------------------
    # Informe
    # ------------------------------------------------------------------
    @app.get("/api/informe")
    def api_informe():
        ctx = _con_datos()
        if ctx is None:
            return _error("No hay Excel cargado")
        datos, _ = ctx
        solucion = estado.get("solucion")
        if solucion is None or solucion.estado == "infactible":
            return _error("Optimiza primero para ver el informe", 409)

        esfuerzo = {}
        for mo in datos.monitores:
            dp = datos.dias_presente.get(mo, 0)
            if dp == 0:
                continue
            carga = sum(datos.turnos[t].esfuerzo for (m2, t, d), v in solucion.x.items() if m2 == mo and v == 1)
            carga += sum(datos.dependientes[p].esfuerzo for (m2, p, d), v in solucion.y.items() if m2 == mo and v == 1)
            esfuerzo[mo] = carga / dp

        descansos = {}
        for (mo, d), v in solucion.r.items():
            if v == 1:
                descansos[mo] = descansos.get(mo, 0) + 1

        dias_dep_monitor = {}
        dias_dep_acampado = {}
        for (mo, p, d), v in solucion.y.items():
            if v == 1:
                dias_dep_monitor[mo] = dias_dep_monitor.get(mo, 0) + 1
                dias_dep_acampado[p] = dias_dep_acampado.get(p, 0) + 1

        falta = {f"{t} (día {d})": v for (t, d), v in solucion.falta.items() if v > 1e-6}

        def _serie(d, dec=2):
            return [{"label": k, "valor": round(float(v), dec)} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

        return jsonify({
            "esfuerzo": _serie(esfuerzo),
            "descansos": _serie(descansos, 0),
            "dias_dependiente_monitor": _serie(dias_dep_monitor, 0),
            "dias_dependiente_acampado": _serie(dias_dep_acampado, 0),
            "falta": _serie(falta),
        })

    return app


def main():
    app = crear_app()
    print("Interfaz web en http://127.0.0.1:5000  (Ctrl+C para salir)")
    app.run(host="127.0.0.1", port=5000, debug=False)
