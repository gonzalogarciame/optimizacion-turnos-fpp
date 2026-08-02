"""CLI: python -m turnos <comando> [opciones]

Comandos:
    validar     Lee el Excel y muestra el informe de validación previa,
                sin resolver nada.
    optimizar   Lee, valida, resuelve y escribe la solución de vuelta al
                Excel (o a un fichero nuevo con --salida / --dry-run).

Ejemplos:
    python -m turnos validar --excel datos/2026-quincena2-18al30jul/turnos.xlsx
    python -m turnos optimizar --excel datos/2026-quincena2-18al30jul/turnos.xlsx --desde 24
    python -m turnos optimizar --excel datos/2026-quincena2-18al30jul/turnos.xlsx --dry-run
"""
from __future__ import annotations

import argparse
import sys

from .io_excel.escritor import escribir_solucion
from .io_excel.lector import ErrorLecturaExcel, leer_datos
from .modelo.construir import ErrorModeloInconsistente, construir_modelo
from .nombres import ErrorNombreNoReconocido
from .resolver import resolver_modelo
from .validar import validar_previa


def _leer_con_manejo_errores(ruta: str, desde):
    try:
        return leer_datos(ruta, desde=desde)
    except (ErrorLecturaExcel, ErrorNombreNoReconocido, ValueError) as exc:
        print(f"ERROR leyendo '{ruta}': {exc}", file=sys.stderr)
        sys.exit(1)


def comando_validar(args) -> None:
    datos = _leer_con_manejo_errores(args.excel, args.desde)
    informe = validar_previa(datos)
    print(f"DIA_REOPTIMIZACION efectivo: {datos.cfg.dia_reoptimizacion}")
    print(informe.texto())
    if not informe.ok:
        sys.exit(2)


def comando_optimizar(args) -> None:
    datos = _leer_con_manejo_errores(args.excel, args.desde)

    informe = validar_previa(datos)
    print(f"DIA_REOPTIMIZACION efectivo: {datos.cfg.dia_reoptimizacion}")
    print(informe.texto())
    if not informe.ok and not args.forzar:
        print(
            "\nHay errores de validación. Corrige el Excel o usa --forzar para "
            "intentar resolver de todos modos.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        modelo = construir_modelo(datos)
    except ErrorModeloInconsistente as exc:
        print(f"ERROR construyendo el modelo: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Restricciones aplicadas: {', '.join(modelo.restricciones_aplicadas)}")
    print(f"Variables: x={len(modelo.x_idx)}  y={len(modelo.y_idx)}  r={len(modelo.r_idx)}  z={len(modelo.z_idx)}")

    solucion = resolver_modelo(modelo, datos, dos_fases=args.dos_fases)

    print(f"\nEstado del solver: {solucion.estado}  (tiempo={solucion.tiempo_s:.1f}s)")
    if solucion.gap is not None:
        print(f"Gap: {solucion.gap:.2%}")
    if solucion.objetivo is not None:
        print(f"Objetivo: {solucion.objetivo:.2f}")

    if solucion.estado == "infactible":
        print("\nEl modelo es INFACTIBLE. Diagnóstico (IIS):", file=sys.stderr)
        for linea in solucion.diagnostico:
            print(f"  - {linea}", file=sys.stderr)
        sys.exit(3)

    if solucion.falta:
        total_falta = sum(solucion.falta.values())
        if total_falta > 1e-6:
            print(f"\nAVISO: quedan {total_falta:.0f} plazas sin cubrir en total:")
            for (t, d), v in sorted(solucion.falta.items()):
                if v > 1e-6:
                    print(f"  - {t} día {d}: faltan {v:.0f}")

    ruta_salida = escribir_solucion(
        args.excel, datos, solucion, ruta_salida=args.salida, dry_run=args.dry_run
    )
    print(f"\nSolución escrita en: {ruta_salida}")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m turnos", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    for nombre, fn in (("validar", comando_validar), ("optimizar", comando_optimizar)):
        p = sub.add_parser(nombre)
        p.add_argument("--excel", required=True, help="Ruta al Excel del campamento (p. ej. datos/<campamento>/turnos.xlsx)")
        p.add_argument(
            "--desde", type=int, default=None,
            help="Día desde el que re-optimizar (sobrescribe DIA_REOPTIMIZACION de CONFIG)",
        )
        p.set_defaults(func=fn)

    # Opciones específicas de 'optimizar'
    parser_optimizar = sub.choices["optimizar"]
    parser_optimizar.add_argument("--salida", default=None, help="Ruta de salida (por defecto, sobrescribe --excel)")
    parser_optimizar.add_argument("--dry-run", action="store_true", help="No sobrescribe: escribe en un fichero *_DRYRUN")
    parser_optimizar.add_argument("--dos-fases", action="store_true", help="Resuelve la equidad en dos fases (ver r16_equidad_esfuerzo.py)")
    parser_optimizar.add_argument("--forzar", action="store_true", help="Intenta resolver aunque la validación previa encuentre errores")

    return parser


def main(argv=None) -> None:
    parser = construir_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
