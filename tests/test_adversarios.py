"""Tests adversarios: contratos que NO dependen del generador sintético.

El set sintético se fabrica con el mismo vocabulario que el normalizador y evita
corromper unidades; estos tests fijan el comportamiento en los casos incómodos:
gramaje, cantidad corrupta, marca de otro producto, abreviaturas desconocidas,
EAN duplicado/inactivo y fotos que no se pueden procesar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from catalogo_match.backends import crear_backend
from catalogo_match.config import ConfigMatcher
from catalogo_match.emparejador import Emparejador, tokens_fuera_de_catalogo
from catalogo_match.indice import construir_indice
from catalogo_match.modelos import SKU, Consulta
from catalogo_match.normaliza import parsear_cantidad


def _sku(
    sku: str,
    nombre: str,
    marca: str,
    presentacion: str,
    valor: float,
    unidad: str,
    *,
    ean: str = "",
    activo: bool = True,
) -> SKU:
    return SKU(
        sku=sku,
        nombre=nombre,
        marca=marca,
        presentacion=presentacion,
        contenido_valor=valor,
        contenido_unidad=unidad,
        codigo_barras=ean,
        activo=activo,
        stock=10,
        categoria="lacteos",
        subcategoria="yogur",
    )


def _emparejador(skus: list[SKU]) -> Emparejador:
    """Umbrales altos a propósito: los tests miden el orden del top (el ranking)."""
    embedder = crear_backend("hash")
    cfg = ConfigMatcher(umbral_alto=0.99, umbral_bajo=0.98)
    indice = construir_indice(skus, embedder, cfg)
    return Emparejador(indice, embedder, cfg, verificar_backend=False)


class TestGramaje:
    def test_digito_dentro_de_palabra_no_inventa_cantidad(self):
        """'Y0G' (ruido OCR de YOG) no debe leerse como '0 g'."""
        assert parsear_cantidad("Y0G GRIEG FRESA") is None
        cantidad = parsear_cantidad("Y0G GRIEG FRESA 1KG")
        assert cantidad is not None
        assert cantidad.valor == pytest.approx(1000.0)
        assert cantidad.unidad == "g"

    def test_mismo_producto_distinto_envase_elige_el_que_dice_la_consulta(self):
        emp = _emparejador(
            [
                _sku("SKU-900", "Yogurt Griego Fresa", "Aurora", "900 g", 900, "g"),
                _sku("SKU-1K", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g"),
            ]
        )
        resultado = emp.emparejar(Consulta(id_fila="t", texto="YOG GRIEGO FRESA 1KG"))
        assert resultado.candidatos[0].sku.sku == "SKU-1K"

    def test_cantidad_corrupta_no_cambia_el_producto(self):
        """El ruido sobre la unidad ('900GG') no debe robar el match del sabor."""
        emp = _emparejador(
            [
                _sku("SKU-FRE", "Yogurt Griego Fresa", "Aurora", "900 g", 900, "g"),
                _sku("SKU-NAT", "Yogurt Griego Natural", "Aurora", "900 g", 900, "g"),
            ]
        )
        resultado = emp.emparejar(Consulta(id_fila="t", texto="Y0G GRIEG FRESA 900GG"))
        assert resultado.candidatos[0].sku.sku == "SKU-FRE"


class TestMarcaAjena:
    def test_marca_de_otro_producto_no_se_roba_el_match(self):
        emp = _emparejador(
            [
                _sku("SKU-AUR", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g"),
                _sku("SKU-VAL", "Yogurt Griego Fresa", "Valle Verde", "1 kg", 1000, "g"),
            ]
        )
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="YOGURT GRIEGO FRESA VALLE VERDE 1KG")
        )
        assert resultado.candidatos[0].sku.sku == "SKU-VAL"
        assert "marca coincide" in resultado.candidatos[0].motivos

    def test_abreviatura_desconocida_no_confunde_el_sabor(self):
        """Alfabeto del generador y del normalizador no siempre coinciden: debe sostenerse."""
        emp = _emparejador(
            [
                _sku("SKU-FRE", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g"),
                _sku("SKU-NAT", "Yogurt Griego Natural", "Aurora", "1 kg", 1000, "g"),
            ]
        )
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="YOG GRIGO FRESA 1KG REFFA77 XQ")
        )
        assert resultado.candidatos[0].sku.sku == "SKU-FRE"


class TestCodigoDeBarras:
    def test_ean_duplicado_no_automatiza(self):
        emp = _emparejador(
            [
                _sku("SKU-1", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g", ean="7501234567890"),
                _sku("SKU-2", "Yogurt Griego Fresa", "Aurora", "900 g", 900, "g", ean="7501234567890"),
            ]
        )
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="YOG GRIEGO FRESA 1KG", codigo_barras="7501234567890")
        )
        assert resultado.decision == "revisar"
        assert resultado.detalles["codigo_barras"] == "duplicado en el maestro"
        assert all("código de barras exacto" not in c.motivos for c in resultado.candidatos)
        assert all(c.puntaje < 1.0 for c in resultado.candidatos)

    def test_ean_de_sku_inactivo_no_automatiza(self):
        emp = _emparejador(
            [
                _sku(
                    "SKU-OFF",
                    "Yogurt Griego Fresa",
                    "Aurora",
                    "1 kg",
                    1000,
                    "g",
                    ean="7501234567891",
                    activo=False,
                ),
            ]
        )
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="YOG GRIEGO FRESA 1KG", codigo_barras="7501234567891")
        )
        assert resultado.decision == "revisar"
        assert resultado.detalles["codigo_barras"] == "SKU inactivo (no se fuerza)"
        assert all("código de barras exacto" not in c.motivos for c in resultado.candidatos)

    def test_ean_unico_y_activo_gana_con_1_0(self):
        emp = _emparejador(
            [
                _sku("SKU-1", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g", ean="7501234567892"),
                _sku("SKU-2", "Yogurt Griego Natural", "Aurora", "1 kg", 1000, "g"),
            ]
        )
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="lo que sea", codigo_barras="7501234567892")
        )
        assert resultado.decision == "aceptado"
        assert resultado.candidatos[0].sku.sku == "SKU-1"
        assert resultado.candidatos[0].puntaje == 1.0
        assert "código de barras exacto" in resultado.candidatos[0].motivos


class TestVarianteFueraDeCatalogo:
    """Un sabor/subtipo que no existe en el maestro no debe aceptarse solo."""

    def _emparejador_aceptador(self, skus: list[SKU]) -> Emparejador:
        """Umbrales bajísimos y margen 0: sin el guard, todo saldría 'aceptado'."""
        embedder = crear_backend("hash")
        cfg = ConfigMatcher(umbral_alto=0.10, umbral_bajo=0.05, margen_empate=0.0)
        indice = construir_indice(skus, embedder, cfg)
        return Emparejador(indice, embedder, cfg, verificar_backend=False)

    def test_sabor_que_no_existe_va_a_revision(self):
        emp = self._emparejador_aceptador(
            [
                _sku("SKU-NAT", "Yogurt Griego Natural", "Aurora", "1 kg", 1000, "g"),
                _sku("SKU-FRE", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g"),
            ]
        )
        resultado = emp.emparejar(Consulta(id_fila="t", texto="YOGUR GRIEGO MANGO 1KG"))
        assert resultado.decision == "revisar"
        assert "fuera del catálogo" in resultado.motivo_decision
        assert "mango" in resultado.detalles["tokens_fuera_de_catalogo"]

    def test_ruido_de_envase_y_pedido_no_bloquea(self):
        emp = self._emparejador_aceptador(
            [_sku("SKU-FRE", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g")]
        )
        resultado = emp.emparejar(
            Consulta(
                id_fila="t",
                texto="DESCRIPCION: YOGUR GRIEGO FRESA BOTELLA 1 L LOTE 24 CAJA X3 UNID",
            )
        )
        assert resultado.decision == "aceptado"
        assert "tokens_fuera_de_catalogo" not in resultado.detalles

    def test_typo_o_truncado_no_cuenta_como_variante(self):
        emp = self._emparejador_aceptador(
            [_sku("SKU-FRE", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g")]
        )
        resultado = emp.emparejar(Consulta(id_fila="t", texto="Y0G GRIEG FRS 1KG"))
        assert resultado.decision == "aceptado"


class TestPalabrasCortasDelGuard:
    """El parecido difuso no aplica a palabras cortas: COCO no es CHOCO."""

    def _sku(self, sku: str, nombre: str) -> SKU:
        return SKU(sku=sku, nombre=nombre)

    def test_coco_no_se_lee_como_choco(self):
        vocab = {"batido", "chocolate", "leche"}
        tokens = {"SKU-1": {"batido", "chocolate"}}
        raros = tokens_fuera_de_catalogo(
            "BATIDO DE COCO", self._sku("SKU-1", "Batido de Chocolate"), vocab, tokens
        )
        assert raros == ["coco"]

    def test_jamon_no_se_lee_como_jabon(self):
        vocab = {"pizza", "masa", "fina", "jabon"}
        tokens = {"SKU-2": {"pizza", "masa", "fina"}}
        raros = tokens_fuera_de_catalogo(
            "PIZZA MASA FINA JAMON", self._sku("SKU-2", "Pizza masa fina"), vocab, tokens
        )
        assert raros == ["jamon"]

    def test_truncamiento_corto_se_tolera(self):
        vocab = {"pizza", "masa", "fina"}
        tokens = {"SKU-3": {"masa", "fina"}}
        raros = tokens_fuera_de_catalogo(
            "PIZZ MASA FINA", self._sku("SKU-3", "Pizza masa fina"), vocab, tokens
        )
        assert raros == []

    def test_parecido_en_palabra_larga_se_tolera(self):
        vocab = {"batido", "chocolate"}
        tokens = {"SKU-4": {"batido", "chocolate"}}
        raros = tokens_fuera_de_catalogo(
            "BATIDO CHOCOLATTE", self._sku("SKU-4", "Batido de Chocolate"), vocab, tokens
        )
        assert raros == []


class _EmbeddorImagenRota:
    """Finge soportar imágenes pero falla al procesarlas (foto ilegible)."""

    nombre = "stub-imagen-rota"
    dim = 512
    modalidades = frozenset({"texto", "imagen"})

    def __init__(self) -> None:
        self._hash = crear_backend("hash")

    def huella(self) -> str:
        return "stub-imagen-rota-v1"

    def encode_textos(self, textos, tipo="documento"):
        return self._hash.encode_textos(textos, tipo)

    def encode_multimodal(self, items, tipo="consulta"):
        raise RuntimeError("no se pudo decodificar la imagen")

    def descripcion(self) -> dict:
        return {"nombre": self.nombre, "dim": self.dim}


class TestFotoIlegible:
    def _emparejador_con_foto(self, tmp_path: Path):
        ruta = tmp_path / "foto.jpg"
        ruta.write_bytes(b"esto no es una imagen real")
        embedder = _EmbeddorImagenRota()
        skus = [_sku("SKU-1", "Yogurt Griego Fresa", "Aurora", "1 kg", 1000, "g")]
        indice = construir_indice(skus, embedder, ConfigMatcher())
        emp = Emparejador(indice, embedder, ConfigMatcher(), verificar_backend=False)
        return emp, ruta

    def test_foto_rota_sin_texto_va_a_revision_y_lo_dice(self, tmp_path: Path):
        emp, ruta = self._emparejador_con_foto(tmp_path)
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="", imagen=str(ruta), fuente="foto")
        )
        assert resultado.decision == "revisar"
        assert resultado.motivo_decision == "imagen no procesable y sin texto de respaldo"
        assert resultado.detalles["imagen_fallida"] is True
        assert "falló el embedding de imagen" in resultado.detalles["advertencia"]

    def test_foto_rota_con_texto_sigue_con_el_texto_y_lo_reporta(self, tmp_path: Path):
        emp, ruta = self._emparejador_con_foto(tmp_path)
        resultado = emp.emparejar(
            Consulta(id_fila="t", texto="Yogurt Griego Fresa 1 kg", imagen=str(ruta))
        )
        assert resultado.detalles["imagen_fallida"] is True
        assert resultado.detalles["modo_consulta"] == "texto"
        assert resultado.candidatos[0].sku.sku == "SKU-1"
