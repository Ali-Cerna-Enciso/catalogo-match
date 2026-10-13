"""Sustitutos: cuando el SKU ganador está agotado, proponer alternativas del maestro."""

from __future__ import annotations

from .config import ConfigMatcher
from .modelos import SKU, Sustituto
from .normaliza import compatibilidad_cantidad, parsear_cantidad, similitud_textos


def _cantidad_de(sku: SKU):
    if sku.contenido_valor and sku.contenido_unidad:
        from .normaliza import Cantidad

        return Cantidad(float(sku.contenido_valor), sku.contenido_unidad, 1, sku.presentacion)
    return parsear_cantidad(sku.presentacion)


def proponer_sustitutos(
    origen: SKU,
    catalogo: list[SKU],
    curados: list[tuple[str, str, str]] | None = None,
    cfg: ConfigMatcher | None = None,
    vectores_por_sku: dict[str, object] | None = None,
) -> list[Sustituto]:
    """Devuelve sustitutos con stock para un SKU agotado.

    Ordena: primero los curados (lista explícita), luego heurística
    (misma categoría/marca + presentación y embedding cercanos).
    """
    cfg = cfg or ConfigMatcher()
    curados = curados or []
    por_id = {s.sku: s for s in catalogo}
    propuestos: list[Sustituto] = []
    vistos: set[str] = {origen.sku}

    def _agregar(sku: SKU, puntaje: float, motivo: str) -> None:
        if sku.sku in vistos or not sku.activo or sku.agotado:
            return
        vistos.add(sku.sku)
        propuestos.append(Sustituto(sku=sku, puntaje=round(puntaje, 4), motivo=motivo))

    # 1) Curados
    for sku_origen, sku_sustituto, motivo in curados:
        if sku_origen != origen.sku:
            continue
        candidato = por_id.get(sku_sustituto)
        si_texto = (
            similitud_textos(origen.nombre_completo, candidato.nombre_completo) if candidato else 0.0
        )
        if candidato:
            _agregar(candidato, max(0.85, si_texto), f"curado: {motivo or 'par definido en el maestro'}")

    # 2) Heurístico
    cantidad_origen = _cantidad_de(origen)
    puntuados: list[tuple[float, SKU, list[str]]] = []
    for sku in catalogo:
        if sku.sku == origen.sku or not sku.activo or sku.agotado:
            continue
        motivos: list[str] = []
        puntaje = 0.0
        misma_subcategoria = bool(sku.subcategoria and sku.subcategoria == origen.subcategoria)
        sim_texto = similitud_textos(origen.nombre_completo, sku.nombre_completo)
        if not misma_subcategoria and sim_texto < 0.45:
            # Sin parentesco real: evita proponer "Leche" como sustituto de "Yogurt".
            continue
        if sku.categoria and sku.categoria == origen.categoria:
            puntaje += 0.4
            motivos.append("misma categoría")
        if sku.marca and sku.marca == origen.marca:
            puntaje += 0.25
            motivos.append("misma marca")
        if misma_subcategoria:
            puntaje += 0.1
            motivos.append("misma subcategoría")
        sim_cant, detalle_cant = compatibilidad_cantidad(cantidad_origen, _cantidad_de(sku))
        if sim_cant is not None:
            puntaje += 0.2 * sim_cant
            if detalle_cant in {"igual", "similar"}:
                motivos.append(f"presentación {detalle_cant}")
        if vectores_por_sku and origen.sku in vectores_por_sku and sku.sku in vectores_por_sku:
            import numpy as np

            sim_vec = float(
                np.dot(
                    np.asarray(vectores_por_sku[origen.sku], dtype=np.float32),
                    np.asarray(vectores_por_sku[sku.sku], dtype=np.float32),
                )
            )
            puntaje += 0.15 * max(0.0, sim_vec)
        else:
            puntaje += 0.15 * sim_texto
        if not motivos:
            continue  # sin categoría ni marca compartida: no se propone
        puntuados.append((puntaje, sku, motivos))

    puntuados.sort(key=lambda t: -t[0])
    for puntaje, sku, motivos in puntuados[: cfg.max_sustitutos]:
        _agregar(sku, puntaje, ", ".join(motivos))

    return propuestos[: cfg.max_sustitutos]
