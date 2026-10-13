"""Interfaz de línea de comandos de catalogo-match."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack, suppress
from pathlib import Path

from . import __version__
from .config import PLANTILLA_TOML, ConfigMatcher
from .datos import cargar_lote, cargar_maestro, cargar_sustitutos, cargar_verdad

# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------


def _opciones_backend(parser: argparse.ArgumentParser, para_indice: bool = False) -> None:
    parser.add_argument(
        "--backend",
        default="gemma" if para_indice else None,
        choices=["hash", "gemma"],
        help="Backend de embeddings. 'hash' es offline/determinista (pruebas y CI).",
    )
    parser.add_argument(
        "--modelo", default=None, help="ID o ruta del modelo (default: google/embeddinggemma-2)"
    )
    parser.add_argument(
        "--modalidades", default=None, choices=["texto", "texto+imagen"], help="Encoders a cargar."
    )
    parser.add_argument("--truncar", type=int, default=None, choices=[128, 256, 512, 768], help="MRL")
    parser.add_argument(
        "--sin-prefijos", action="store_true", help="No usar los prefijos de tarea de EmbeddingGemma 2."
    )


def _config_desde_args(args: argparse.Namespace) -> ConfigMatcher:
    cfg = ConfigMatcher.desde_toml(args.config) if getattr(args, "config", None) else ConfigMatcher()
    cambios: dict = {}
    if getattr(args, "formato_doc", None):
        cambios["formato_documento"] = args.formato_doc
    if getattr(args, "truncar", None):
        cambios["truncar_a"] = args.truncar
    if getattr(args, "sin_prefijos", False):
        cambios["usar_prefijos"] = False
    return cfg.con(**cambios) if cambios else cfg


def _crear_backend_para_indices(args: argparse.Namespace):
    from .backends import crear_backend

    opciones: dict = {}
    if args.backend == "gemma":
        if args.modelo:
            opciones["modelo"] = args.modelo
        if args.modalidades:
            opciones["modalidades"] = tuple(args.modalidades.split("+"))
        if args.truncar:
            opciones["truncar_a"] = args.truncar
        if args.sin_prefijos:
            opciones["usar_prefijos"] = False
    return crear_backend(args.backend, **opciones)


def _overrides_backend(args: argparse.Namespace) -> dict:
    overrides: dict = {}
    if getattr(args, "backend", None):
        overrides["nombre"] = args.backend
    if getattr(args, "modelo", None):
        overrides["modelo"] = args.modelo
    if getattr(args, "modalidades", None):
        overrides["modalidades"] = tuple(args.modalidades.split("+"))
    if getattr(args, "truncar", None):
        overrides["truncar_a"] = args.truncar
    if getattr(args, "sin_prefijos", False):
        overrides["usar_prefijos"] = False
    return overrides


def _pct(valor) -> str:
    return "—" if not isinstance(valor, float) else f"{valor * 100:.1f} %"


def _sustitutos_curados(args: argparse.Namespace):
    ruta = getattr(args, "sustitutos_curados", None)
    return cargar_sustitutos(ruta) if ruta else []


def _imprimir_resultado(resultado, detalle: bool = True) -> None:
    marca_decision = {"aceptado": "OK", "revisar": "REV", "no_se": "??"}[resultado.decision]
    puntaje = resultado.mejor.puntaje if resultado.mejor else 0.0
    texto = resultado.consulta.texto.replace("\n", " ⏎ ")[:78]
    print(f"[{marca_decision}] {resultado.consulta.id_fila}  ({puntaje:.3f})  «{texto}»")
    if resultado.decision == "no_se":
        print("      → no sé (no hay candidato suficientemente bueno)")
    for pos, candidato in enumerate(resultado.candidatos, start=1):
        s = candidato.sku
        extra = []
        if candidato.motivos:
            extra.append(", ".join(candidato.motivos))
        if s.agotado:
            extra.append("AGOTADO")
        linea = (
            f"   {pos}) {s.sku:<14} {candidato.puntaje:.3f}  {s.nombre} | {s.marca} | {s.presentacion}"
        )
        if extra:
            linea += f"   [{'; '.join(extra)}]"
        print(linea)
        if detalle:
            print(
                f"      emb={candidato.puntaje_embedding:.3f} "
                f"lex={candidato.puntaje_lexico:.3f} "
                f"cant={candidato.puntaje_cantidad if candidato.puntaje_cantidad is not None else '—'}"
            )
    for sustituto in resultado.sustitutos:
        print(
            f"   ↳ sustituto: {sustituto.sku.sku:<14} {sustituto.puntaje:.3f}  "
            f"{sustituto.sku.nombre} | {sustituto.sku.presentacion}   ({sustituto.motivo})"
        )


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def _cmd_info(args: argparse.Namespace) -> int:
    import platform

    from .backends.gemma import EmbeddorGemma

    info = {
        "catalogo_match": __version__,
        "python": sys.version.split()[0],
        "plataforma": platform.platform(),
        "entorno_embeddings": EmbeddorGemma.revisar_entorno(),
        "modelo_solicitado": args.modelo,
        "modelo_local": EmbeddorGemma.modelo_local(args.modelo),
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))
    if not info["modelo_local"]:
        print(
            "\nEl modelo aún no está en caché local. Descárgalo con:\n"
            "  python -c \"from huggingface_hub import snapshot_download; "
            f"snapshot_download('{args.modelo}')\"",
            file=sys.stderr,
        )
    return 0


def _cmd_generar_datos(args: argparse.Namespace) -> int:
    import subprocess

    script = Path("tools/generar_datos_sinteticos.py")
    if not script.exists():
        print(f"error: no existe {script}", file=sys.stderr)
        return 1
    comando = [sys.executable, str(script), "--salida", args.salida]
    if args.semilla:
        comando += ["--semilla", str(args.semilla)]
    return subprocess.run(comando, check=False).returncode


def _cmd_indexar(args: argparse.Namespace) -> int:
    import time

    from .indice import construir_indice

    cfg = _config_desde_args(args)
    if args.con_imagenes and (args.modalidades or "texto") != "texto+imagen":
        print(
            "error: --con-imagenes requiere --modalidades texto+imagen (el encoder de visión "
            "debe estar cargado).",
            file=sys.stderr,
        )
        return 1
    skus = cargar_maestro(args.maestro)
    print(f"[indexar] {len(skus)} SKUs del maestro {args.maestro}")
    embedder = _crear_backend_para_indices(args)
    inicio = time.perf_counter()
    indice = construir_indice(skus, embedder, cfg, con_imagenes=args.con_imagenes)
    indice.guardar(args.salida)
    segundos = time.perf_counter() - inicio
    print(
        f"[indexar] listo: {indice.n} vectores de {indice.dim}d "
        f"({segundos:.1f} s) | backend: {indice.huella} | salida: {args.salida}"
    )
    return 0


def _cmd_emparejar(args: argparse.Namespace) -> int:
    from .emparejador import emparejador_desde_indice

    cfg = _config_desde_args(args)
    emparejador = emparejador_desde_indice(
        args.indice, cfg, _sustitutos_curados(args), _overrides_backend(args)
    )
    consultas = cargar_lote(args.lote)
    print(
        f"[emparejar] {len(consultas)} consultas | índice: {emparejador.indice.n} SKUs "
        f"| backend: {emparejador.indice.huella}"
    )

    conteos = {"aceptado": 0, "revisar": 0, "no_se": 0}
    with ExitStack() as pila:
        salida = (
            pila.enter_context(Path(args.salida).open("w", encoding="utf-8"))
            if args.salida
            else None
        )
        for pos, consulta in enumerate(consultas):
            resultado = emparejador.emparejar(
                consulta, top=args.top, con_sustitutos=not args.sin_sustitutos
            )
            conteos[resultado.decision] += 1
            if pos < args.mostrar:
                _imprimir_resultado(resultado, detalle=args.detalle)
            if salida:
                salida.write(json.dumps(resultado.como_dict(), ensure_ascii=False) + "\n")

    total = max(len(consultas), 1)
    print(
        f"[emparejar] aceptados: {conteos['aceptado']} ({conteos['aceptado'] / total:.0%}) | "
        f"revisar: {conteos['revisar']} | no sé: {conteos['no_se']}"
    )
    if args.salida:
        print(f"[emparejar] resultados JSONL: {args.salida}")
    return 0


def _cmd_evaluar(args: argparse.Namespace) -> int:
    from .emparejador import emparejador_desde_indice
    from .evaluacion import evaluar

    if not args.verdad:
        print("error: falta --verdad (CSV id_fila,sku_correcto)", file=sys.stderr)
        return 1
    cfg = _config_desde_args(args)
    emparejador = emparejador_desde_indice(
        args.indice, cfg, _sustitutos_curados(args), _overrides_backend(args)
    )
    consultas = cargar_lote(args.lote)
    verdad = cargar_verdad(args.verdad)
    print(
        f"[evaluar] {len(consultas)} consultas | {emparejador.indice.n} SKUs "
        f"| backend: {emparejador.indice.huella}"
    )
    informe = evaluar(
        emparejador,
        consultas,
        verdad,
        con_baseline=not args.sin_baseline,
        calibrar=args.calibrar,
        ejemplos_error=args.ejemplos,
        pares_salida=args.pares_salida,
    )
    informe.escribir_markdown(args.informe)
    if args.json_salida:
        Path(args.json_salida).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_salida).write_text(
            json.dumps(informe.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    m = informe.metricas
    print("[evaluar] resultados (top-1 / top-3 sobre filas con match real):")
    for clave in ("top1", "top3", "mrr", "cobertura", "precision_aceptado", "tasa_no_se", "sin_match_ok"):
        valor = m.get(clave)
        if valor is None:
            continue
        print(f"   {clave:<20}: {valor * 100:6.1f} %")
    if informe.baseline:
        print(
            f"   baseline difuso     : {informe.baseline['difuso_top1'] * 100:6.1f} % (top-1)"
        )
    cortes = informe.cortes or {}
    if cortes.get("n_sin_barras"):
        print(
            f"   top1 sin EAN        : {_pct(cortes.get('top1_sin_barras')):>8} "
            f"({cortes.get('n_sin_barras')} filas; "
            f"{cortes.get('n_resueltas_por_barras')} resueltas por código de barras)"
        )
        print(
            f"   error presentación  : {cortes.get('errores_presentacion')} "
            f"({_pct(cortes.get('tasa_errores_presentacion'))}); "
            f"aceptados con presentación incorrecta: {cortes.get('presentacion_incorrecta_aceptada')}"
        )
    if informe.calibracion and "umbral_alto_sugerido" in informe.calibracion:
        print(
            f"   umbral sugerido     : alto={informe.calibracion['umbral_alto_sugerido']:.2f} "
            f"(precisión {informe.calibracion['precision_en_aceptados'] * 100:.1f} % "
            f"en {informe.calibracion['aceptados_en_evaluacion']} aceptados)"
        )
    print(f"[evaluar] informe: {args.informe}")
    if args.pares_salida:
        print(f"[evaluar] pares de entrenamiento exportados: {args.pares_salida}")
    return 0


def _cmd_servir(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print(
            "error: falta el extra de API. Instala con:\n  pip install -e '.[api]'",
            file=sys.stderr,
        )
        return 1
    host = args.host
    if host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get(
        "CATALOGO_MATCH_TOKEN", ""
    ).strip():
        print(
            f"error: para publicar la API fuera de loopback (--host {host}) define "
            "CATALOGO_MATCH_TOKEN.\n"
            "       La API no trae autenticación propia; si además aceptas rutas locales de\n"
            "       imagen, limita CATALOGO_MATCH_DIR_IMAGENES a una carpeta dedicada.",
            file=sys.stderr,
        )
        return 1

    from .api import crear_app

    cfg = ConfigMatcher.desde_toml(args.config) if args.config else None
    curados = _sustitutos_curados(args)
    app = crear_app(
        args.indice, cfg=cfg, curados=curados, overrides_backend=_overrides_backend(args)
    )
    import uvicorn

    print(f"[servir] escuchando en http://{host}:{args.port} | índice: {args.indice}")
    uvicorn.run(app, host=host, port=args.port)
    return 0


def _cmd_plantilla_config(_args: argparse.Namespace) -> int:
    print(PLANTILLA_TOML)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalogo-match",
        description=(
            "Emparejador local de catálogo de productos: texto/imagen de proveedor → "
            "top-3 SKUs del maestro, con puntaje, abstención y sustitución. "
            "Todo el procesamiento ocurre en el servidor local."
        ),
    )
    parser.add_argument("--version", action="version", version=f"catalogo-match {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("info", help="Diagnóstico del entorno y del modelo.")
    p.add_argument("--modelo", default="google/embeddinggemma-2")
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("generar-datos", help="Genera el set sintético (maestro, lote, verdad, sustitutos).")
    p.add_argument("--salida", default="data/sintetico")
    p.add_argument("--semilla", type=int, default=2026)
    p.set_defaults(func=_cmd_generar_datos)

    p = sub.add_parser("indexar", help="Vectoriza el maestro y guarda el índice.")
    p.add_argument("--maestro", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument(
        "--con-imagenes",
        action="store_true",
        help="Intercalar imágenes del maestro (texto+imagen).",
    )
    p.add_argument("--formato-doc", default=None, choices=["titulo_texto", "plano"])
    p.add_argument("--config", default=None)
    _opciones_backend(p, para_indice=True)
    p.set_defaults(func=_cmd_indexar)

    p = sub.add_parser("emparejar", help="Empareja un lote sucio contra el índice.")
    p.add_argument("--indice", required=True)
    p.add_argument("--lote", required=True)
    p.add_argument("--salida", default=None, help="Escribe resultados en JSONL.")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--sin-sustitutos", action="store_true")
    p.add_argument("--sustitutos-curados", default=None, help="CSV opcional de pares curados.")
    p.add_argument("--mostrar", type=int, default=5, help="Cuántos resultados imprimir en consola.")
    p.add_argument("--sin-detalle", dest="detalle", action="store_false", default=True)
    p.add_argument("--config", default=None)
    _opciones_backend(p)
    p.set_defaults(func=_cmd_emparejar)

    p = sub.add_parser("evaluar", help="Mide el emparejador contra un set etiquetado.")
    p.add_argument("--indice", required=True)
    p.add_argument("--lote", required=True)
    p.add_argument("--verdad", required=True, help="CSV id_fila,sku_correcto (vacío = debe abstenerse).")
    p.add_argument("--informe", default="reports/informe_eval.md")
    p.add_argument("--json-salida", default=None)
    p.add_argument("--pares-salida", default=None, help="Exporta tripletas para fine-tuning (JSONL).")
    p.add_argument("--calibrar", action="store_true", help="Sugiere umbrales según la precisión objetivo.")
    p.add_argument("--sin-baseline", action="store_true")
    p.add_argument("--ejemplos", type=int, default=8, help="Errores de ejemplo en el informe.")
    p.add_argument("--sustitutos-curados", default=None)
    p.add_argument("--config", default=None)
    _opciones_backend(p)
    p.set_defaults(func=_cmd_evaluar)

    p = sub.add_parser("servir", help="Levanta la API HTTP local (requiere extra [api]).")
    p.add_argument("--indice", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--sustitutos-curados", default=None)
    p.add_argument("--config", default=None)
    _opciones_backend(p)
    p.set_defaults(func=_cmd_servir)

    p = sub.add_parser("plantilla-config", help="Imprime una plantilla de configuración TOML.")
    p.set_defaults(func=_cmd_plantilla_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Consolas Windows suelen usar cp1252: evita crashes y mojibake con acentos.
    for flujo in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError):  # pragma: no cover
            flujo.reconfigure(encoding="utf-8", errors="replace")
    args = _construir_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as e:  # noqa: BLE001
        if os.environ.get("CATALOGO_MATCH_DEBUG"):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1
