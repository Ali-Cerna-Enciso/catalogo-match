"""Tests de `catalogo_match.normaliza`: acentos, abreviaturas, cantidades y similitud."""

from __future__ import annotations

import pytest

from catalogo_match.normaliza import (
    ABREVIATURAS,
    Cantidad,
    compatibilidad_cantidad,
    marca_en_texto,
    normalizar,
    parsear_cantidad,
    similitud_textos,
    sin_acentos,
    tokenizar,
)


class TestNormalizar:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Café ÑANDÚ Ácido", "cafe nandu acido"),
            ("Piña con Ñ", "pina con n"),
            ("  YOGURT   GRIEGO  ", "yogurt griego"),
            ("", ""),
        ],
    )
    def test_minusculas_sin_acentos_y_espacios_colapsados(self, entrada, esperado):
        assert normalizar(entrada) == esperado

    def test_sin_acentos_preserva_el_resto(self):
        assert sin_acentos("Ñandú, 1.5 kg") == "Nandu, 1.5 kg"
        assert sin_acentos("") == ""

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("1000gr", "1000 gr"),
            ("4x100", "4 x 100"),
            ("1,5 kg", "1.5 kg"),
            ("YOG × 12", "yog x 12"),
        ],
    )
    def test_separa_digito_unidad_y_normaliza_simbolos(self, entrada, esperado):
        assert normalizar(entrada) == esperado


class TestTokenizar:
    @pytest.mark.parametrize(
        ("token", "expandido"),
        [
            ("YOG", "yogur"),
            ("YOGURT", "yogur"),
            ("DETERG", "detergente"),
            ("DET", "detergente"),
            ("CHOC", "chocolate"),
            ("GALL", "galleta"),
            ("ACOND", "acondicionador"),
        ],
    )
    def test_expande_abreviaturas_comerciales(self, token, expandido):
        assert tokenizar(token) == [expandido]
        assert ABREVIATURAS[token.lower()] == expandido

    def test_quita_palabras_vacias(self):
        assert tokenizar("YOGURT DE LA FRESA CON AZUCAR") == ["yogur", "fresa", "azucar"]

    def test_conserva_numeros_y_unidades(self):
        assert tokenizar("YOG 1KG") == ["yogur", "1", "kg"]


class TestParsearCantidad:
    @pytest.mark.parametrize(
        ("texto", "valor", "unidad", "unidades"),
        [
            ("1000gr", 1000.0, "g", 1),
            ("1000 gr", 1000.0, "g", 1),
            ("4 x 100 g", 400.0, "g", 4),
            ("4 X 100 G", 400.0, "g", 4),
            ("6 x 1.5 L", 9000.0, "ml", 6),
            ("1,5 kg", 1500.0, "g", 1),
            ("1.5 kg", 1500.0, "g", 1),
            ("1 kilo", 1000.0, "g", 1),
            ("250 mg", 0.25, "g", 1),
            ("X12", 12.0, "un", 12),
            ("x 12", 12.0, "un", 12),
            ("12 x", 12.0, "un", 12),
            ("docena", 12.0, "un", 12),
            ("1 l", 1000.0, "ml", 1),
            ("1 L", 1000.0, "ml", 1),
            ("500 ml", 500.0, "ml", 1),
            ("3 x 170 g", 510.0, "g", 3),
        ],
    )
    def test_cantidad_normalizada_a_unidad_base(self, texto, valor, unidad, unidades):
        cantidad = parsear_cantidad(texto)
        assert cantidad is not None
        assert cantidad.valor == pytest.approx(valor)
        assert cantidad.unidad == unidad
        assert cantidad.unidades == unidades

    @pytest.mark.parametrize("texto", ["", "   ", "sin cantidad", "yogurt griego"])
    def test_devuelve_none_sin_pista_de_cantidad(self, texto):
        assert parsear_cantidad(texto) is None

    def test_descripcion_legible(self):
        assert parsear_cantidad("4 x 100 g").descripcion == "4 x 100 g"
        assert parsear_cantidad("X12").descripcion == "x12"

    def test_str_de_cantidad_usa_kg_y_l_cuando_corresponde(self):
        assert str(Cantidad(1500.0, "g")) == "1.5 kg"
        assert str(Cantidad(1000.0, "ml")) == "1 l"
        assert str(Cantidad(12.0, "un")) == "12 un"


