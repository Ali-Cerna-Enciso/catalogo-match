"""Emparejador: consulta sucia -> top-N de SKUs con puntaje, decisión y sustitutos."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np

from .backends import Embeddor
from .config import ConfigMatcher
from .indice import Indice
from .modelos import SKU, Candidato, Consulta, Resultado
from .normaliza import (
    LONGITUD_MINIMA_PARECIDO,
    RUIDO_PROVEEDOR,
    TOLERANCIA_TOKEN,
    Cantidad,
    compatibilidad_cantidad,
    marca_en_texto,
    parsear_cantidad,
    similitud_textos,
    tokenizar,
)
from .sustitutos import proponer_sustitutos

_log = logging.getLogger(__name__)


def _cantidad_sku(sku: SKU) -> Cantidad | None:
    if sku.contenido_valor and sku.contenido_unidad:
        return Cantidad(float(sku.contenido_valor), sku.contenido_unidad, 1, sku.presentacion)
    return parsear_cantidad(sku.presentacion)


def _parece_del_catalogo(token: str, vocabulario: set[str]) -> bool:
    """Decide si un token ajeno al ganador se puede atribuir a una palabra del catálogo.

    Con menos de `LONGITUD_MINIMA_PARECIDO` letras solo valen la coincidencia exacta
    o el truncamiento (el token es prefijo de una palabra del catálogo); el parecido
    difuso se reserva para palabras largas, donde un typo no cambia el significado.
    """
    if token in vocabulario:
        return True
    if len(token) < LONGITUD_MINIMA_PARECIDO:
        return any(conocido.startswith(token) for conocido in vocabulario)
    from rapidfuzz import fuzz

    return any(fuzz.ratio(token, conocido) >= TOLERANCIA_TOKEN for conocido in vocabulario)


def tokens_fuera_de_catalogo(
    texto: str,
    sku_ganador: SKU,
    vocabulario: set[str],
    tokens_por_sku: dict[str, set[str]],
) -> list[str]:
    """Tokens significativos de la consulta que ni el ganador ni el catálogo reconocen.

    Señal de "variante fuera de catálogo": el proveedor pide un sabor/subtipo que el
    maestro no tiene (p. ej. una variante de línea agotada). Se ignoran el vocabulario
    de envase/administración (RUIDO_PROVEEDOR) y los parecidos razonables (typos y
    truncados), para no castigar el ruido normal de los pedidos.
    """
    tokens_ganador = tokens_por_sku.get(sku_ganador.sku, set())
    raros: list[str] = []
    for token in sorted(set(tokenizar(texto)) - tokens_ganador):
        if len(token) < 4 or not token.isalpha() or token in RUIDO_PROVEEDOR:
            continue
        if _parece_del_catalogo(token, vocabulario):
            continue
        raros.append(token)
    return raros


class Emparejador:
    """Combina embedding + reglas de texto/cantidad y decide con umbrales."""

    def __init__(
        self,
        indice: Indice,
        embedder: Embeddor,
        cfg: ConfigMatcher | None = None,
        sustitutos_curados: list[tuple[str, str, str]] | None = None,
        verificar_backend: bool = True,
    ):
        self.indice = indice
        self.embedder = embedder
        self.cfg = cfg or ConfigMatcher()
        self.sustitutos_curados = list(sustitutos_curados or [])
        self._por_id = indice.sku_por_id()
        self._vectores = {s.sku: indice.vectores[i] for i, s in enumerate(indice.skus)}
        conteo_barras: dict[str, int] = {}
        for s in indice.skus:
            if s.codigo_barras:
                conteo_barras[s.codigo_barras] = conteo_barras.get(s.codigo_barras, 0) + 1
        self._por_barras = {
            s.codigo_barras: s
            for s in indice.skus
            if s.codigo_barras and conteo_barras[s.codigo_barras] == 1
        }
        self._barras_duplicadas = {c for c, n in conteo_barras.items() if n > 1}
        self._vocab_cache: tuple[set[str], dict[str, set[str]]] | None = None

        if verificar_backend and indice.huella and indice.huella != "desconocida":
            actual = embedder.huella()
            if actual != indice.huella:
                warnings.warn(
                    f"El índice fue construido con '{indice.huella}' y ahora se usa '{actual}'. "
                    "Re-indexa el maestro para que los vectores sean comparables.",
                    stacklevel=2,
                )

    def _vocabulario_catalogo(self) -> tuple[set[str], dict[str, set[str]]]:
        """Vocabulario de tokens del maestro (lazy y cacheado)."""
        if self._vocab_cache is None:
            vocabulario: set[str] = set()
            tokens_por_sku: dict[str, set[str]] = {}
            for sku in self.indice.skus:
                tokens = set(tokenizar(sku.nombre_completo))
                tokens_por_sku[sku.sku] = tokens
                vocabulario |= tokens
            self._vocab_cache = (vocabulario, tokens_por_sku)
        return self._vocab_cache

    # -- vector de consulta --------------------------------------------------

    def _vector_consulta(self, consulta: Consulta) -> tuple[np.ndarray, str, str | None, bool]:
        """Devuelve (vector, modo, advertencia, imagen_fallida)."""
        modalidades = getattr(self.embedder, "modalidades", frozenset({"texto"}))
        if consulta.imagen and "imagen" in modalidades:
            if not Path(consulta.imagen).exists():
                vec = self.embedder.encode_textos([consulta.texto], tipo="consulta")
                return vec[0], "texto (imagen no encontrada)", None, True
            try:
                vector = self.embedder.encode_multimodal(
                    [{"texto": consulta.texto, "imagen": consulta.imagen}], tipo="consulta"
                )
                return vector[0], "texto+imagen", None, False
            except Exception as e:  # pragma: no cover - depende del entorno/modelo
                _log.warning(
                    "falló el embedding de imagen (%s): %s; se continúa con texto",
                    type(e).__name__,
                    e,
                )
                vec = self.embedder.encode_textos([consulta.texto], tipo="consulta")
                return vec[0], "texto", f"falló el embedding de imagen ({type(e).__name__}): {e}", True
        return self.embedder.encode_textos([consulta.texto], tipo="consulta")[0], "texto", None, False

    # -- puntuación ----------------------------------------------------------

    def _puntuar(
        self,
        consulta: Consulta,
        sku: SKU,
        sim_embedding: float,
        cantidad_consulta: Cantidad | None,
    ) -> Candidato:
        cfg = self.cfg
        sim_lexico = similitud_textos(consulta.texto, sku.nombre_completo)
        embedding_invalido = not np.isfinite(sim_embedding)
        if embedding_invalido:
            sim_embedding = 0.0  # NaN/Inf nunca debe decidir un match
        sim_cantidad, detalle_cantidad = compatibilidad_cantidad(
            cantidad_consulta, _cantidad_sku(sku)
        )

        if sim_cantidad is None:
            total = cfg.peso_embedding + cfg.peso_lexico
            puntaje = (
                (cfg.peso_embedding * sim_embedding + cfg.peso_lexico * sim_lexico) / total
                if total
                else 0.0
            )
        else:
            puntaje = (
                cfg.peso_embedding * sim_embedding
                + cfg.peso_lexico * sim_lexico
                + cfg.peso_cantidad * sim_cantidad
            )

        ajustes: dict[str, float] = {}
        motivos: list[str] = []
        if embedding_invalido:
            motivos.append("embedding inválido")
        if cfg.bonus_marca and marca_en_texto(consulta.texto, sku.marca):
            ajustes["marca"] = cfg.bonus_marca
            motivos.append("marca coincide")
        if detalle_cantidad == "distinta":
            motivos.append("presentación distinta")
        elif detalle_cantidad == "unidades_no_comparables":
            motivos.append("unidades no comparables")
        puntaje += sum(ajustes.values())

        return Candidato(
            sku=sku,
            puntaje=round(min(max(puntaje, 0.0), 1.0), 4),
            puntaje_embedding=round(float(sim_embedding), 4),
            puntaje_lexico=round(float(sim_lexico), 4),
            puntaje_cantidad=None if sim_cantidad is None else round(float(sim_cantidad), 4),
            ajustes=ajustes,
            motivos=motivos,
        )

    # -- emparejamiento ------------------------------------------------------

    def emparejar(
        self,
        consulta: Consulta,
        top: int | None = None,
        con_sustitutos: bool = True,
    ) -> Resultado:
        cfg = self.cfg
        top = top or cfg.top_resultados
        detalles: dict = {}

        if not self.indice.skus:
            return Resultado(consulta, [], "no_se", "índice vacío", [], detalles)

        vector, modo, advertencia, fallo_imagen = self._vector_consulta(consulta)
        detalles["modo_consulta"] = modo
        if advertencia:
            detalles["advertencia"] = advertencia
        if fallo_imagen:
            detalles["imagen_fallida"] = True

        indices, sims = self.indice.top(vector, max(cfg.top_candidatos, top))
        cantidad_consulta = parsear_cantidad(consulta.texto)
        candidatos = [
            self._puntuar(consulta, self.indice.skus[int(idx)], float(sims[pos]), cantidad_consulta)
            for pos, idx in enumerate(indices)
        ]

        # Código de barras: solo gana si es ÚNICO en el maestro y el SKU está activo
        estado_barras: str | None = None
        if consulta.codigo_barras:
            if consulta.codigo_barras in self._barras_duplicadas:
                estado_barras = "duplicado"
                detalles["codigo_barras"] = "duplicado en el maestro"
            else:
                encontrado = self._por_barras.get(consulta.codigo_barras)
                if encontrado is None:
                    estado_barras = "sin_coincidencia"
                    detalles["codigo_barras"] = "sin coincidencia"
                elif not encontrado.activo:
                    estado_barras = "inactivo"
                    detalles["codigo_barras"] = "SKU inactivo (no se fuerza)"
                else:
                    estado_barras = "ok"
                    detalles["codigo_barras"] = "coincidencia exacta"
                    for candidato in candidatos:
                        if candidato.sku.sku == encontrado.sku:
                            candidato.puntaje = 1.0
                            candidato.ajustes["codigo_barras"] = 1.0
                            candidato.motivos.append("código de barras exacto")
                            break
                    else:
                        candidatos.append(
                            Candidato(
                                sku=encontrado,
                                puntaje=1.0,
                                ajustes={"codigo_barras": 1.0},
                                motivos=["código de barras exacto"],
                            )
                        )

        candidatos.sort(key=lambda c: -c.puntaje)
        p1 = candidatos[0].puntaje if candidatos else 0.0
        p2 = candidatos[1].puntaje if len(candidatos) > 1 else None
        estrecho = p2 is not None and (p1 - p2) < cfg.margen_empate
        con_barras = bool(candidatos and "código de barras exacto" in candidatos[0].motivos)

        if con_barras:
            decision, motivo = "aceptado", "código de barras exacto"
        elif p1 >= cfg.umbral_alto and not estrecho:
            decision, motivo = "aceptado", "puntaje alto"
        elif p1 >= cfg.umbral_alto and estrecho:
            decision, motivo = "revisar", "empate estrecho en el top-2"
        elif p1 >= cfg.umbral_bajo:
            decision, motivo = "revisar", "puntaje en zona gris"
        else:
            decision, motivo = "no_se", "sin candidato suficiente"

        # Un EAN duplicado o de un SKU inactivo no automatiza: va a revisión.
        if estado_barras == "duplicado":
            decision, motivo = "revisar", "código de barras duplicado en el maestro"
        elif estado_barras == "inactivo":
            decision, motivo = "revisar", "código de barras de un SKU inactivo"

        # Veto: misma familia pero presentación muy distinta (5 kg vs 500 g) no se acepta sola.
        if (
            decision == "aceptado"
            and not con_barras
            and candidatos
            and "presentación distinta" in candidatos[0].motivos
            and (candidatos[0].puntaje_cantidad or 0.0) < 0.3
        ):
            decision, motivo = "revisar", "presentación incompatible con la consulta"

        # Si la foto era el único insumo y no se pudo procesar, no se disfraza de match de texto.
        if fallo_imagen and not consulta.texto.strip():
            decision, motivo = "revisar", "imagen no procesable y sin texto de respaldo"

        # Variante fuera de catálogo: la consulta pide un sabor/subtipo que el maestro no
        # tiene (p. ej. una variante de línea). No se acepta sola.
        if decision == "aceptado" and not con_barras and candidatos:
            vocabulario, tokens_por_sku = self._vocabulario_catalogo()
            raros = tokens_fuera_de_catalogo(
                consulta.texto, candidatos[0].sku, vocabulario, tokens_por_sku
            )
            if raros:
                decision = "revisar"
                motivo = f"posible variante fuera del catálogo: {', '.join(raros[:3])}"
                detalles["tokens_fuera_de_catalogo"] = raros

        if estrecho and p2 is not None:
            detalles["empate_estrecho"] = round(p1 - p2, 4)

        candidatos = candidatos[:top]

        sustitutos = []
        if con_sustitutos and decision != "no_se" and candidatos and candidatos[0].sku.agotado:
            sustitutos = proponer_sustitutos(
                candidatos[0].sku,
                self.indice.skus,
                curados=self.sustitutos_curados,
                cfg=cfg,
                vectores_por_sku=self._vectores,
            )
            detalles["sustitutos_para"] = candidatos[0].sku.sku

        return Resultado(
            consulta=consulta,
            candidatos=candidatos,
            decision=decision,
            motivo_decision=motivo,
            sustitutos=sustitutos,
            detalles=detalles,
        )

    def emparejar_lote(self, consultas: list[Consulta], con_sustitutos: bool = True):
        for consulta in consultas:
            yield self.emparejar(consulta, con_sustitutos=con_sustitutos)


def emparejador_desde_indice(
    ruta_indice: str | Path,
    cfg: ConfigMatcher | None = None,
    sustitutos_curados: list[tuple[str, str, str]] | None = None,
    overrides_backend: dict | None = None,
) -> Emparejador:
    """Carga un índice guardado y reconstruye su backend para consultar."""
    from .backends import backend_desde_meta

    indice = Indice.cargar(ruta_indice)
    embedder = backend_desde_meta(indice.meta, **(overrides_backend or {}))
    return Emparejador(indice, embedder, cfg, sustitutos_curados=sustitutos_curados)
