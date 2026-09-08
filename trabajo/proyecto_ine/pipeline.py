"""Pipeline de indicadores laborales para la base anual ENE 2025."""

from datetime import datetime
from pathlib import Path

import yaml
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from src.cargar import generar_dashboard, guardar_resultados, subir_a_s3
from src.extraer import extraer_ene
from src.transformar import generar_resultados


BASE_DIR = Path(__file__).resolve().parent


def cargar_configuracion() -> dict:
    with (BASE_DIR / "config.yaml").open(encoding="utf-8") as archivo:
        config = yaml.safe_load(archivo)
    for seccion, clave in [("datos", "carpeta"), ("salida", "carpeta"), ("base_datos", "ruta")]:
        ruta = Path(config[seccion][clave])
        config[seccion][clave] = str(ruta if ruta.is_absolute() else BASE_DIR / ruta)
    return config


def configurar_logging() -> None:
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    logger.remove()
    logger.add(lambda mensaje: print(mensaje, end=""), level="INFO")
    logger.add(BASE_DIR / "logs" / "pipeline_{time:YYYY-MM-DD}.log", level="DEBUG", encoding="utf-8", rotation="5 MB", retention="30 days")


def main() -> None:
    configurar_logging()
    load_dotenv(BASE_DIR / ".env")
    config = cargar_configuracion()
    corrida_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    logger.info("Iniciando análisis anual ENE 2025.")
    base = extraer_ene(config["datos"])
    metadata_origen = base.attrs.get("metadatos_origen", {})
    microdatos, resultados, calidad = generar_resultados(
        base,
        factor=config["ene"]["factor_expansion"],
        edad_minima=config["ene"].get("edad_minima_pet", 15),
        edad_maxima=config["ene"].get("edad_maxima_valida", 120),
    )
    metadata = {
        "corrida_id": corrida_id,
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        "fuente": config["datos"].get("fuente", "ENE"),
        "factor_expansion": config["ene"]["factor_expansion"],
        **metadata_origen,
    }
    rutas = guardar_resultados(
        resultados, calidad, microdatos, pd.DataFrame([metadata]),
        config["base_datos"]["ruta"], config["salida"]["carpeta"],
        config["salida"].get("exportar_parquet", True),
        config["salida"].get("limpiar_reportes_antes_de_cargar", True),
    )
    periodo = ", ".join(map(str, sorted(base["ano_trimestre"].dropna().unique())))
    ruta_dashboard = Path(config["salida"]["carpeta"]) / "visualizacion.html"
    generar_dashboard(resultados, calidad, ruta_dashboard, periodo, corrida_id)
    rutas.append(ruta_dashboard)
    if config.get("aws", {}).get("subir_a_s3", False):
        logger.info("Subiendo resultados ENE a S3.")
        subir_a_s3(
            rutas=rutas,
            bucket=config["aws"]["bucket"],
            prefix=config["aws"]["prefix"],
            region=config["aws"]["region"],
            carpeta_base=config["salida"]["carpeta"],
        )
    nacional = resultados["indicadores_nacionales"].iloc[0]
    logger.success("Finalizado {}: TD={}%, TO={}%, TP={}%.", periodo, nacional["tasa_desocupacion"], nacional["tasa_ocupacion"], nacional["tasa_participacion"])


if __name__ == "__main__":
    main()
