"""Tests de `catalogo_match.backends` (hash offline) y de `catalogo_match.indice`."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from catalogo_match.backends import ErrorBackend, backend_desde_meta, crear_backend
from catalogo_match.backends.base import normalizar_l2
from catalogo_match.config import ConfigMatcher
from catalogo_match.indice import ARCHIVO_META, ARCHIVO_VECTORES, Indice, construir_indice
from catalogo_match.modelos import SKU


class TestBackendHash:
    @pytest.mark.parametrize("alias", ["hash", "offline", "determinista", "HASH", " Hash "])
    def test_alias_reconocidos(self, alias):
        assert crear_backend(alias).nombre == "hash"

    def test_backend_desconocido_lanza_error(self):
        with pytest.raises(ErrorBackend, match="Backend desconocido"):
            crear_backend("gemma-magico")

    def test_dim_por_defecto_y_huella_estable(self):
        backend = crear_backend("hash")
        assert backend.dim == 512
        assert backend.huella() == "hash-ngrama3-512-v1"

    def test_dim_configurable_cambia_la_huella(self):
        backend = crear_backend("hash", dim=64)
        assert backend.dim == 64
        assert backend.huella() == "hash-ngrama3-64-v1"
        assert backend.encode_textos(["x"]).shape == (1, 64)

    def test_es_determinista(self):
        a = crear_backend("hash").encode_textos(["Yogurt Griego Fresa 900 g"])
        b = crear_backend("hash").encode_textos(["Yogurt Griego Fresa 900 g"])
        assert np.array_equal(a, b)

    def test_vectores_normalizados_l2(self):
        vectores = crear_backend("hash").encode_textos(
            ["Yogurt Griego Fresa 900 g", "Detergente Ropa Bolsa 4 kg"]
        )
        assert np.allclose(np.linalg.norm(vectores, axis=1), 1.0, atol=1e-6)

    def test_texto_vacio_da_vector_nulo(self):
        vector = crear_backend("hash").encode_textos([""])[0]
        assert np.allclose(vector, 0.0)

    def test_lista_vacia_da_matriz_vacia(self):
        assert crear_backend("hash").encode_textos([]).shape == (0, 512)

    def test_no_procesa_imagenes(self):
        with pytest.raises(NotImplementedError):
            crear_backend("hash").encode_multimodal([{"texto": "x", "imagen": None}])

    def test_descripcion_para_el_indice(self):
        descripcion = crear_backend("hash").descripcion()
        assert descripcion["nombre"] == "hash"
        assert descripcion["dim"] == 512
        assert descripcion["modalidades"] == ["texto"]


class TestBackendDesdeMeta:
    def test_reconstruye_el_hash_con_su_dim(self, indice):
        backend = backend_desde_meta(indice.meta)
        assert backend.nombre == "hash"
        assert backend.dim == indice.dim
        assert backend.huella() == indice.huella

    def test_permite_overrides(self, indice):
        assert backend_desde_meta(indice.meta, dim=64).dim == 64

    def test_meta_vacia_cae_en_hash_por_defecto(self):
        assert backend_desde_meta({}).nombre == "hash"


class TestNormalizarL2:
    def test_filas_nulas_no_producen_nan(self):
        matriz = normalizar_l2(np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32))
        assert np.allclose(matriz[0], [0.6, 0.8])
        assert not np.isnan(matriz).any()


class TestConstruirIndice:
    def test_dim_n_y_metadatos(self, skus, embedder):
        indice = construir_indice(skus, embedder, ConfigMatcher())
        assert indice.n == 6
        assert indice.dim == 512
        assert indice.vectores.shape == (6, 512)
        assert indice.vectores.dtype == np.float32
        assert indice.huella == "hash-ngrama3-512-v1"
        assert indice.meta["con_imagenes"] is False
        assert indice.meta["config"]["formato_documento"] == "titulo_texto"
        assert indice.sku_por_id()["SKU-003"].marca == "Blanco"

    def test_sin_skus_lanza_error(self, embedder):
        with pytest.raises(ValueError, match="No hay SKUs para indexar"):
            construir_indice([], embedder)

    @pytest.mark.parametrize("formato", ["titulo_texto", "plano"])
    def test_formato_documento_configurable(self, skus, embedder, formato):
        indice = construir_indice(skus, embedder, ConfigMatcher(formato_documento=formato))
        assert indice.meta["config"]["formato_documento"] == formato

    def test_con_imagenes_pero_backend_solo_texto_usa_texto(self, skus, embedder):
        """El backend hash no tiene modalidad imagen: se indexa igual, solo texto."""
        indice = construir_indice(skus, embedder, ConfigMatcher(), con_imagenes=True)
        assert indice.n == 6
        assert indice.meta["con_imagenes"] is True


class TestPersistenciaIndice:
    def test_roundtrip_guardar_y_cargar(self, indice, tmp_path: Path):
        destino = indice.guardar(tmp_path / "indice")
        assert (destino / ARCHIVO_VECTORES).exists()
        assert (destino / ARCHIVO_META).exists()

        recargado = Indice.cargar(destino)
        assert recargado.n == indice.n == 6
        assert recargado.dim == indice.dim == 512
        assert recargado.huella == indice.huella
        assert recargado.skus == indice.skus
        assert np.allclose(recargado.vectores, indice.vectores)
        assert recargado.vectores.dtype == np.float32

    def test_meta_json_es_utf8_con_acentos(self, indice, tmp_path: Path):
        destino = indice.guardar(tmp_path / "indice")
        crudo = (destino / ARCHIVO_META).read_text(encoding="utf-8")
        crudo.encode("utf-8")  # debe poder escribirse como utf-8
        meta = json.loads(crudo)
        assert meta["version"] == 1
        assert meta["n"] == 6
        assert meta["dim"] == 512

    def test_rechaza_version_no_soportada(self, indice, tmp_path: Path):
        destino = indice.guardar(tmp_path / "indice")
        meta = json.loads((destino / ARCHIVO_META).read_text(encoding="utf-8"))
        meta["version"] = 99
        (destino / ARCHIVO_META).write_text(json.dumps(meta), encoding="utf-8")

        with pytest.raises(ValueError, match="no soportada"):
            Indice.cargar(destino)

    def test_rechaza_indice_inconsistente(self, indice, tmp_path: Path):
        destino = indice.guardar(tmp_path / "indice")
        meta = json.loads((destino / ARCHIVO_META).read_text(encoding="utf-8"))
        meta["skus"] = meta["skus"][:-1]  # 5 SKUs vs 6 vectores
        (destino / ARCHIVO_META).write_text(json.dumps(meta), encoding="utf-8")

        with pytest.raises(ValueError, match="inconsistente"):
            Indice.cargar(destino)


class TestTopYSimilitudes:
    def test_top_devuelve_k_ordenado(self, indice, embedder):
        vector = embedder.encode_textos(["Detergente Ropa Bolsa Blanco 4 kg"])[0]
        indices, similitudes = indice.top(vector, 3)
        assert len(indices) == 3
        assert list(similitudes) == sorted(similitudes, reverse=True)
        assert indice.skus[int(indices[0])].sku == "SKU-003"

    def test_top_pide_mas_que_el_catalogo(self, indice, embedder):
        vector = embedder.encode_textos(["Detergente"])[0]
        indices, similitudes = indice.top(vector, 99)
        assert len(indices) == indice.n
        assert len(similitudes) == indice.n

    def test_similitudes_es_producto_punto(self, indice, embedder):
        vector = embedder.encode_textos(["Arroz Extra Grano Campos 5 kg"])[0]
        assert np.allclose(indice.similitudes(vector), indice.vectores @ vector)

    def test_indice_vacio_tiene_dim_cero_y_top_vacio(self, embedder):
        vacio = Indice(skus=[], vectores=np.zeros((0, 8), dtype=np.float32), meta={})
        assert vacio.dim == 0
        assert vacio.n == 0
        assert vacio.huella == "desconocida"
        indices, similitudes = vacio.top(embedder.encode_textos(["x"])[0], 3)
        assert indices.size == 0
        assert similitudes.size == 0

    def test_indice_vacio_con_vectores_de_una_fila(self, embedder):
        """Caso degenerado: hay vector pero no SKUs (dim se lee de la matriz)."""
        indice = Indice(
            skus=[SKU(sku="S1", nombre="x")], vectores=np.zeros((1, 8), dtype=np.float32), meta={}
        )
        assert indice.n == 1
        assert indice.dim == 8
