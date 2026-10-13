"""Evaluación del emparejador: métricas, baseline difuso, calibración e informe."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .emparejador import Emparejador
from .modelos import SKU, Consulta, Resultado
from .normaliza import normalizar

# ---------------------------------------------------------------------------
# Estructuras
# ---------------------------------------------------------------------------


@dataclass
class FilaEvaluada:
    consulta: Consulta
    verdad: str  # '' = no existe match (hay que abstenerse)
    resultado: Resultado

    @property
    def sku_top1(self) -> str:
        mejor = self.resultado.mejor
        return mejor.sku.sku if mejor else ""

    @property
    def correcto_top1(self) -> bool:
        return bool(self.verdad) and self.sku_top1 == self.verdad

    @property
    def rank_correcto(self) -> int | None:
        if not self.verdad:
            return None
        for pos, candidato in enumerate(self.resultado.candidatos, start=1):
            if candidato.sku.sku == self.verdad:
                return pos
        return None


@dataclass
class InformeEvaluacion:
    metricas: dict
    por_dificultad: dict
    por_fuente: dict
    baseline: dict
    sustitutos: dict
    ejemplos_error: list[dict]
    calibracion: dict | None
    backend: dict
    config: dict
    n_consultas: int
    n_maestro: int
    segundos: float
    cortes: dict = field(default_factory=dict)
    fecha: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def a_dict(self) -> dict:
        return {
            "fecha": self.fecha,
            "n_consultas": self.n_consultas,
            "n_maestro": self.n_maestro,
            "segundos": self.segundos,
            "backend": self.backend,
            "config": self.config,
            "metricas": self.metricas,
            "por_dificultad": self.por_dificultad,
            "por_fuente": self.por_fuente,
            "baseline": self.baseline,
            "sustitutos": self.sustitutos,
            "calibracion": self.calibracion,
            "ejemplos_error": self.ejemplos_error,
            "cortes": self.cortes,
        }

    # -- informe markdown ----------------------------------------------------

    def escribir_markdown(self, ruta: str | Path) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        lineas: list[str] = []
        a = lineas.append

        a("# Informe de evaluación — catalogo-match")
        a("")
        a(f"- Fecha (UTC): {self.fecha}")
        a(f"- Consultas evaluadas: {self.n_consultas} | SKUs en el maestro: {self.n_maestro}")
        a(f"- Backend: `{self.backend.get('huella', '?')}` ({self.backend.get('nombre', '?')})")
        a(f"- Tiempo total de emparejamiento: {self.segundos:.1f} s")
        a("")

        a("## Resultados principales")
        a("")
        a("| Métrica | Valor |")
        a("|---|---|")
        etiquetas = {
            "top1": "Top-1 correcto (solo filas con match real)",
            "top3": "Top-3 contiene el correcto",
            "mrr": "MRR (recíproco del rango)",
            "cobertura": "Cobertura (1 - tasa de 'no sé')",
            "tasa_no_se": "Se abstuvo ('no sé')",
            "precision_aceptado": "Precisión de lo aceptado automáticamente",
            "abstencion_falsa": "Abstención falsa (tenía match y dijo 'no sé')",
            "sin_match_ok": "Sin match real y se abstuvo (correcto)",
            "sin_match_aceptado": "Sin match real y aun así aceptó (riesgo)",
        }
        for clave, etiqueta in etiquetas.items():
            valor = self.metricas.get(clave)
            a(f"| {etiqueta} | {_formato(valor)} |")
        a("")

        if self.por_dificultad:
            a("## Por dificultad del lote")
            a("")
            a("| Dificultad | n | Top-1 | Top-3 | Cobertura | Precisión aceptado |")
            a("|---|---|---|---|---|---|")
            for clave in sorted(self.por_dificultad):
                d = self.por_dificultad[clave]
                a(
                    f"| {clave or '(sin etiqueta)'} | {d['n']} | {_formato(d['top1'])} | "
                    f"{_formato(d['top3'])} | {_formato(d['cobertura'])} | "
                    f"{_formato(d['precision_aceptado'])} |"
                )
            a("")

        if self.por_fuente:
            a("## Por fuente")
            a("")
            a("| Fuente | n | Top-1 | Top-3 | Cobertura |")
            a("|---|---|---|---|---|")
            for clave in sorted(self.por_fuente):
                d = self.por_fuente[clave]
                a(
                    f"| {clave or '(sin etiqueta)'} | {d['n']} | {_formato(d['top1'])} | "
                    f"{_formato(d['top3'])} | {_formato(d['cobertura'])} |"
                )
            a("")

        if self.baseline:
            a("## Línea base (comparación)")
            a("")
            a("| Enfoque | Top-1 | Top-3 |")
            a("|---|---|---|")
            d1 = _formato(self.baseline.get("difuso_top1"))
            d3 = _formato(self.baseline.get("difuso_top3"))
            a(f"| Difuso clásico (rapidfuzz token_set_ratio, sin modelo) | {d1} | {d3} |")
            a(
                f"| catalogo-match ({self.backend.get('nombre', '?')}) | "
                f"{_formato(self.metricas.get('top1'))} | {_formato(self.metricas.get('top3'))} |"
            )
            a("")

        if self.cortes:
            a("## Cortes honestos (qué mide cada cosa)")
            a("")
            c = self.cortes or {}
            a("| Corte | Valor |")
            a("|---|---|")
            a(
                f"| Filas resueltas por el atajo de código de barras | "
                f"{c.get('n_resueltas_por_barras', 0)} de {c.get('n_total', 0)} |"
            )
            a(f"| Top-1 sin esas filas | {_formato(c.get('top1_sin_barras'))} |")
            a(f"| Top-3 sin esas filas | {_formato(c.get('top3_sin_barras'))} |")
            precision_sin = _formato(c.get("precision_aceptado_sin_barras"))
            a(f"| Precisión de aceptados sin esas filas | {precision_sin} |")
            a(
                f"| Errores de presentación (misma línea, envase distinto) | "
                f"{c.get('errores_presentacion', 0)} de {c.get('n_con_verdad', 0)} "
                f"({_formato(c.get('tasa_errores_presentacion'))}) |"
            )
            a(
                f"| Presentación incorrecta aceptada automáticamente | "
                f"{c.get('presentacion_incorrecta_aceptada', 0)} "
                f"({_formato(c.get('tasa_presentacion_aceptada'))}) |"
            )
            a(
                f"| Sin match real aceptados automáticamente | "
                f"{_formato(self.metricas.get('sin_match_aceptado'))} |"
            )
            a("")

        if self.sustitutos:
            a("## Sustitutos (SKUs agotados)")
            a("")
            a("| Métrica | Valor |")
            a("|---|---|")
            a(f"| Filas cuyo SKU correcto está agotado | {self.sustitutos.get('n_agotados', 0)} |")
            propuesto = _formato(self.sustitutos.get("tasa_propuesto"))
            a(f"| Se propuso al menos un sustituto | {propuesto} |")
            a(
                "| Sustituto de la misma categoría (proxy) | "
                + _formato(self.sustitutos.get("tasa_misma_categoria"))
                + " |"
            )
            a(
                "| Sustituto de la misma marca (proxy) | "
                + _formato(self.sustitutos.get("tasa_misma_marca"))
                + " |"
            )
            a("")
            a("> Proxy automático: en producción valida una muestra con criterio humano.")
            a("")

        if self.calibracion:
            a("## Calibración sugerida")
            a("")
            for clave, valor in self.calibracion.items():
                a(f"- {clave}: {valor}")
            a("")

        if self.ejemplos_error:
            a("## Errores de ejemplo (top-1 incorrecto)")
            a("")
            a("| Consulta | Verdad | Top-1 propuesto | Puntaje | Decisión |")
            a("|---|---|---|---|---|")
            for ejemplo in self.ejemplos_error:
                consulta_txt = ejemplo["consulta"].replace("|", "/").replace("\n", " ")[:70]
                a(
                    f"| {consulta_txt} | {ejemplo['verdad']} | {ejemplo['predicho']} | "
                    f"{ejemplo['puntaje']:.3f} | {ejemplo['decision']} |"
                )
            a("")

        a("---")
        a("")
        a("Los números de este informe corresponden al backend indicado arriba.")
        if self.backend.get("nombre") == "hash":
            a("El backend `hash` es un sustituto offline determinista para pruebas y CI: no")
            a("representa la calidad de EmbeddingGemma 2. Para números reales usa `--backend gemma`.")
        else:
            a("Los números corresponden al set evaluado y al backend indicado arriba: miden el")
            a("pipeline, no el techo del modelo. Conviene repetir la evaluación con un lote")
            a("etiquetado propio antes de fijar umbrales de producción.")
        a("")
        ruta.write_text("\n".join(lineas), encoding="utf-8")
        return ruta


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def _formato(valor) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float):
        return f"{valor * 100:.1f} %"
    return str(valor)


def _metricas_de(filas: list[FilaEvaluada]) -> dict:
    total = len(filas)
    if not total:
        return {}
    con_verdad = [f for f in filas if f.verdad]
    sin_verdad = [f for f in filas if not f.verdad]
    aceptadas = [f for f in filas if f.resultado.decision == "aceptado"]
    aceptadas_con_verdad = [f for f in aceptadas if f.verdad]
    no_se = [f for f in filas if f.resultado.decision == "no_se"]

    top1 = (
        sum(1 for f in con_verdad if f.correcto_top1) / len(con_verdad) if con_verdad else None
    )
    top3 = (
        sum(1 for f in con_verdad if (f.rank_correcto or 99) <= 3) / len(con_verdad)
        if con_verdad
        else None
    )
    mrr = (
        sum(1.0 / f.rank_correcto for f in con_verdad if f.rank_correcto) / len(con_verdad)
        if con_verdad
        else None
    )
    precision_aceptado = (
        sum(1 for f in aceptadas_con_verdad if f.correcto_top1) / len(aceptadas_con_verdad)
        if aceptadas_con_verdad
        else None
    )
    abstencion_falsa = (
        sum(1 for f in con_verdad if f.resultado.decision == "no_se") / len(con_verdad)
        if con_verdad
        else None
    )
    sin_match_ok = (
        sum(1 for f in sin_verdad if f.resultado.decision == "no_se") / len(sin_verdad)
        if sin_verdad
        else None
    )
    sin_match_aceptado = (
        sum(1 for f in sin_verdad if f.resultado.decision == "aceptado") / len(sin_verdad)
        if sin_verdad
        else None
    )
    return {
        "n": total,
        "top1": top1,
        "top3": top3,
        "mrr": mrr,
        "cobertura": 1.0 - len(no_se) / total,
        "tasa_no_se": len(no_se) / total,
        "precision_aceptado": precision_aceptado,
        "abstencion_falsa": abstencion_falsa,
        "sin_match_ok": sin_match_ok,
        "sin_match_aceptado": sin_match_aceptado,
    }


def _agrupar(filas: list[FilaEvaluada], clave) -> dict:
    grupos: dict[str, list[FilaEvaluada]] = {}
    for fila in filas:
        valor = clave(fila) or ""
        grupos.setdefault(valor, []).append(fila)
    return {k: _metricas_de(v) for k, v in grupos.items()}


def _cortes_honestos(filas: list[FilaEvaluada], skus_por_id: dict[str, SKU]) -> dict:
    """Cortes que evitan inflar la lectura del informe.

    - Excluye las filas que resolvió el atajo de código de barras (puntaje forzado):
      esas no miden al modelo.
    - Cuenta los errores de presentación (mismo producto de la misma línea, envase
      distinto: 900 g vs 1 kg), que son el error caro de automatizar.
    """

    def linea(sku_id: str) -> tuple[str, str] | None:
        sku = skus_por_id.get(sku_id)
        if sku is None:
            return None
        return (sku.nombre.strip().lower(), sku.marca.strip().lower())

    sin_barras = [
        f for f in filas if f.resultado.detalles.get("codigo_barras") != "coincidencia exacta"
    ]
    metricas_sin = _metricas_de(sin_barras)
    con_verdad = [f for f in filas if f.verdad]
    aceptados = [f for f in filas if f.resultado.decision == "aceptado" and f.verdad]
    errores_presentacion = [
        f
        for f in con_verdad
        if f.sku_top1 and f.sku_top1 != f.verdad and linea(f.sku_top1) == linea(f.verdad)
    ]
    presentacion_aceptada = [
        f
        for f in aceptados
        if f.sku_top1 and f.sku_top1 != f.verdad and linea(f.sku_top1) == linea(f.verdad)
    ]
    return {
        "n_total": len(filas),
        "n_resueltas_por_barras": len(filas) - len(sin_barras),
        "n_sin_barras": len(sin_barras),
        "top1_sin_barras": metricas_sin.get("top1"),
        "top3_sin_barras": metricas_sin.get("top3"),
        "precision_aceptado_sin_barras": metricas_sin.get("precision_aceptado"),
        "cobertura_sin_barras": metricas_sin.get("cobertura"),
        "n_con_verdad": len(con_verdad),
        "errores_presentacion": len(errores_presentacion),
        "tasa_errores_presentacion": (
            len(errores_presentacion) / len(con_verdad) if con_verdad else None
        ),
        "presentacion_incorrecta_aceptada": len(presentacion_aceptada),
        "tasa_presentacion_aceptada": (
            len(presentacion_aceptada) / len(aceptados) if aceptados else None
        ),
    }


# ---------------------------------------------------------------------------
# Baseline y calibración
# ---------------------------------------------------------------------------


def baseline_difuso(filas: list[FilaEvaluada], skus: list) -> dict:
    """Top-1/Top-3 con rapidfuzz clásico sobre TODO el maestro (sin embeddings)."""
    from rapidfuzz import fuzz, process

    catalogo = {s.sku: s.nombre_completo for s in skus}
    if not catalogo:
        return {}

    aciertos1 = 0
    aciertos3 = 0
    con_verdad = [f for f in filas if f.verdad]
    for fila in con_verdad:
        resultados = process.extract(
            normalizar(fila.consulta.texto), catalogo, scorer=fuzz.token_set_ratio, limit=3
        )
        elegidos = [r[2] for r in resultados]
        if elegidos and elegidos[0] == fila.verdad:
            aciertos1 += 1
        if fila.verdad in elegidos:
            aciertos3 += 1
    n = len(con_verdad) or 1
    return {"difuso_top1": aciertos1 / n, "difuso_top3": aciertos3 / n, "n": n}


def calibrar_umbrales(
    filas: list[FilaEvaluada], meta_precision: float = 0.95, min_aceptados: int = 5
) -> dict | None:
    """Busca el `umbral_alto` que maximiza la cobertura manteniendo la precisión objetivo.

    Cuenta como error TODA fila aceptada que no sea correcta, incluidas las filas
    sin match real (verdad vacía): aceptar un "no existe" también baja la precisión.
    Si ninguna fila tiene verdad, no hay nada que calibrar y devuelve None.
    """
    if not any(f.verdad for f in filas):
        return None
    pares = [
        (f.resultado.mejor.puntaje, bool(f.verdad) and f.correcto_top1)
        for f in filas
        if f.resultado.mejor is not None
    ]
    if not pares:
        return None
    mejor: tuple[float, int, float] | None = None
    for alto_centesimas in range(50, 100):
        alto = alto_centesimas / 100
        aceptados = [correcto for puntaje, correcto in pares if puntaje >= alto]
        if len(aceptados) < min_aceptados:
            continue
        precision = sum(aceptados) / len(aceptados)
        if precision >= meta_precision and (mejor is None or len(aceptados) > mejor[1]):
            mejor = (alto, len(aceptados), precision)
    if mejor is None:
        return {"sugerencia": "sin combinación que cumpla la precisión objetivo"}
    alto, n_aceptados, precision = mejor
    return {
        "umbral_alto_sugerido": alto,
        "umbral_bajo_sugerido": round(max(0.35, alto - 0.15), 2),
        "aceptados_en_evaluacion": n_aceptados,
        "precision_en_aceptados": round(precision, 4),
        "meta_precision": meta_precision,
    }


# ---------------------------------------------------------------------------
# Evaluación completa
# ---------------------------------------------------------------------------


def evaluar(
    emparejador: Emparejador,
    consultas: list[Consulta],
    verdad: dict[str, str],
    *,
    con_baseline: bool = True,
    calibrar: bool = False,
    ejemplos_error: int = 8,
    pares_salida: str | Path | None = None,
) -> InformeEvaluacion:
    import time

    inicio = time.perf_counter()
    filas: list[FilaEvaluada] = []
    for consulta in consultas:
        resultado = emparejador.emparejar(consulta)
        filas.append(FilaEvaluada(consulta, verdad.get(consulta.id_fila, ""), resultado))
    segundos = time.perf_counter() - inicio

    # Sustitutos (proxy sobre los SKUs agotados del propio maestro)
    agotados = {s.sku: s for s in emparejador.indice.skus if s.agotado}
    filas_agotadas = [f for f in filas if f.verdad in agotados]
    propuestos = [f for f in filas_agotadas if f.resultado.sustitutos]
    util_categoria = [
        f
        for f in propuestos
        if any(s.sku.categoria == agotados[f.verdad].categoria for s in f.resultado.sustitutos)
    ]
    util_marca = [
        f
        for f in propuestos
        if any(s.sku.marca == agotados[f.verdad].marca for s in f.resultado.sustitutos)
    ]
    metricas_sustitutos = {
        "n_agotados": len(filas_agotadas),
        "tasa_propuesto": (len(propuestos) / len(filas_agotadas)) if filas_agotadas else None,
        "tasa_misma_categoria": (len(util_categoria) / len(propuestos)) if propuestos else None,
        "tasa_misma_marca": (len(util_marca) / len(propuestos)) if propuestos else None,
    }

    errores = []
    for fila in filas:
        if fila.verdad and not fila.correcto_top1 and fila.resultado.mejor is not None:
            errores.append(
                {
                    "consulta": fila.consulta.texto,
                    "verdad": fila.verdad,
                    "predicho": fila.sku_top1,
                    "puntaje": fila.resultado.mejor.puntaje,
                    "decision": fila.resultado.decision,
                }
            )
    errores.sort(key=lambda e: -e["puntaje"])

    # Exportar pares de entrenamiento (positivo + negativos duros = errores del top-3)
    if pares_salida:
        ruta = Path(pares_salida)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("w", encoding="utf-8") as fh:
            for fila in filas:
                if not fila.verdad or fila.correcto_top1:
                    continue
                negativos = [c.sku.sku for c in fila.resultado.candidatos if c.sku.sku != fila.verdad]
                if not negativos:
                    continue
                fh.write(
                    json.dumps(
                        {
                            "consulta": fila.consulta.texto,
                            "positivo": fila.verdad,
                            "negativos": negativos[:3],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    return InformeEvaluacion(
        metricas=_metricas_de(filas),
        por_dificultad=_agrupar(filas, lambda f: f.consulta.dificultad),
        por_fuente=_agrupar(filas, lambda f: f.consulta.fuente),
        baseline=baseline_difuso(filas, emparejador.indice.skus) if con_baseline else {},
        sustitutos=metricas_sustitutos,
        ejemplos_error=errores[:ejemplos_error],
        calibracion=calibrar_umbrales(filas) if calibrar else None,
        backend=emparejador.indice.backend_info,
        config=emparejador.cfg.a_dict(),
        n_consultas=len(filas),
        n_maestro=emparejador.indice.n,
        cortes=_cortes_honestos(filas, emparejador.indice.sku_por_id()),
        segundos=round(segundos, 2),
    )