class TestFraccion:
    """Fracciones simples ("1/2 kilo" -> 500 g).

    Este caso ya estuvo roto (`normalizar()` borraba la "/" antes de `_FRACCION`);
    quedan estos tests como guardia de regresión.
    """

    @pytest.mark.parametrize(
        ("texto", "valor", "unidad"),
        [
            ("1/2 kilo", 500.0, "g"),
            ("3/4 l", 750.0, "ml"),
            ("1/4 kg", 250.0, "g"),
            ("1/2 docena", 6.0, "un"),
        ],
    )
    def test_fraccion_se_convierte_a_unidad_base(self, texto, valor, unidad):
        cantidad = parsear_cantidad(texto)
        assert cantidad is not None
        assert cantidad.valor == pytest.approx(valor)
        assert cantidad.unidad == unidad

    def test_la_barra_sobrevive_a_normalizar(self):
        assert normalizar("1/2 kilo") == "1/2 kilo"
        assert normalizar("3/4 L") == "3/4 l"


class TestCompatibilidadCantidad:
    @pytest.mark.parametrize(
        ("a", "b", "esperado", "motivo"),
        [
            ("900 g", "900 g", 1.0, "igual"),
            ("2 x 100 g", "200 g", 1.0, "igual"),
            ("1 kg", "1000 g", 1.0, "igual"),
            ("600 g", "900 g", 0.6667, "similar"),
            ("400 g", "5000 g", 0.08, "distinta"),
        ],
    )
    def test_similitud_entre_cantidades(self, a, b, esperado, motivo):
        similitud, detalle = compatibilidad_cantidad(parsear_cantidad(a), parsear_cantidad(b))
        assert similitud == pytest.approx(esperado, abs=1e-4)
        assert detalle == motivo

    def test_unidades_no_comparables_kg_vs_l(self):
        similitud, motivo = compatibilidad_cantidad(
            parsear_cantidad("1 kg"), parsear_cantidad("1 l")
        )
        assert similitud is None
        assert motivo == "unidades_no_comparables"

    @pytest.mark.parametrize(
        ("a", "b"),
        [(None, "1 kg"), ("1 kg", None), (None, None)],
    )
    def test_sin_dato_cuando_falta_una_cantidad(self, a, b):
        cantidad_a = parsear_cantidad(a) if a else None
        cantidad_b = parsear_cantidad(b) if b else None
        assert compatibilidad_cantidad(cantidad_a, cantidad_b) == (None, "sin_dato")


class TestSimilitudYMarcas:
    def test_textos_identicos_puntuan_mas_que_textos_distintos(self):
        iguales = similitud_textos("Yogurt Griego Fresa Aurora 900 g", "YOGURT GRIEGO FRESA AURORA 900G")
        distintos = similitud_textos("Yogurt Griego Fresa Aurora 900 g", "Detergente Ropa Bolsa 4 kg")
        assert iguales == pytest.approx(1.0)
        assert distintos < iguales
        assert 0.0 <= distintos < 0.5

    def test_es_simetrica_y_acotada(self):
        a, b = "Arroz Extra Grano Campos 5 kg", "ARROZ EXTRA GRANO CAMPO VERDE 5KG"
        assert similitud_textos(a, b) == similitud_textos(b, a)
        assert 0.0 <= similitud_textos(a, b) <= 1.0

    def test_texto_vacio_puntua_cero(self):
        assert similitud_textos("", "Yogurt Griego") == 0.0
        assert similitud_textos("Yogurt Griego", "") == 0.0

    def test_marca_presente_y_ausente(self):
        assert marca_en_texto("YOG GRIEGO FRESA AURORA 1KG", "Aurora") is True
        assert marca_en_texto("YOG GRIEGO FRESA AURORA 1KG", "AURORA") is True
        assert marca_en_texto("YOG GRIEGO FRESA AURORA 1KG", "Gloria") is False
        assert marca_en_texto("Arroz Extra Grano Campo Verde 5 kg", "Campo Verde") is True

    def test_marca_vacia_no_coincide(self):
        assert marca_en_texto("Yogurt Griego", "") is False
        assert marca_en_texto("", "Aurora") is False


class TestDiccionarioControlado:
    """El diccionario no debe colapsar productos distintos."""

    def test_refresco_no_se_colapsa_con_gaseosa(self):
        tokens = tokenizar("REFRESCO COLA 1.5L")
        assert "refresco" in tokens
        assert "gaseosa" not in tokens

    def test_gaseosa_sigue_expandiendo_su_abreviatura(self):
        assert "gaseosa" in tokenizar("GASE COLA 1.5L")
