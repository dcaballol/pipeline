"""Transformación, calidad e indicadores de la Encuesta Nacional de Empleo.

Las definiciones de los componentes siguen la sección 7 del Libro de códigos
ENE incluido en ``docs/``. La etapa preserva cada registro en el repositorio
analítico y documenta cualquier valor excluido de un cálculo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


CODIGOS_FTP = {12, 14, 16, 18, 20, 22, 25, 26, 27}
CODIGOS_FTA = set(range(1, 11)) | CODIGOS_FTP
# El libro de códigos ENE define 0 como "Menor de 15 años" y 1-28 para
# la condición de actividad de las personas de 15 años o más.
CODIGOS_CAE = {0} | set(range(1, 29))
NOMBRES_REGION = {
    1: "Tarapacá", 2: "Antofagasta", 3: "Atacama", 4: "Coquimbo",
    5: "Valparaíso", 6: "O'Higgins", 7: "Maule", 8: "Biobío",
    9: "La Araucanía", 10: "Los Lagos", 11: "Aysén", 12: "Magallanes",
    13: "Metropolitana", 14: "Los Ríos", 15: "Arica y Parinacota", 16: "Ñuble",
}
NOMBRES_SEXO = {1: "Hombres", 2: "Mujeres"}
VARIABLES_NUMERICAS = [
    "edad", "cae_especifico", "ocup_form", "sector", "habituales", "c10",
    "c11", "e4", "region", "sexo",
]
NOMBRES_NIVELES = {
    "pet": "poblacion_edad_trabajar",
    "fdt": "fuerza_trabajo",
    "ocupados": "personas_ocupadas",
    "desocupados": "personas_desocupadas",
    "iniciadores_disponibles": "iniciadores_disponibles",
    "tpi": "ocupados_tiempo_parcial_involuntario",
    "obe": "ocupados_buscan_empleo",
    "ftp": "fuerza_trabajo_potencial",
    "fta": "fuerza_trabajo_ampliada",
    "ocupados_informales": "ocupados_informales",
    "ocupados_sector_informal": "ocupados_sector_informal",
}


def _fila_calidad(criterio: str, regla: str, afectados: int, tratamiento: str) -> dict:
    return {
        "criterio": criterio,
        "regla_aplicada": regla,
        "registros_afectados": int(afectados),
        "tratamiento": tratamiento,
    }


def _convertir_numericas(df: pd.DataFrame, columnas: list[str]) -> tuple[pd.DataFrame, int]:
    """Normaliza números y cuenta valores no vacíos que no pudieron convertirse."""
    resultado = df.copy()
    conversiones_fallidas = 0
    for columna in columnas:
        original = resultado[columna]
        convertido = pd.to_numeric(original, errors="coerce")
        conversiones_fallidas += int((original.notna() & convertido.isna()).sum())
        resultado[columna] = convertido
    return resultado, conversiones_fallidas


def construir_componentes(
    df: pd.DataFrame,
    factor: str = "fact_anual",
    edad_minima: int = 15,
    edad_maxima: int = 120,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normaliza campos, registra calidad y crea los componentes ENE.

    No se eliminan filas: los valores inválidos se conservan en el microdato
    analítico, se convierten en ausentes y se excluyen solo del indicador que
    no pueden representar. Un factor inválido se reemplaza por cero para no
    alterar niveles ponderados.
    """
    requeridas = [factor, *VARIABLES_NUMERICAS]
    faltantes = [columna for columna in requeridas if columna not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas para calcular indicadores: {', '.join(faltantes)}")

    resultado, conversiones_fallidas = _convertir_numericas(df, requeridas)
    calidad = [
        _fila_calidad(
            "Normalización de formatos",
            "Conversión de variables analíticas a tipo numérico.",
            conversiones_fallidas,
            "Valores no convertibles pasan a nulo y quedan documentados.",
        )
    ]

    edad_invalida = resultado["edad"].notna() & ~resultado["edad"].between(0, edad_maxima)
    resultado.loc[edad_invalida, "edad"] = np.nan
    calidad.append(_fila_calidad(
        "Valores erróneos", f"Edad fuera del rango válido del microdato: 0-{edad_maxima}.", edad_invalida.sum(),
        "Se conserva el registro; la edad se deja nula y no integra la población en edad de trabajar.",
    ))

    fuera_poblacion_objetivo = resultado["edad"].notna() & resultado["edad"].lt(edad_minima)
    calidad.append(_fila_calidad(
        "Alcance analítico",
        f"Indicadores laborales desde {edad_minima} años; tramos 15-24 a 65-69 y 70+.",
        fuera_poblacion_objetivo.sum(),
        "Menores de 15 años son válidos en la encuesta, se conservan en microdatos y no integran resultados laborales.",
    ))

    cae_invalido = resultado["cae_especifico"].notna() & ~resultado["cae_especifico"].isin(CODIGOS_CAE)
    resultado.loc[cae_invalido, "cae_especifico"] = np.nan
    calidad.append(_fila_calidad(
        "Valores erróneos", "cae_especifico fuera del catálogo 0-28.", cae_invalido.sum(),
        "Se conserva el registro; se excluye de los componentes laborales derivados.",
    ))

    region_invalida = resultado["region"].notna() & ~resultado["region"].isin(NOMBRES_REGION)
    resultado.loc[region_invalida, "region"] = np.nan
    calidad.append(_fila_calidad(
        "Valores erróneos", "Región fuera del catálogo 1-16.", region_invalida.sum(),
        "Se conserva el registro; se reporta como Sin clasificación.",
    ))

    sexo_invalido = resultado["sexo"].notna() & ~resultado["sexo"].isin(NOMBRES_SEXO)
    resultado.loc[sexo_invalido, "sexo"] = np.nan
    calidad.append(_fila_calidad(
        "Valores erróneos", "Sexo fuera del catálogo 1-2.", sexo_invalido.sum(),
        "Se conserva el registro; se reporta como Sin clasificación.",
    ))

    factor_invalido = resultado[factor].isna() | resultado[factor].le(0)
    resultado["factor"] = resultado[factor].where(~factor_invalido, 0.0)
    calidad.append(_fila_calidad(
        "Valores erróneos", f"{factor} nulo, cero o negativo.", factor_invalido.sum(),
        "Se conserva el registro con factor 0; no aporta a estimaciones ponderadas.",
    ))

    faltantes_criticos = resultado[["edad", "cae_especifico", "region", "sexo", factor]].isna().any(axis=1)
    calidad.append(_fila_calidad(
        "Completitud", "Al menos una variable crítica nula tras validación.", faltantes_criticos.sum(),
        "Se mantiene para auditoría; cada indicador usa únicamente sus componentes válidos.",
    ))

    cae = resultado["cae_especifico"]
    resultado["pet"] = resultado["edad"].ge(edad_minima)
    resultado["fdt"] = cae.between(1, 9)
    resultado["ocupados"] = cae.between(1, 7)
    resultado["desocupados"] = cae.isin([8, 9])
    resultado["iniciadores_disponibles"] = cae.eq(10)
    resultado["tpi"] = (
        resultado["ocupados"] & resultado["habituales"].le(30)
        & resultado["c10"].eq(1) & resultado["c11"].isin([1, 2])
    )
    resultado["obe"] = resultado["ocupados"] & resultado["e4"].between(1, 6)
    resultado["ftp"] = cae.isin(CODIGOS_FTP)
    resultado["fta"] = cae.isin(CODIGOS_FTA)
    resultado["ocupados_informales"] = resultado["ocup_form"].eq(2)
    resultado["ocupados_sector_informal"] = resultado["sector"].eq(2)
    resultado["region_nombre"] = resultado["region"].map(NOMBRES_REGION).fillna("Sin clasificación")
    resultado["sexo_nombre"] = resultado["sexo"].map(NOMBRES_SEXO).fillna("Sin clasificación")
    resultado["tramo_edad_analitico"] = pd.cut(
        resultado["edad"],
        bins=[edad_minima, 25, 35, 45, 55, 65, 70, np.inf],
        right=False,
        labels=["15-24", "25-34", "35-44", "45-54", "55-64", "65-69", "70+"],
    )

    calidad.append(_fila_calidad(
        "Métricas derivadas",
        "Componentes PET, FT, ocupados, desocupados, subutilización e informalidad.",
        len(resultado),
        "Se agregan columnas analíticas trazables al microdato; no reemplazan variables fuente.",
    ))
    return resultado, pd.DataFrame(calidad)


def _ponderado(df: pd.DataFrame, columna: str) -> float:
    return float(df.loc[df[columna].fillna(False), "factor"].sum())


def _seguro(numerador: float, denominador: float) -> float:
    return round(numerador / denominador * 100, 2) if denominador else np.nan


def _personas(valor: float) -> int:
    """Redondea niveles expandidos a personas enteras para difusión."""
    return int(round(valor))


def calcular_indicadores(df: pd.DataFrame) -> dict:
    """Calcula niveles y tasas TD, TO, TP, TPL, SU1-SU4, TOI y TOSI."""
    niveles = {
        "pet": _ponderado(df, "pet"), "fdt": _ponderado(df, "fdt"),
        "ocupados": _ponderado(df, "ocupados"), "desocupados": _ponderado(df, "desocupados"),
        "iniciadores_disponibles": _ponderado(df, "iniciadores_disponibles"),
        "tpi": _ponderado(df, "tpi"), "obe": _ponderado(df, "obe"),
        "ftp": _ponderado(df, "ftp"), "fta": _ponderado(df, "fta"),
        "ocupados_informales": _ponderado(df, "ocupados_informales"),
        "ocupados_sector_informal": _ponderado(df, "ocupados_sector_informal"),
    }
    n = niveles
    tasas = {
        "tasa_desocupacion": _seguro(n["desocupados"], n["fdt"]),
        "tasa_ocupacion": _seguro(n["ocupados"], n["pet"]),
        "tasa_participacion": _seguro(n["fdt"], n["pet"]),
        "tasa_presion_laboral": _seguro(n["desocupados"] + n["iniciadores_disponibles"] + n["obe"], n["fdt"] + n["iniciadores_disponibles"]),
        "su1": _seguro(n["desocupados"] + n["iniciadores_disponibles"], n["fdt"] + n["iniciadores_disponibles"]),
        "su2": _seguro(n["desocupados"] + n["iniciadores_disponibles"] + n["tpi"], n["fdt"] + n["iniciadores_disponibles"]),
        "su3": _seguro(n["desocupados"] + n["iniciadores_disponibles"] + n["ftp"], n["fta"]),
        "su4": _seguro(n["desocupados"] + n["iniciadores_disponibles"] + n["tpi"] + n["ftp"], n["fta"]),
        "tasa_ocupacion_informal": _seguro(n["ocupados_informales"], n["ocupados"]),
        "tasa_ocupacion_sector_informal": _seguro(n["ocupados_sector_informal"], n["ocupados"]),
    }
    niveles_publicos = {NOMBRES_NIVELES[nombre]: _personas(valor) for nombre, valor in niveles.items()}
    return {**niveles_publicos, **tasas}


def resumen_por_grupo(df: pd.DataFrame, columna: str) -> pd.DataFrame:
    filas = []
    for grupo, datos in df.groupby(columna, dropna=False, observed=True):
        filas.append({"grupo": grupo, "muestra": len(datos), **calcular_indicadores(datos)})
    return pd.DataFrame(filas).sort_values("grupo").reset_index(drop=True)


def generar_resultados(
    df: pd.DataFrame, factor: str, edad_minima: int, edad_maxima: int = 120,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    """Orquesta microdatos analíticos, resultados agregados y reporte de calidad."""
    base, calidad = construir_componentes(df, factor, edad_minima, edad_maxima)
    resultados = {
        "indicadores_nacionales": pd.DataFrame([{"grupo": "Nacional", "muestra": len(base), **calcular_indicadores(base)}]),
        "indicadores_region": resumen_por_grupo(base, "region_nombre"),
        "indicadores_sexo": resumen_por_grupo(base, "sexo_nombre"),
    }
    base_pet = base.loc[base["pet"]].copy()
    resultados["indicadores_tramo_edad"] = resumen_por_grupo(base_pet, "tramo_edad_analitico")
    logger.success("Indicadores ENE calculados con factor '{}' para {} personas.", factor, len(base))
    return base, resultados, calidad
