"""Tests de `catalogo_match.config`: valores por defecto, TOML y copias."""

from __future__ import annotations

from pathlib import Path

import pytest

from catalogo_match.config import PLANTILLA_TOML, ConfigMatcher


class TestValoresPorDefecto:
    def test_umbrales_y_pesos_razonables(self):
        cfg = ConfigMatcher()
        assert 0.0 < cfg.umbral_bajo < cfg.umbral_alto <= 1.0
        assert cfg.top_candidatos >= cfg.top_resultados >= 1
        assert cfg.peso_embedding + cfg.peso_lexico + cfg.peso_cantidad == pytest.approx(1.0)
        assert cfg.peso_embedding > cfg.peso_lexico > cfg.peso_cantidad > 0.0
        assert cfg.bonus_marca == pytest.approx(0.05)
        assert cfg.formato_documento == "titulo_texto"
        assert cfg.max_sustitutos >= 1
        assert cfg.usar_prefijos is True
        assert cfg.con_imagenes_maestro is False

    def test_truncar_dim_es_none_por_defecto(self):
        assert ConfigMatcher().truncar_dim is None
        assert ConfigMatcher(truncar_a=512).truncar_dim == 512

    def test_a_dict_es_serializable(self):
        datos = ConfigMatcher().a_dict()
        assert datos["umbral_alto"] == pytest.approx(0.78)
        assert set(datos) == {campo for campo in ConfigMatcher().__dataclass_fields__}


class TestDesdeToml:
    def test_lee_un_toml_temporal(self, tmp_path: Path):
        ruta = tmp_path / "matcher.toml"
        ruta.write_text(
            """
            top_resultados = 1
            umbral_alto = 0.9
            umbral_bajo = 0.4
            formato_documento = "plano"
            usar_prefijos = false
            """,
            encoding="utf-8",
        )
        cfg = ConfigMatcher.desde_toml(ruta)
        assert cfg.top_resultados == 1
        assert cfg.umbral_alto == pytest.approx(0.9)
        assert cfg.umbral_bajo == pytest.approx(0.4)
        assert cfg.formato_documento == "plano"
        assert cfg.usar_prefijos is False
        # lo que no aparece en el TOML se queda con el valor por defecto
        assert cfg.peso_embedding == pytest.approx(0.66)
        assert cfg.top_candidatos == 25

    def test_ignora_claves_desconocidas_y_none(self, tmp_path: Path):
        ruta = tmp_path / "matcher.toml"
        ruta.write_text(
            'umbral_alto = 0.7\nclave_inventada = "x"\npeso_lexico = 0.5\n',
            encoding="utf-8",
        )
        cfg = ConfigMatcher.desde_toml(ruta)
        assert cfg.umbral_alto == pytest.approx(0.7)
        assert cfg.peso_lexico == pytest.approx(0.5)
        assert not hasattr(cfg, "clave_inventada")

    def test_archivo_inexistente_falla(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            ConfigMatcher.desde_toml(tmp_path / "no_existe.toml")

    def test_la_plantilla_es_un_toml_valido_con_los_defaults(self, tmp_path: Path):
        """`plantilla-config` debe imprimir un TOML que reproduce los valores por defecto."""
        ruta = tmp_path / "plantilla.toml"
        ruta.write_text(PLANTILLA_TOML, encoding="utf-8")
        assert ConfigMatcher.desde_toml(ruta) == ConfigMatcher()

    def test_la_plantilla_documenta_las_claves(self):
        for clave in ConfigMatcher().__dataclass_fields__:
            assert clave in PLANTILLA_TOML


class TestCopias:
    def test_con_cambia_solo_lo_indicado(self):
        cfg = ConfigMatcher()
        otro = cfg.con(umbral_alto=0.9, top_resultados=1)
        assert otro.umbral_alto == pytest.approx(0.9)
        assert otro.top_resultados == 1
        assert otro.umbral_bajo == cfg.umbral_bajo
        assert cfg.umbral_alto == pytest.approx(0.78)  # el original no cambia

    def test_con_ignora_los_none(self):
        cfg = ConfigMatcher(umbral_alto=0.5, umbral_bajo=0.4)
        assert cfg.con(umbral_alto=None).umbral_alto == pytest.approx(0.5)

    def test_desde_dict_ignora_desconocidas(self):
        cfg = ConfigMatcher.desde_dict({"umbral_alto": 0.65, "no_existe": 1})
        assert cfg.umbral_alto == pytest.approx(0.65)
        assert cfg.umbral_bajo == pytest.approx(0.60)


class TestValidacion:
    """El camino de configuración (TOML/desde_dict) valida coherencia."""

    def test_umbrales_invertidos_fallan(self):
        with pytest.raises(ValueError, match="umbrales incoherentes"):
            ConfigMatcher.desde_dict({"umbral_alto": 0.5, "umbral_bajo": 0.9})

    def test_pesos_negativos_fallan(self):
        with pytest.raises(ValueError, match="no puede ser negativo"):
            ConfigMatcher.desde_dict({"peso_embedding": -0.1})

    def test_suma_de_pesos_fuera_de_rango_falla(self):
        with pytest.raises(ValueError, match="suma de pesos"):
            ConfigMatcher.desde_dict(
                {"peso_embedding": 1.0, "peso_lexico": 1.0, "peso_cantidad": 1.0}
            )

    def test_top_candidatos_menor_que_resultados_falla(self):
        with pytest.raises(ValueError, match="top_candidatos"):
            ConfigMatcher.desde_dict({"top_candidatos": 2, "top_resultados": 5})

    def test_construccion_directa_no_valida_para_experimentos(self):
        cfg = ConfigMatcher(umbral_alto=0.5, umbral_bajo=0.9)
        assert cfg.umbral_alto == pytest.approx(0.5)  # permitido: solo la carga valida
