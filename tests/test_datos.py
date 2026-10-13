"""Tests de `catalogo_match.datos`: CSV con BOM, limpieza de códigos y parseo de columnas."""

from __future__ import annotations

from pathlib import Path

import pytest

from catalogo_match.datos import (
    cargar_lote,
    cargar_maestro,
    cargar_sustitutos,
    cargar_verdad,
    limpiar_codigo,
    texto_documento,
)
from catalogo_match.modelos import SKU
from catalogo_match.normaliza import Cantidad, compatibilidad_cantidad, parsear_cantidad

COLUMNAS_MAESTRO = [
    "sku",
    "nombre",
    "marca",
    "presentacion",
    "contenido_valor",
    "contenido_unidad",
    "categoria",
    "subcategoria",
    "codigo_barras",
    "precio_lista",
    "stock",
    "activo",
    "imagen",
]


def _fila(
    sku: str,
    nombre: str = "Producto",
    marca: str = "Marca",
    presentacion: str = "900 g",
    codigo_barras: str = "",
    precio: str = "9.90",
    stock: str = "10",
    activo: str = "1",
    imagen: str = "",
) -> list[str]:
    return [
        sku,
        nombre,
        marca,
        presentacion,
        "900",
        "g",
        "lacteos",
        "yogurt",
        codigo_barras,
        precio,
        stock,
        activo,
        imagen,
    ]


class TestLimpiarCodigo:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("7751234567890.0", "7751234567890"),
            ("7751234567890", "7751234567890"),
            (" 7751234567890 ", "7751234567890"),
            ("000123", "000123"),
            ("SKU-0099", "0099"),
            ("12.50", ""),  # decimal no interpretable: se descarta (antes se concatenaba)
            ("7.5", ""),
            ("", ""),
            ("abc", ""),
            (None, ""),
        ],
    )
    def test_limpia_y_preserva_ceros_a_la_izquierda(self, entrada, esperado):
        assert limpiar_codigo(entrada) == esperado


class TestCargarMaestro:
    def test_csv_con_bom_y_codigo_con_punto_decimal(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            COLUMNAS_MAESTRO,
            [
                _fila("0007", "Yogurt Griego Fresa", "Aurora", "900 g", "7751234567890.0", "9,90", "149"),
                _fila("0012", "Detergente Ropa", "Blanco", "4 kg", "000123", "35.0", "0"),
            ],
        )
        # El BOM tiene que ser real (los CSV del proyecto se leen en utf-8-sig).
        assert ruta.read_bytes().startswith(b"\xef\xbb\xbf")

        skus = cargar_maestro(ruta)
        assert [s.sku for s in skus] == ["0007", "0012"]  # ceros a la izquierda intactos
        assert skus[0].codigo_barras == "7751234567890"  # se quitó el ".0" de Excel
        assert skus[1].codigo_barras == "000123"
        assert skus[0].precio_lista == pytest.approx(9.9)
        assert skus[0].stock == 149
        assert skus[1].stock == 0
        assert skus[0].nombre == "Yogurt Griego Fresa"
        assert skus[0].contenido_valor == pytest.approx(900.0)
        assert skus[0].contenido_unidad == "g"
        assert skus[0].categoria == "lacteos"
        assert skus[0].subcategoria == "yogurt"

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [("", True), ("1", True), ("si", True), ("SI", True), ("no", False), ("0", False)],
    )
    def test_activo_parseado(self, escribir_csv, tmp_path: Path, valor, esperado):
        ruta = escribir_csv(
            tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [_fila("S1", activo=valor)]
        )
        assert cargar_maestro(ruta)[0].activo is esperado

    @pytest.mark.parametrize(("valor", "esperado"), [("", 0), ("0", 0), ("12", 12), ("3.9", 3)])
    def test_stock_parseado(self, escribir_csv, tmp_path: Path, valor, esperado):
        ruta = escribir_csv(
            tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [_fila("S1", stock=valor)]
        )
        assert cargar_maestro(ruta)[0].stock == esperado

    def test_agotado_deriva_de_stock(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            COLUMNAS_MAESTRO,
            [_fila("S1", stock="5"), _fila("S2", stock="0")],
        )
        con_stock, agotado = cargar_maestro(ruta)
        assert con_stock.agotado is False
        assert agotado.agotado is True

    def test_ignora_filas_sin_sku_y_duplicados(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            COLUMNAS_MAESTRO,
            [_fila("S1"), _fila("S1", nombre="Duplicado"), _fila("", nombre="Sin SKU")],
        )
        skus = cargar_maestro(ruta)
        assert [s.sku for s in skus] == ["S1"]
        assert skus[0].nombre == "Producto"

    def test_avisa_por_columnas_ausentes(self, escribir_csv, tmp_path: Path, capsys):
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            ["sku", "nombre"],
            [["S1", "Yogurt Griego Fresa"]],
        )
        skus = cargar_maestro(ruta)
        assert skus[0].marca == ""
        assert skus[0].presentacion == ""
        assert "aviso" in capsys.readouterr().err

    def test_error_sin_columna_sku(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(tmp_path / "maestro.csv", ["id", "nombre"], [["1", "x"]])
        with pytest.raises(ValueError, match="sku"):
            cargar_maestro(ruta)

    def test_error_si_no_hay_ningun_sku_valido(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [_fila("")])
        with pytest.raises(ValueError, match="ningún SKU válido"):
            cargar_maestro(ruta)

    def test_resuelve_imagen_existente_a_ruta_absoluta(self, escribir_csv, tmp_path: Path):
        (tmp_path / "imagenes").mkdir()
        (tmp_path / "imagenes" / "foto.png").write_bytes(b"png")
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            COLUMNAS_MAESTRO,
            [_fila("S1", imagen="imagenes/foto.png"), _fila("S2", imagen="imagenes/ausente.png")],
        )
        con_imagen, sin_imagen = cargar_maestro(ruta)
        assert Path(con_imagen.imagen).is_absolute()
        assert Path(con_imagen.imagen).name == "foto.png"
        assert sin_imagen.imagen == "imagenes/ausente.png"  # no existe: se deja igual

    def test_puede_no_resolver_imagenes(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "maestro.csv",
            COLUMNAS_MAESTRO,
            [_fila("S1", imagen="imagenes/foto.png")],
        )
        skus = cargar_maestro(ruta, resolver_imagenes=False)
        assert skus[0].imagen == "imagenes/foto.png"


