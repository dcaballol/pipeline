"""Carga del repositorio analítico ENE y visualizaciones de resultados."""

from __future__ import annotations

import html
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
from loguru import logger


def guardar_resultados(
    resultados: dict[str, pd.DataFrame],
    calidad: pd.DataFrame,
    microdatos: pd.DataFrame,
    metadata: pd.DataFrame,
    ruta_bd: str,
    carpeta_salida: str,
    exportar_parquet: bool = True,
    limpiar_reportes: bool = True,
) -> list[Path]:
    """Carga el repositorio SQLite y exporta tablas de consumo.

    Las tablas agregadas se publican en CSV y Parquet. Los microdatos
    analíticos quedan en SQLite y Parquet para trazabilidad, pero no se genera
    CSV para evitar un archivo plano innecesariamente pesado.
    """
    salida = Path(carpeta_salida)
    reportes = salida / "reportes"
    reportes.mkdir(parents=True, exist_ok=True)
    if limpiar_reportes:
        # `reportes/` es de uso exclusivo del pipeline. Se limpia antes de
        # escribir para que solo sobrevivan los artefactos de la última corrida.
        for artefacto in reportes.iterdir():
            if artefacto.is_dir():
                shutil.rmtree(artefacto)
            else:
                artefacto.unlink()
        logger.info("Reportes de corridas anteriores eliminados de {}.", reportes)
    ruta_bd = Path(ruta_bd)
    ruta_bd.parent.mkdir(parents=True, exist_ok=True)
    tablas = {**resultados, "reporte_calidad_datos": calidad, "metadata_corrida": metadata}
    rutas: list[Path] = []

    with sqlite3.connect(ruta_bd) as conexion:
        for nombre, tabla in tablas.items():
            tabla.to_sql(nombre, conexion, if_exists="replace", index=False)
            ruta_csv = reportes / f"{nombre}.csv"
            tabla.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
            rutas.append(ruta_csv)
            if exportar_parquet:
                ruta_parquet = reportes / f"{nombre}.parquet"
                tabla.to_parquet(ruta_parquet, index=False)
                rutas.append(ruta_parquet)
        microdatos.to_sql("microdatos_analiticos", conexion, if_exists="replace", index=False, chunksize=50_000)

    if exportar_parquet:
        ruta_microdatos = reportes / "microdatos_analiticos.parquet"
        microdatos.to_parquet(ruta_microdatos, index=False)
        rutas.append(ruta_microdatos)
    logger.success("Repositorio analítico actualizado: {} tablas en {}.", len(tablas) + 1, ruta_bd)
    return rutas


def subir_a_s3(rutas: list[Path], bucket: str, prefix: str, region: str, carpeta_base: str) -> list[str]:
    """Sube los artefactos generados a S3 conservando su estructura."""
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError("Falta boto3; instala requirements.txt para usar S3.") from error
    cliente = boto3.client("s3", region_name=region)
    base = Path(carpeta_base)
    subidos = []
    for ruta in rutas:
        key = f"{prefix.rstrip('/')}/{ruta.relative_to(base).as_posix()}"
        cliente.upload_file(str(ruta), bucket, key)
        subidos.append(key)
        logger.success("Subido a S3: s3://{}/{}", bucket, key)
    return subidos


def _porcentaje(valor: object) -> str:
    return "-" if pd.isna(valor) else f"{float(valor):.2f}%"


def _tabla(df: pd.DataFrame, columnas: list[tuple[str, str]]) -> str:
    encabezado = "".join(f"<th>{html.escape(titulo)}</th>" for _, titulo in columnas)
    filas = []
    for _, fila in df.iterrows():
        celdas = []
        for nombre, _ in columnas:
            valor = fila[nombre]
            if nombre.startswith(("tasa_", "su")):
                texto = _porcentaje(valor)
            elif nombre in {"pet", "fdt", "ocupados", "desocupados", "muestra", "registros_afectados"}:
                texto = f"{valor:,.0f}"
            else:
                texto = str(valor)
            celdas.append(f"<td>{html.escape(texto)}</td>")
        filas.append("<tr>" + "".join(celdas) + "</tr>")
    return f"<table><thead><tr>{encabezado}</tr></thead><tbody>{''.join(filas)}</tbody></table>"


