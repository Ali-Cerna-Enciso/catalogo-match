"""Tests de la API HTTP local (`crear_app`). Requiere el extra [api]."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def cliente(indice_dir: Path):
    """TestClient de la app levantada sobre un índice real (backend hash)."""
    pytest.importorskip("fastapi", reason="falta el extra [api]: pip install -e '.[api]'")
    pytest.importorskip("httpx", reason="falta httpx (extra dev)")
    import warnings

    from catalogo_match.api import crear_app

    with warnings.catch_warnings():
        # starlette avisa que testclient con httpx está deprecado: no es asunto del test.
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

    return TestClient(crear_app(indice_dir))


class TestSalud:
    def test_salud_reporta_skus_dim_y_backend(self, cliente):
        respuesta = cliente.get("/v1/salud")
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["skus"] == 6
        assert datos["dim"] == 512
        assert datos["backend"] == "hash-ngrama3-512-v1"
        assert datos["modelo_cargado"] is True
        assert datos["indice_fecha"]  # el índice guarda su fecha de construcción
        assert datos["indice_edad_segundos"] >= 0

    def test_recargar_responde_estado(self, cliente):
        respuesta = cliente.post("/v1/recargar")
        assert respuesta.status_code == 200
        assert respuesta.json()["skus"] == 6

    def test_imagen_por_ruta_deshabilitada_por_defecto(self, cliente, monkeypatch):
        monkeypatch.delenv("CATALOGO_MATCH_DIR_IMAGENES", raising=False)
        respuesta = cliente.post("/v1/emparejar", json={"texto": "x", "imagen": "/etc/passwd"})
        assert respuesta.status_code == 400
        assert "deshabilitadas" in respuesta.json()["detail"]

    def test_imagen_por_ruta_fuera_del_directorio_se_rechaza(
        self, indice_dir, tmp_path, monkeypatch
    ):
        pytest.importorskip("fastapi", reason="falta el extra [api]")
        import warnings

        from fastapi.testclient import TestClient

        from catalogo_match.api import crear_app

        permitido = tmp_path / "imagenes"
        permitido.mkdir()
        monkeypatch.setenv("CATALOGO_MATCH_DIR_IMAGENES", str(permitido))
        monkeypatch.delenv("CATALOGO_MATCH_TOKEN", raising=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cliente = TestClient(crear_app(indice_dir))

        respuesta = cliente.post(
            "/v1/emparejar", json={"texto": "x", "imagen": str(tmp_path / "otro.jpg")}
        )
        assert respuesta.status_code == 400
        respuesta = cliente.post(
            "/v1/emparejar", json={"texto": "x", "imagen": str(permitido / "no.jpg")}
        )
        assert respuesta.status_code == 404
        (permitido / "ok.jpg").write_bytes(b"no-es-jpg-real")
        respuesta = cliente.post(
            "/v1/emparejar",
            json={"texto": "Yogurt Griego Fresa 900 g", "imagen": str(permitido / "ok.jpg")},
        )
        assert respuesta.status_code == 200  # el backend hash ignora la imagen

    def test_raiz_lista_los_endpoints(self, cliente):
        datos = cliente.get("/").json()
        assert datos["nombre"] == "catalogo-match"
        assert datos["skus"] == 6
        assert datos["backend"] == "hash-ngrama3-512-v1"
        assert "/v1/emparejar" in datos["endpoints"]


class TestEmparejar:
    def test_emparejar_devuelve_el_resultado(self, cliente):
        respuesta = cliente.post(
            "/v1/emparejar",
            json={"texto": "Yogurt Griego Fresa Aurora 900 g", "id_fila": "api-1"},
        )
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["id_fila"] == "api-1"
        assert datos["decision"] == "aceptado"
        assert datos["candidatos"][0]["sku"] == "SKU-002"

    def test_peticion_incompleta_devuelve_422(self, cliente):
        respuesta = cliente.post("/v1/emparejar", json={"id_fila": "solo-id"})
        assert respuesta.status_code == 422
        assert respuesta.json()["detail"][0]["loc"][-1] == "texto"

    def test_imagen_base64_inexistente_no_rompe(self, cliente):
        respuesta = cliente.post(
            "/v1/emparejar",
            json={"texto": "Yogurt Griego Fresa 1 kg", "imagen_base64": "aG9sYQ=="},
        )
        assert respuesta.status_code == 200  # la imagen no se puede decodificar como foto
