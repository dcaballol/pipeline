"""Extracción y validación de la base anual de la ENE."""

from pathlib import Path

import pandas as pd
from loguru import logger


# Variables que el pipeline utiliza para construir los indicadores publicados
# en el libro de códigos de la ENE. Se cargan únicamente estas columnas para
# mantener acotado el uso de memoria de la base anual.
COLUMNAS_REQUERIDAS = {
    "ano_trimestre", "region", "sexo", "edad", "cae_especifico",
    "ocup_form", "sector", "habituales", "c10", "c11", "e4",
    "fact_anual",
}
COLUMNAS_OPCIONALES = {"tramo_edad"}


def extraer_ene(config_datos: dict) -> pd.DataFrame:
    """Lee el CSV anual de ENE respetando su separador y decimal.

    La identificación se mantiene como texto para no perder ceros o precisión
    en claves de hogar/persona. Las columnas analíticas se convierten después
    a numérico en ``transformar.py``.
    """
    ruta = Path(config_datos["carpeta"]) / config_datos["archivo"]
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró la base ENE: {ruta.resolve()}")

    cabecera_origen = pd.read_csv(
        ruta,
        sep=config_datos.get("separador", ";"),
        encoding=config_datos.get("encoding", "utf-8-sig"),
        nrows=0,
    ).columns
    df = pd.read_csv(
        ruta,
        sep=config_datos.get("separador", ";"),
        decimal=config_datos.get("decimal", ","),
        encoding=config_datos.get("encoding", "utf-8-sig"),
        low_memory=False,
        usecols=lambda columna: columna in (COLUMNAS_REQUERIDAS | COLUMNAS_OPCIONALES),
    )
    faltantes = sorted(COLUMNAS_REQUERIDAS - set(df.columns))
    if faltantes:
        raise ValueError(
            "La base no contiene las variables requeridas por el indicador ENE: "
            + ", ".join(faltantes)
        )

    metadatos = {
        "archivo_origen": ruta.name,
        "ruta_origen": str(ruta.resolve()),
        "tamano_mb": round(ruta.stat().st_size / 1024**2, 2),
        "filas_origen": len(df),
        "columnas_origen": len(cabecera_origen),
        "variables_analiticas_cargadas": len(df.columns),
        "frecuencia": config_datos.get("frecuencia", "anual"),
    }
    df.attrs["metadatos_origen"] = metadatos
    logger.info(
        "Base ENE cargada: {} filas, {} columnas, período {}.",
        len(df), len(df.columns),
        ", ".join(map(str, sorted(df["ano_trimestre"].dropna().unique()))),
    )
    return df
