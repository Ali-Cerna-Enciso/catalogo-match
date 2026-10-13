"""Tests end-to-end de `catalogo_match.cli` (todo en `tmp_path`, backend hash)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalogo_match.cli import main


@pytest.fixture
def indice_tmp(ruta_maestro: Path, tmp_path: Path) -> Path:
    """Índice real construido por el propio CLI (`--backend hash`, sin red)."""
    salida = tmp_path / "indice"
    codigo = main(
        ["indexar", "--maestro", str(ruta_maestro), "--salida", str(salida), "--backend", "hash"]
    )
    assert codigo == 0
    return salida


class TestIndexar:
    def test_indexar_devuelve_cero_y_guarda_el_indice(
        self, ruta_maestro: Path, tmp_path: Path, capsys
    ):
        salida = tmp_path / "indice"
        codigo = main(
            ["indexar", "--maestro", str(ruta_maestro), "--salida", str(salida), "--backend", "hash"]
        )
        assert codigo == 0
        assert (salida / "indice.json").exists()
        assert (salida / "vectores.npy").exists()

        meta = json.loads((salida / "indice.json").read_text(encoding="utf-8"))
        assert meta["n"] == 6
        assert meta["dim"] == 512
        assert meta["backend"]["nombre"] == "hash"
        assert "listo: 6 vectores" in capsys.readouterr().out

    def test_indexar_con_formato_plano(self, ruta_maestro: Path, tmp_path: Path):
        salida = tmp_path / "indice_plano"
        codigo = main(
            [
                "indexar",
                "--maestro",
                str(ruta_maestro),
                "--salida",
                str(salida),
                "--backend",
                "hash",
                "--formato-doc",
                "plano",
            ]
        )
        assert codigo == 0
        meta = json.loads((salida / "indice.json").read_text(encoding="utf-8"))
        assert meta["config"]["formato_documento"] == "plano"

    def test_con_imagenes_sin_modalidad_imagen_falla(self, ruta_maestro: Path, tmp_path: Path, capsys):
        codigo = main(
            [
                "indexar",
                "--maestro",
                str(ruta_maestro),
                "--salida",
                str(tmp_path / "indice"),
                "--backend",
                "hash",
                "--con-imagenes",
            ]
        )
        assert codigo == 1
        assert "con-imagenes" in capsys.readouterr().err

    def test_maestro_inexistente_devuelve_error(self, tmp_path: Path, capsys):
        codigo = main(
            [
                "indexar",
                "--maestro",
                str(tmp_path / "no_existe.csv"),
                "--salida",
                str(tmp_path / "indice"),
                "--backend",
                "hash",
            ]
        )
        assert codigo == 1
        assert "error:" in capsys.readouterr().err


class TestEmparejar:
    def test_escribe_jsonl_con_las_decisiones(
        self, indice_tmp: Path, ruta_lote: Path, tmp_path: Path, capsys
    ):
        salida = tmp_path / "resultados.jsonl"
        codigo = main(
            [
                "emparejar",
                "--indice",
                str(indice_tmp),
                "--lote",
                str(ruta_lote),
                "--salida",
                str(salida),
                "--sin-sustitutos",
            ]
        )
        assert codigo == 0

        lineas = [json.loads(linea) for linea in salida.read_text(encoding="utf-8").splitlines()]
        assert len(lineas) == 4
        assert {linea["id_fila"] for linea in lineas} == {"F1", "F2", "F3", "F4"}
        assert {linea["decision"] for linea in lineas} <= {"aceptado", "revisar", "no_se"}
        assert all(linea["sustitutos"] == [] for linea in lineas)
        assert lineas[0]["candidatos"][0]["sku"] == "SKU-002"
        assert lineas[0]["candidatos"][0]["puntaje"] > 0.7
        assert "aceptados:" in capsys.readouterr().out

    def test_sin_salida_solo_imprime(self, indice_tmp: Path, ruta_lote: Path, capsys):
        codigo = main(
            ["emparejar", "--indice", str(indice_tmp), "--lote", str(ruta_lote), "--mostrar", "1"]
        )
        assert codigo == 0
        salida = capsys.readouterr().out
        assert "SKU-002" in salida
        assert "AGOTADO" in salida  # el SKU-002 del maestro no tiene stock

    def test_emplea_los_sustitutos_curados(self, indice_tmp: Path, ruta_lote: Path, tmp_path: Path, capsys):
        curados = tmp_path / "sustitutos.csv"
        curados.write_text(
            "sku_origen,sku_sustituto,motivo\nSKU-002,SKU-001,mismo sabor\n", encoding="utf-8-sig"
        )
        codigo = main(
            [
                "emparejar",
                "--indice",
                str(indice_tmp),
                "--lote",
                str(ruta_lote),
                "--sustitutos-curados",
                str(curados),
                "--mostrar",
                "1",
            ]
        )
        assert codigo == 0
        assert "curado: mismo sabor" in capsys.readouterr().out

    def test_indice_inexistente_devuelve_error(self, ruta_lote: Path, tmp_path: Path, capsys):
        codigo = main(
            ["emparejar", "--indice", str(tmp_path / "no_existe"), "--lote", str(ruta_lote)]
        )
        assert codigo == 1
        assert "error:" in capsys.readouterr().err


class TestEvaluar:
    def test_escribe_el_informe_markdown(
        self, indice_tmp: Path, ruta_lote: Path, ruta_verdad: Path, tmp_path: Path, capsys
    ):
        informe = tmp_path / "reports" / "informe_eval.md"
        codigo = main(
            [
                "evaluar",
                "--indice",
                str(indice_tmp),
                "--lote",
                str(ruta_lote),
                "--verdad",
                str(ruta_verdad),
                "--informe",
                str(informe),
            ]
        )
        assert codigo == 0
        assert informe.exists()
        texto = informe.read_text(encoding="utf-8")
        assert "# Informe de evaluación" in texto
        assert "top1" in capsys.readouterr().out

    def test_exporta_json_y_pares(
        self, indice_tmp: Path, ruta_lote: Path, ruta_verdad: Path, tmp_path: Path
    ):
        informe = tmp_path / "informe.md"
        json_salida = tmp_path / "informe.json"
        pares = tmp_path / "pares.jsonl"
        codigo = main(
            [
                "evaluar",
                "--indice",
                str(indice_tmp),
                "--lote",
                str(ruta_lote),
                "--verdad",
                str(ruta_verdad),
                "--informe",
                str(informe),
                "--json-salida",
                str(json_salida),
                "--pares-salida",
                str(pares),
                "--calibrar",
            ]
        )
        assert codigo == 0
        datos = json.loads(json_salida.read_text(encoding="utf-8"))
        assert datos["n_consultas"] == 4
        assert datos["metricas"]["top1"] == pytest.approx(1.0)
        assert pares.exists()  # sin errores de top-1: JSONL vacío, pero creado

    def test_sin_verdad_es_error_de_uso(self, indice_tmp: Path, ruta_lote: Path, tmp_path: Path, capsys):
        # argparse exige --verdad, así que el proceso termina con SystemExit(2).
        with pytest.raises(SystemExit) as excinfo:
            main(["evaluar", "--indice", str(indice_tmp), "--lote", str(ruta_lote)])
        assert excinfo.value.code == 2
        assert "--verdad" in capsys.readouterr().err


class TestPlantillaConfig:
    def test_imprime_una_plantilla_toml(self, capsys):
        assert main(["plantilla-config"]) == 0
        salida = capsys.readouterr().out
        assert "umbral_alto" in salida
        assert "top_candidatos" in salida

    def test_la_plantilla_impresa_se_puede_cargar(self, tmp_path: Path, capsys):
        from catalogo_match.config import ConfigMatcher

        assert main(["plantilla-config"]) == 0
        ruta = tmp_path / "config.toml"
        ruta.write_text(capsys.readouterr().out, encoding="utf-8")
        assert ConfigMatcher.desde_toml(ruta) == ConfigMatcher()


class TestSinComando:
    def test_sin_subcomando_es_error_de_uso(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2


class TestServir:
    def test_fuera_de_loopback_sin_token_se_rechaza(self, indice_tmp: Path, monkeypatch):
        """Publicar en 0.0.0.0 sin CATALOGO_MATCH_TOKEN no debe arrancar."""
        monkeypatch.delenv("CATALOGO_MATCH_TOKEN", raising=False)
        codigo = main(
            ["servir", "--indice", str(indice_tmp), "--host", "0.0.0.0", "--port", "8123"]
        )
        assert codigo == 1