class TestUnidadDeContenido:
    """`contenido_valor` se escala siempre a la unidad base (g / ml / un)."""

    def test_kg_se_escala_a_gramos(self, escribir_csv, tmp_path: Path):
        fila = [
            "S1", "Yogurt Griego", "Aurora", "1.5 kg", "1.5", "kg",
            "lacteos", "yogurt", "", "9.9", "10", "1", "",
        ]
        sku = cargar_maestro(escribir_csv(tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [fila]))[0]
        assert sku.contenido_unidad == "g"
        assert sku.contenido_valor == pytest.approx(1500.0)

    def test_mg_se_escala_a_gramos_y_es_comparable(self, escribir_csv, tmp_path: Path):
        fila = [
            "S1", "Yogurt Griego", "Aurora", "250 mg", "250", "mg",
            "lacteos", "yogurt", "", "9.9", "10", "1", "",
        ]
        sku = cargar_maestro(escribir_csv(tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [fila]))[0]
        assert sku.contenido_unidad == "g"
        assert sku.contenido_valor == pytest.approx(0.25)
        cantidad_sku = Cantidad(float(sku.contenido_valor), sku.contenido_unidad)
        assert compatibilidad_cantidad(parsear_cantidad("250 mg"), cantidad_sku) == (1.0, "igual")

    def test_litros_se_escalan_a_ml(self, escribir_csv, tmp_path: Path):
        fila = [
            "S1", "Jugo de Naranja", "Valle Verde", "1.5 l", "1.5", "l",
            "bebidas", "jugos", "", "6.9", "10", "1", "",
        ]
        sku = cargar_maestro(escribir_csv(tmp_path / "maestro.csv", COLUMNAS_MAESTRO, [fila]))[0]
        assert sku.contenido_unidad == "ml"
        assert sku.contenido_valor == pytest.approx(1500.0)


class TestCargarLote:
    def test_columnas_principales(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "lote.csv",
            ["id_fila", "texto", "proveedor", "codigo_barras", "imagen", "fuente", "dificultad"],
            [["F1", "YOG GRIEGO 900GR", "Distribuidora Andina", "7751234567890.0", "", "", ""]],
        )
        consulta = cargar_lote(ruta)[0]
        assert consulta.id_fila == "F1"
        assert consulta.texto == "YOG GRIEGO 900GR"
        assert consulta.proveedor == "Distribuidora Andina"
        assert consulta.codigo_barras == "7751234567890"
        assert consulta.fuente == "texto"  # vacío -> por defecto
        assert consulta.dificultad == ""

    def test_error_sin_columna_texto(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(tmp_path / "lote.csv", ["id_fila"], [["F1"]])
        with pytest.raises(ValueError, match="texto"):
            cargar_lote(ruta)


class TestCargarVerdad:
    def test_valor_vacio_indica_abstencion(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "verdad.csv",
            ["id_fila", "sku_correcto"],
            [["F1", "SKU-001"], ["F2", ""]],
        )
        assert cargar_verdad(ruta) == {"F1": "SKU-001", "F2": ""}

    def test_error_sin_columnas_requeridas(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(tmp_path / "verdad.csv", ["id_fila"], [["F1"]])
        with pytest.raises(ValueError, match="sku_correcto"):
            cargar_verdad(ruta)


class TestCargarSustitutos:
    def test_archivo_ausente_devuelve_lista_vacia(self, tmp_path: Path):
        assert cargar_sustitutos(tmp_path / "no_existe.csv") == []

    def test_pares_con_y_sin_motivo(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(
            tmp_path / "sustitutos.csv",
            ["sku_origen", "sku_sustituto", "motivo"],
            [["SKU-002", "SKU-001", "mismo sabor"], ["SKU-004", "SKU-005", ""]],
        )
        assert cargar_sustitutos(ruta) == [
            ("SKU-002", "SKU-001", "mismo sabor"),
            ("SKU-004", "SKU-005", ""),
        ]

    def test_error_sin_columnas_requeridas(self, escribir_csv, tmp_path: Path):
        ruta = escribir_csv(tmp_path / "sustitutos.csv", ["origen", "destino"], [["a", "b"]])
        with pytest.raises(ValueError, match="sku_origen"):
            cargar_sustitutos(ruta)


class TestTextoDocumento:
    def test_incluye_title_y_text_con_marca_y_ean(self, skus):
        documento = texto_documento(skus[0])
        assert documento.startswith("title: ")
        assert " | text: " in documento
        assert skus[0].nombre in documento
        assert "marca Aurora" in documento
        assert "EAN 7751234567890" in documento

    def test_formato_plano_es_solo_el_nombre_completo(self, skus):
        assert texto_documento(skus[0], formato="plano") == skus[0].nombre_completo

    def test_sin_metadatos_usa_none(self):
        documento = texto_documento(SKU(sku="S1", nombre="Producto"))
        assert documento == "title: Producto | text: none"
