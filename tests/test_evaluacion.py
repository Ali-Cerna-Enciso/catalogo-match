"""Tests de `catalogo_match.evaluacion`: métricas, baseline, calibración e informes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalogo_match.evaluacion import (
    FilaEvaluada,
    _cortes_honestos,
    calibrar_umbrales,
    evaluar,
)
from catalogo_match.modelos import SKU, Candidato, Consulta, Resultado

CLAVES_METRICAS = {
    "n",
    "top1",
    "top3",
    "mrr",
    "cobertura",
    "tasa_no_se",
    "precision_aceptado",
    "abstencion_falsa",
    "sin_match_ok",
    "sin_match_aceptado",
}


def _fila(puntaje: float, verdad: str, sku_top1: str = "SKU-001", decision: str = "aceptado") -> FilaEvaluada:
    consulta = Consulta(id_fila="f", texto="texto")
    candidato = Candidato(sku=SKU(sku=sku_top1, nombre="Producto"), puntaje=puntaje)
    return FilaEvaluada(consulta, verdad, Resultado(consulta, [candidato], decision))


class TestEvaluarConVerdadConocida:
    def test_set_trivial_da_top1_perfecto(self, emparejador, consultas, verdad):
        informe = evaluar(emparejador, consultas, verdad)
        assert informe.metricas["top1"] == pytest.approx(1.0)
        assert informe.metricas["top3"] == pytest.approx(1.0)
        assert informe.metricas["mrr"] == pytest.approx(1.0)
        assert informe.metricas["precision_aceptado"] == pytest.approx(1.0)
        assert informe.metricas["abstencion_falsa"] == pytest.approx(0.0)
        assert informe.ejemplos_error == []
        assert informe.n_consultas == 4
        assert informe.n_maestro == 6
        assert set(informe.metricas) == CLAVES_METRICAS
        assert informe.backend["nombre"] == "hash"
        assert informe.config["umbral_alto"] == pytest.approx(0.78)

    def test_fila_sin_match_real_cuenta_en_sin_match_ok(self, emparejador, consultas, verdad):
        informe = evaluar(emparejador, consultas, verdad)
        assert verdad["F3"] == ""  # el lote trae una fila sin match posible
        assert informe.metricas["sin_match_ok"] == pytest.approx(1.0)
        assert informe.metricas["sin_match_aceptado"] == pytest.approx(0.0)
        assert informe.metricas["cobertura"] == pytest.approx(0.75)
        assert informe.metricas["tasa_no_se"] == pytest.approx(0.25)

    def test_agrupacion_por_dificultad_y_fuente(self, emparejador, consultas, verdad):
        informe = evaluar(emparejador, consultas, verdad)
        assert set(informe.por_dificultad) == {"facil", "media", "dificil"}
        assert informe.por_dificultad["facil"]["n"] == 2
        assert informe.por_dificultad["facil"]["top1"] == pytest.approx(1.0)
        assert set(informe.por_fuente) == {"texto"}
        assert informe.por_fuente["texto"]["n"] == 4

    def test_metricas_de_sustitutos_sobre_agotados(self, emparejador, consultas, verdad):
        informe = evaluar(emparejador, consultas, verdad)
        assert informe.sustitutos["n_agotados"] == 2  # F1 -> SKU-002 y F4 -> SKU-004
        assert informe.sustitutos["tasa_propuesto"] == pytest.approx(1.0)
        assert informe.sustitutos["tasa_misma_categoria"] == pytest.approx(1.0)

    def test_baseline_difuso_comparable(self, emparejador, consultas, verdad):
        informe = evaluar(emparejador, consultas, verdad)
        assert informe.baseline["n"] == 3
        assert informe.baseline["difuso_top1"] == pytest.approx(1.0)

    def test_baseline_se_puede_desactivar(self, emparejador, consultas, verdad):
        assert evaluar(emparejador, consultas, verdad, con_baseline=False).baseline == {}

    def test_calibracion_opcional(self, emparejador, consultas, verdad):
        sin_calibrar = evaluar(emparejador, consultas, verdad)
        assert sin_calibrar.calibracion is None

        calibrado = evaluar(emparejador, consultas, verdad, calibrar=True)
        assert calibrado.calibracion is not None
        assert "sugerencia" in calibrado.calibracion or "umbral_alto_sugerido" in calibrado.calibracion


class TestParesDeEntrenamiento:
    def test_escribe_jsonl_con_consulta_positivo_y_negativos(
        self, emparejador, consultas, verdad, tmp_path: Path
    ):
        # F2 tiene como verdad un SKU equivocado a propósito: fuerza un error del top-1.
        verdad_erronea = {**verdad, "F2": "SKU-001"}
        destino = tmp_path / "salidas" / "pares.jsonl"

        informe = evaluar(emparejador, consultas, verdad_erronea, pares_salida=destino)

        assert destino.exists()
        lineas = [json.loads(linea) for linea in destino.read_text(encoding="utf-8").splitlines()]
        assert len(lineas) == 1
        par = lineas[0]
        assert set(par) == {"consulta", "positivo", "negativos"}
        assert par["consulta"] == "Detergente Ropa Bolsa Blanco 4 kg"
        assert par["positivo"] == "SKU-001"
        assert par["negativos"][0] == "SKU-003"  # el top-1 real, como negativo duro
        assert "SKU-001" not in par["negativos"]
        assert len(par["negativos"]) <= 3
        assert informe.metricas["top1"] < 1.0
        assert [e["verdad"] for e in informe.ejemplos_error] == ["SKU-001"]

    def test_sin_errores_el_archivo_queda_vacio(self, emparejador, consultas, verdad, tmp_path: Path):
        destino = tmp_path / "pares.jsonl"
        evaluar(emparejador, consultas, verdad, pares_salida=destino)
        assert destino.exists()
        assert destino.read_text(encoding="utf-8") == ""


class TestInformeMarkdown:
    def test_crea_el_archivo_con_el_titulo_y_las_secciones(self, emparejador, consultas, verdad, tmp_path):
        informe = evaluar(emparejador, consultas, verdad, calibrar=True)
        ruta = informe.escribir_markdown(tmp_path / "reports" / "informe_eval.md")

        assert ruta.exists()
        texto = ruta.read_text(encoding="utf-8")
        assert "# Informe de evaluación" in texto
        assert "## Resultados principales" in texto
        assert "## Por dificultad del lote" in texto
        assert "## Por fuente" in texto
        assert "Top-1 correcto" in texto
        assert "Backend: `hash-ngrama3-512-v1`" in texto
        assert "no" in texto and "representa la calidad de EmbeddingGemma 2" in texto
        assert "usa `--backend gemma`" in texto  # avisa que el backend offline no es el modelo real

    def test_a_dict_incluye_las_claves_del_informe(self, emparejador, consultas, verdad):
        datos = evaluar(emparejador, consultas, verdad).a_dict()
        assert set(datos) == {
            "fecha",
            "n_consultas",
            "n_maestro",
            "segundos",
            "backend",
            "config",
            "metricas",
            "por_dificultad",
            "por_fuente",
            "baseline",
            "sustitutos",
            "calibracion",
            "ejemplos_error",
            "cortes",
        }
        json.dumps(datos, ensure_ascii=False)  # debe ser serializable a JSON


class TestCortesHonestos:
    """Cortes que evitan inflar la lectura: sin atajo de EAN y errores de presentación."""

    def test_excluye_filas_resueltas_por_ean(self):
        skus = {
            "SKU-001": SKU(sku="SKU-001", nombre="Yogurt Fresa", marca="Aurora"),
            "SKU-002": SKU(sku="SKU-002", nombre="Yogurt Fresa", marca="Aurora"),
            "SKU-003": SKU(sku="SKU-003", nombre="Detergente", marca="LimpiaMax"),
        }
        por_ean = _fila(1.0, "SKU-001")
        por_ean.resultado.detalles["codigo_barras"] = "coincidencia exacta"
        acierto = _fila(0.9, "SKU-001")
        envase = _fila(0.9, "SKU-002")  # aceptó otro envase de la misma línea: error caro

        cortes = _cortes_honestos([por_ean, acierto, envase], skus)

        assert cortes["n_resueltas_por_barras"] == 1
        assert cortes["n_sin_barras"] == 2
        assert cortes["top1_sin_barras"] == pytest.approx(0.5)
        assert cortes["errores_presentacion"] == 1
        assert cortes["tasa_errores_presentacion"] == pytest.approx(1 / 3)
        assert cortes["presentacion_incorrecta_aceptada"] == 1
        assert cortes["tasa_presentacion_aceptada"] == pytest.approx(1 / 3)

    def test_sin_filas_devuelve_none_en_top1(self):
        cortes = _cortes_honestos([], {})
        assert cortes["n_total"] == 0
        assert cortes["top1_sin_barras"] is None


class TestCalibrarUmbrales:
    def test_umbral_sugerido_baja_mientras_la_precision_aguante(self):
        filas = [_fila(0.90, "SKU-001") for _ in range(5)]
        filas.append(_fila(0.50, "SKU-002", sku_top1="SKU-003"))  # error con puntaje bajo

        calibracion = calibrar_umbrales(filas, meta_precision=0.95, min_aceptados=5)

        # `calibrar_umbrales` maximiza la cobertura: con este lote, cualquier umbral
        # entre 0.51 y 0.90 acepta las mismas 5 filas con precisión 1.0 y el barrido
        # se queda con el PRIMERO (el más laxo), no con el más exigente.
        assert calibracion is not None
        assert calibracion["umbral_alto_sugerido"] == pytest.approx(0.51)
        assert calibracion["umbral_bajo_sugerido"] == pytest.approx(0.36)
        assert calibracion["aceptados_en_evaluacion"] == 5
        assert calibracion["precision_en_aceptados"] == pytest.approx(1.0)

    def test_las_filas_sin_match_tambien_cuentan_como_error(self):
        """Aceptar un 'no existe' baja la precisión: la calibración debe considerarlo."""
        filas = [_fila(0.95, "SKU-001") for _ in range(5)]
        filas.append(_fila(0.85, ""))  # sin match real, pero puntaje alto

        calibracion = calibrar_umbrales(filas, meta_precision=0.95, min_aceptados=5)

        # Con umbral <= 0.85 entra la fila fantasma (precisión 5/6 = 0.83 < 0.95);
        # a partir de 0.86 solo quedan los 5 aciertos -> umbral sugerido 0.86.
        assert calibracion is not None
        assert calibracion["umbral_alto_sugerido"] == pytest.approx(0.86)
        assert calibracion["aceptados_en_evaluacion"] == 5
        assert calibracion["precision_en_aceptados"] == pytest.approx(1.0)

    def test_precision_insuficiente_no_sugiere_nada_mejor(self):
        """Con errores repartidos, la precisión nunca llega a la meta."""
        filas = [_fila(0.90, "SKU-001") for _ in range(5)]
        filas.append(_fila(0.95, "SKU-002", sku_top1="SKU-003"))

        calibracion = calibrar_umbrales(filas, meta_precision=0.95, min_aceptados=5)
        assert calibracion == {"sugerencia": "sin combinación que cumpla la precisión objetivo"}

    def test_sin_suficientes_aceptados_avisa(self):
        calibracion = calibrar_umbrales([_fila(0.99, "SKU-001")], min_aceptados=5)
        assert calibracion == {"sugerencia": "sin combinación que cumpla la precisión objetivo"}

    @pytest.mark.parametrize(
        "filas",
        [
            [],
            [_fila(0.9, "")],  # sin verdad no se puede calibrar nada
        ],
    )
    def test_sin_filas_utiles_devuelve_none(self, filas):
        assert calibrar_umbrales(filas) is None
