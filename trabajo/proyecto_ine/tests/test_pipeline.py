"""Pruebas de las definiciones ENE utilizadas por el pipeline."""

import pandas as pd
import pytest
import sqlite3

from src.cargar import guardar_resultados
from src.extraer import COLUMNAS_REQUERIDAS
from src.transformar import calcular_indicadores, construir_componentes, generar_resultados


def _base_sintetica() -> pd.DataFrame:
    """Una fila por componente del libro de códigos, con peso conocido."""
    return pd.DataFrame({
        "ano_trimestre": [2025] * 8,
        "region": [13, 13, 5, 5, 1, 1, 2, 2],
        "sexo": [1, 2, 1, 2, 1, 2, 1, 2],
        "edad": [30, 28, 45, 52, 19, 40, 25, 37],
        "cae_especifico": [1, 8, 10, 12, 1, 1, 9, 7],
        "ocup_form": [1, 1, 1, 1, 2, 1, 1, 2],
        "sector": [1, 1, 1, 1, 2, 1, 1, 2],
        "habituales": [45, 0, 0, 0, 20, 40, 0, 30],
        "c10": [2, 2, 2, 2, 1, 2, 2, 1],
        "c11": [3, 3, 3, 3, 1, 3, 3, 2],
        "e4": [7, 7, 7, 7, 2, 7, 7, 3],
        "fact_anual": [10.0] * 8,
        "tramo_edad": [2, 2, 5, 6, 1, 4, 2, 3],
    })


def test_columnas_requeridas_corresponden_a_base_anual():
    assert "fact_anual" in COLUMNAS_REQUERIDAS
    assert "cae_especifico" in COLUMNAS_REQUERIDAS


def test_componentes_siguen_codigos_del_libro_ene():
    base, _ = construir_componentes(_base_sintetica())
    assert base["ocupados"].sum() == 4
    assert base["desocupados"].sum() == 2
    assert base["fdt"].sum() == 6
    assert base["iniciadores_disponibles"].sum() == 1
    assert base["ftp"].sum() == 1
    assert base["tpi"].sum() == 2
    assert base["obe"].sum() == 2


def test_indicadores_ponderados_tienen_denominadores_correctos():
    base, _ = construir_componentes(_base_sintetica())
    indicadores = calcular_indicadores(base)
    assert indicadores["poblacion_edad_trabajar"] == 80
    assert indicadores["fuerza_trabajo"] == 60
    assert indicadores["personas_desocupadas"] == 20
    assert indicadores["tasa_desocupacion"] == pytest.approx(33.33)
    assert indicadores["tasa_ocupacion"] == pytest.approx(50.0)
    assert indicadores["tasa_participacion"] == pytest.approx(75.0)
    assert indicadores["tasa_ocupacion_informal"] == pytest.approx(50.0)


def test_resultados_incluyen_desagregaciones_esperadas():
    _, resultados, calidad = generar_resultados(_base_sintetica(), "fact_anual", 15)
    assert set(["indicadores_nacionales", "indicadores_region", "indicadores_sexo"]).issubset(resultados)
    assert resultados["indicadores_region"].shape[0] == 4
    assert "registros_afectados" in calidad.columns
    assert resultados["indicadores_tramo_edad"]["grupo"].astype(str).str.startswith("0").sum() == 0


def test_calidad_conserva_filas_y_documenta_valores_invalidos():
    datos = _base_sintetica()
    datos.loc[0, "edad"] = 150
    datos.loc[1, "fact_anual"] = 0
    datos.loc[2, "region"] = 99

    resultado, calidad = construir_componentes(datos)

    assert len(resultado) == len(datos)
    assert pd.isna(resultado.loc[0, "edad"])
    assert resultado.loc[1, "factor"] == 0
    assert resultado.loc[2, "region_nombre"] == "Sin clasificación"
    assert calidad["registros_afectados"].sum() >= 3


def test_carga_crea_repositorio_analitico_y_reporte_calidad(tmp_path):
    base, resultados, calidad = generar_resultados(_base_sintetica(), "fact_anual", 15)
    metadata = pd.DataFrame([{"corrida_id": "prueba", "archivo_origen": "sintetico.csv"}])
    ruta_bd = tmp_path / "ene.db"
    rutas = guardar_resultados(
        resultados, calidad, base, metadata, str(ruta_bd), str(tmp_path), exportar_parquet=False,
    )

    assert ruta_bd.exists()
    assert any(ruta.name == "reporte_calidad_datos.csv" for ruta in rutas)
    with sqlite3.connect(ruta_bd) as conexion:
        tablas = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conexion)["name"].tolist()
    assert {"microdatos_analiticos", "reporte_calidad_datos", "metadata_corrida"}.issubset(tablas)


def test_carga_limpia_reportes_de_corridas_anteriores(tmp_path):
    carpeta_reportes = tmp_path / "reportes"
    carpeta_reportes.mkdir()
    artefacto_antiguo = carpeta_reportes / "reporte_obsoleto.csv"
    artefacto_antiguo.write_text("contenido antiguo", encoding="utf-8")

    base, resultados, calidad = generar_resultados(_base_sintetica(), "fact_anual", 15)
    metadata = pd.DataFrame([{"corrida_id": "prueba", "archivo_origen": "sintetico.csv"}])
    guardar_resultados(resultados, calidad, base, metadata, str(tmp_path / "ene.db"), str(tmp_path), exportar_parquet=False)

    assert not artefacto_antiguo.exists()
    assert (carpeta_reportes / "indicadores_nacionales.csv").exists()
