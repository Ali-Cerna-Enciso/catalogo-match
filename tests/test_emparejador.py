"""Tests del emparejador: decisiones, código de barras, empates y sustitutos."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from catalogo_match.config import ConfigMatcher
from catalogo_match.emparejador import Emparejador, emparejador_desde_indice
from catalogo_match.indice import Indice
from catalogo_match.modelos import Consulta

# Umbrales altos: obligan a abstenerse con casi cualquier texto.
CFG_EXIGENTE = ConfigMatcher(umbral_alto=0.95, umbral_bajo=0.90)
# Margen de empate enorme: cualquier consulta con 2 candidatos cae en "revisar".
CFG_EMPATE = ConfigMatcher(umbral_alto=0.10, umbral_bajo=0.0, margen_empate=0.50)


def _consulta(texto: str, id_fila: str = "X1", **extra) -> Consulta:
    return Consulta(id_fila=id_fila, texto=texto, **extra)


def _matriz_vacia(embedder) -> np.ndarray:
    return np.zeros((0, embedder.dim), dtype=np.float32)


class TestConstruccion:
    def test_emparejador_desde_indice_guardado(self, indice_dir: Path):
        emparejador = emparejador_desde_indice(indice_dir)
        assert emparejador.indice.n == 6
        assert emparejador.indice.huella == "hash-ngrama3-512-v1"
        assert emparejador.cfg.umbral_alto == 0.78  # configuración por defecto

    def test_emparejador_desde_indice_con_config(self, indice_dir: Path):
        cfg = ConfigMatcher(umbral_alto=0.5, top_resultados=1)
        assert emparejador_desde_indice(indice_dir, cfg).cfg == cfg

    def test_avisa_si_la_huella_del_indice_no_coincide(self, indice, embedder):
        otro = type(embedder)(dim=64)
        with pytest.warns(UserWarning, match="Re-indexa el maestro"):
            Emparejador(indice, otro)

    def test_verificar_backend_se_puede_desactivar(self, indice, embedder):
        otro = type(embedder)(dim=64)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            Emparejador(indice, otro, verificar_backend=False)


class TestDecisiones:
    def test_consulta_facil_da_el_top1_correcto(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Detergente Ropa Bolsa Blanco 4 kg"))
        assert resultado.decision == "aceptado"
        assert resultado.mejor is not None
        assert resultado.mejor.sku.sku == "SKU-003"
        assert resultado.mejor.puntaje >= 0.78
        assert resultado.mejor.motivos == ["marca coincide"]  # "Blanco" es la marca del SKU

    def test_top1_suma_bonus_de_marca(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert resultado.mejor.sku.sku == "SKU-002"
        assert resultado.mejor.ajustes["marca"] == pytest.approx(0.05)
        assert "marca coincide" in resultado.mejor.motivos

    def test_marca_ausente_no_suma_bonus(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa 900 g"))
        assert resultado.mejor.sku.sku == "SKU-002"
        assert "marca" not in resultado.mejor.ajustes
        assert "marca coincide" not in resultado.mejor.motivos

    @pytest.mark.parametrize("umbrales", [CFG_EXIGENTE, ConfigMatcher()])
    def test_consulta_sin_relacion_se_abstiene(self, indice, embedder, umbrales):
        emparejador = Emparejador(indice, embedder, umbrales)
        resultado = emparejador.emparejar(_consulta("zzzz qqqq vvvv wwww"))
        assert resultado.decision == "no_se"
        assert resultado.motivo_decision == "sin candidato suficiente"
        assert resultado.mejor.puntaje < umbrales.umbral_bajo

    def test_puntaje_en_zona_gris_pide_revision(self, indice, embedder):
        """Con umbrales muy bajos, un puntaje medio cae en "revisar"."""
        cfg = ConfigMatcher(umbral_alto=0.99, umbral_bajo=0.30)
        emparejador = Emparejador(indice, embedder, cfg)
        resultado = emparejador.emparejar(_consulta("Lejia Limon Brillo 1 l"))
        assert resultado.decision == "revisar"
        assert resultado.motivo_decision == "puntaje en zona gris"

    def test_empate_estrecho_pide_revision(self, indice, embedder):
        emparejador = Emparejador(indice, embedder, CFG_EMPATE)
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert resultado.decision == "revisar"
        assert resultado.motivo_decision == "empate estrecho en el top-2"
        assert resultado.detalles["empate_estrecho"] < CFG_EMPATE.margen_empate
        assert len(resultado.candidatos) >= 2

    def test_el_mismo_caso_sin_margen_de_empate_se_acepta(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert resultado.decision == "aceptado"
        assert "empate_estrecho" not in resultado.detalles

    def test_indice_vacio_se_abstiene(self, embedder):
        emparejador = Emparejador(Indice(skus=[], vectores=_matriz_vacia(embedder), meta={}), embedder)
        resultado = emparejador.emparejar(_consulta("cualquier cosa"))
        assert resultado.decision == "no_se"
        assert resultado.motivo_decision == "índice vacío"
        assert resultado.candidatos == []


class TestCodigoDeBarras:
    def test_coincidencia_exacta_fuerza_puntaje_1_y_aceptado(self, emparejador):
        resultado = emparejador.emparejar(
            _consulta("texto irrelevante", codigo_barras="7751234567894")
        )
        assert resultado.decision == "aceptado"
        assert resultado.motivo_decision == "código de barras exacto"
        assert resultado.detalles["codigo_barras"] == "coincidencia exacta"
        assert resultado.mejor.sku.sku == "SKU-005"
        assert resultado.mejor.puntaje == 1.0
        assert resultado.mejor.ajustes["codigo_barras"] == 1.0
        assert "código de barras exacto" in resultado.mejor.motivos

    def test_gana_aunque_el_sku_no_estuviera_en_el_top(self, indice, embedder):
        cfg = ConfigMatcher(top_candidatos=1, top_resultados=1)
        emparejador = Emparejador(indice, embedder, cfg)
        resultado = emparejador.emparejar(
            _consulta("Yogurt Griego Fresa Aurora 900 g", codigo_barras="7751234567895"), top=1
        )
        assert resultado.decision == "aceptado"
        assert resultado.mejor.sku.sku == "SKU-006"
        assert resultado.mejor.puntaje == 1.0

    def test_codigo_sin_coincidencia_se_registra_en_detalles(self, emparejador):
        resultado = emparejador.emparejar(
            _consulta("Detergente Ropa Bolsa Blanco 4 kg", codigo_barras="9999999999999")
        )
        assert resultado.detalles["codigo_barras"] == "sin coincidencia"
        assert resultado.mejor.sku.sku == "SKU-003"  # decide por texto, no por barcode
        assert "código de barras exacto" not in resultado.mejor.motivos


class TestEstructuraDeSalida:
    def test_top_resultados_limita_los_candidatos_devueltos(self, indice, embedder):
        emparejador = Emparejador(indice, embedder, ConfigMatcher(top_resultados=2))
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert len(resultado.candidatos) == 2

    def test_top_explicito_tiene_prioridad(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"), top=1)
        assert len(resultado.candidatos) == 1

    def test_candidatos_ordenados_por_puntaje(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 3 x 170 g"))
        puntajes = [c.puntaje for c in resultado.candidatos]
        assert puntajes == sorted(puntajes, reverse=True)

    def test_desglose_de_puntajes_presente(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        candidato = resultado.mejor
        assert candidato.puntaje_embedding > 0.0
        assert candidato.puntaje_lexico > 0.0
        assert candidato.puntaje_cantidad == pytest.approx(1.0)  # 900 g vs 900 g
        assert resultado.detalles["modo_consulta"] == "texto"

    def test_como_dict_tiene_las_claves_del_jsonl(self, emparejador):
        datos = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g")).como_dict()
        assert set(datos) == {
            "id_fila",
            "proveedor",
            "consulta",
            "fuente",
            "decision",
            "motivo_decision",
            "candidatos",
            "sustitutos",
            "detalles",
        }
        assert datos["id_fila"] == "X1"
        assert datos["candidatos"][0]["sku"].startswith("SKU-")

    def test_emparejar_lote_devuelve_un_resultado_por_consulta(self, emparejador, consultas):
        resultados = list(emparejador.emparejar_lote(consultas))
        assert len(resultados) == len(consultas) == 4
        assert [r.consulta.id_fila for r in resultados] == ["F1", "F2", "F3", "F4"]


class TestSustitutos:
    def test_sku_agotado_propone_sustituto_heuristico(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert resultado.mejor.sku.sku == "SKU-002"
        assert resultado.mejor.sku.agotado is True
        assert resultado.detalles["sustitutos_para"] == "SKU-002"
        assert [s.sku.sku for s in resultado.sustitutos] == ["SKU-001"]
        sustituto = resultado.sustitutos[0]
        assert sustituto.sku.stock > 0
        assert sustituto.sku.agotado is False
        assert "misma categoría" in sustituto.motivo
        assert "misma marca" in sustituto.motivo

    def test_sustituto_curado_tiene_prioridad(self, indice, embedder):
        emparejador = Emparejador(
            indice, embedder, ConfigMatcher(), sustitutos_curados=[("SKU-002", "SKU-001", "mismo sabor")]
        )
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert [s.sku.sku for s in resultado.sustitutos] == ["SKU-001"]
        assert resultado.sustitutos[0].motivo == "curado: mismo sabor"
        assert resultado.sustitutos[0].puntaje >= 0.85

    def test_respeta_stock_disponible_en_sustitutos(self, indice, embedder):
        emparejador = Emparejador(
            indice, embedder, ConfigMatcher(), sustitutos_curados=[("SKU-002", "SKU-004", "sin stock")]
        )
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        elegidos = {s.sku.sku for s in resultado.sustitutos}
        assert "SKU-004" not in elegidos  # el curado apunta a un SKU agotado
        assert elegidos == {"SKU-001"}  # queda la heurística de misma categoría/marca
        assert all(s.sku.stock > 0 for s in resultado.sustitutos)

    def test_sku_con_stock_no_propone_sustitutos(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Detergente Ropa Bolsa Blanco 4 kg"))
        assert resultado.mejor.sku.agotado is False
        assert resultado.sustitutos == []
        assert "sustitutos_para" not in resultado.detalles

    def test_sin_sustitutos_desactiva_la_propuesta(self, emparejador):
        resultado = emparejador.emparejar(
            _consulta("Yogurt Griego Fresa Aurora 900 g"), con_sustitutos=False
        )
        assert resultado.sustitutos == []

    def test_abstencion_no_propone_sustitutos(self, indice, embedder):
        emparejador = Emparejador(indice, embedder, CFG_EXIGENTE)
        resultado = emparejador.emparejar(_consulta("Arroz Extra Grano Campos 5 kg"))
        assert resultado.decision == "no_se"
        assert resultado.sustitutos == []

    def test_heuristica_prefiere_misma_categoria(self, emparejador):
        resultado = emparejador.emparejar(_consulta("Arroz Extra Grano Campos 5 kg"))
        assert resultado.mejor.sku.sku == "SKU-004"
        assert resultado.sustitutos
        primero = resultado.sustitutos[0]
        assert primero.sku.sku == "SKU-005"
        assert "misma categoría" in primero.motivo



class TestConImagenes:
    def test_imagen_inexistente_cae_a_texto(self, emparejador):
        consulta = _consulta("Yogurt Griego Fresa Aurora 900 g", imagen="no_existe.jpg")
        resultado = emparejador.emparejar(consulta)
        assert resultado.detalles["modo_consulta"] == "texto"
        assert resultado.mejor.sku.sku == "SKU-002"

    def test_imagen_con_backend_de_solo_texto_se_ignora(self, emparejador, tmp_path: Path):
        foto = tmp_path / "foto.jpg"
        foto.write_bytes(b"img")
        resultado = emparejador.emparejar(
            _consulta("Yogurt Griego Fresa Aurora 900 g", imagen=str(foto))
        )
        assert resultado.detalles["modo_consulta"] == "texto"
        assert resultado.mejor.sku.sku == "SKU-002"


class TestConstruccionConSustitutosCurados:
    def test_emparejador_desde_indice_acepta_curados(self, indice_dir: Path):
        emparejador = emparejador_desde_indice(
            indice_dir, None, [("SKU-002", "SKU-001", "curado")]
        )
        resultado = emparejador.emparejar(_consulta("Yogurt Griego Fresa Aurora 900 g"))
        assert resultado.sustitutos[0].motivo == "curado: curado"