def generar_dashboard(
    resultados: dict[str, pd.DataFrame], calidad: pd.DataFrame, ruta: Path,
    periodo: str, corrida_id: str,
) -> None:
    """Genera una vista estática desde las mismas tablas cargadas a SQLite."""
    nacional = resultados["indicadores_nacionales"].iloc[0]
    tarjetas = [
        ("Tasa de desocupación", _porcentaje(nacional["tasa_desocupacion"])),
        ("Tasa de ocupación", _porcentaje(nacional["tasa_ocupacion"])),
        ("Tasa de participación", _porcentaje(nacional["tasa_participacion"])),
        ("Ocupación informal", _porcentaje(nacional["tasa_ocupacion_informal"])),
    ]
    cards = "".join(f'<section class="card"><strong>{titulo}</strong><span>{valor}</span></section>' for titulo, valor in tarjetas)
    region = resultados["indicadores_region"].sort_values("tasa_desocupacion", ascending=False)
    tabla_region = _tabla(region, [("grupo", "Región"), ("muestra", "Muestra"), ("tasa_desocupacion", "TD"), ("tasa_ocupacion", "TO"), ("tasa_participacion", "TP")])
    tabla_sexo = _tabla(resultados["indicadores_sexo"], [("grupo", "Sexo"), ("tasa_desocupacion", "TD"), ("tasa_ocupacion", "TO"), ("tasa_participacion", "TP"), ("tasa_ocupacion_informal", "TOI")])
    tabla_calidad = _tabla(calidad, [("criterio", "Criterio"), ("regla_aplicada", "Regla"), ("registros_afectados", "Registros"), ("tratamiento", "Tratamiento")])
    ruta.write_text(f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>ENE {periodo} - Indicadores laborales</title>
<style>body{{font-family:Arial,sans-serif;max-width:1120px;margin:auto;padding:36px;color:#19324d;background:#f7fafc}}h1,h2{{color:#006e61}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}.card{{background:#fff;border-radius:10px;padding:18px;box-shadow:0 1px 5px #ccd}}.card strong{{display:block;font-size:14px}}.card span{{font-size:30px;font-weight:bold;color:#006e61;display:block;margin-top:10px}}table{{width:100%;border-collapse:collapse;background:#fff;margin-bottom:28px}}th,td{{padding:10px;border-bottom:1px solid #dde;text-align:left;vertical-align:top}}th{{background:#006e61;color:#fff}}.note{{color:#52606d;line-height:1.5}}code{{background:#e6efed;padding:2px 5px;border-radius:4px}}</style></head>
<body><p>Encuesta Nacional de Empleo · INE Chile · Base anual · corrida <code>{corrida_id}</code></p><h1>Indicadores laborales {periodo}</h1><div class="grid">{cards}</div>
<h2>Resultados regionales</h2>{tabla_region}<h2>Resultados por sexo</h2>{tabla_sexo}<h2>Calidad de datos</h2>{tabla_calidad}
<p class="note">Esta visualización se genera después de cargar las tablas <code>indicadores_*</code>, <code>reporte_calidad_datos</code> y <code>microdatos_analiticos</code> en <code>salida/ene_2025.db</code>. Para explorar el repositorio analítico de forma interactiva: <code>streamlit run dashboard.py</code>.</p>
<p class="note">Estimaciones ponderadas con <code>fact_anual</code>. La ENE no tiene representatividad comunal; los resultados se presentan a nivel nacional y regional.</p></body></html>''', encoding="utf-8")
    logger.success("Dashboard HTML generado en {}.", ruta)
