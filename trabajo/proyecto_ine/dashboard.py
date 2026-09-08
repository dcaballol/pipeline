"""Dashboard interactivo conectado al repositorio analítico SQLite de la ENE."""

from pathlib import Path
import sqlite3

import altair as alt
import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
RUTA_BD = BASE_DIR / "salida" / "ene_2025.db"
ETIQUETAS = {
    "grupo": "Grupo", "muestra": "Personas encuestadas",
    "criterio": "Criterio", "regla_aplicada": "Regla aplicada",
    "registros_afectados": "Registros afectados", "tratamiento": "Tratamiento",
    "poblacion_edad_trabajar": "Población en edad de trabajar",
    "fuerza_trabajo": "Fuerza de trabajo", "personas_ocupadas": "Personas ocupadas",
    "personas_desocupadas": "Personas desocupadas", "iniciadores_disponibles": "Iniciadores disponibles",
    "ocupados_tiempo_parcial_involuntario": "Ocupados tiempo parcial involuntario",
    "ocupados_buscan_empleo": "Ocupados que buscan empleo",
    "fuerza_trabajo_potencial": "Fuerza de trabajo potencial",
    "fuerza_trabajo_ampliada": "Fuerza de trabajo ampliada",
    "ocupados_informales": "Ocupados informales", "ocupados_sector_informal": "Ocupados sector informal",
    "tasa_desocupacion": "Tasa de desocupación", "tasa_ocupacion": "Tasa de ocupación",
    "tasa_participacion": "Tasa de participación", "tasa_ocupacion_informal": "Tasa de ocupación informal",
}
COLUMNAS_PERSONAS = {
    "muestra", "poblacion_edad_trabajar", "fuerza_trabajo", "personas_ocupadas",
    "personas_desocupadas", "iniciadores_disponibles", "ocupados_tiempo_parcial_involuntario",
    "ocupados_buscan_empleo", "fuerza_trabajo_potencial", "fuerza_trabajo_ampliada",
    "ocupados_informales", "ocupados_sector_informal", "registros_afectados",
}
INDICADORES_GRAFICO = [
    "tasa_desocupacion", "tasa_ocupacion", "tasa_participacion", "tasa_ocupacion_informal",
]


@st.cache_data
def leer_tabla(nombre: str, version_repositorio: int) -> pd.DataFrame:
    """Lee una tabla y renueva la caché cuando cambia el archivo SQLite."""
    with sqlite3.connect(RUTA_BD) as conexion:
        return pd.read_sql_query(f"SELECT * FROM {nombre}", conexion)


def porcentaje(valor: float) -> str:
    return "-" if pd.isna(valor) else f"{valor:.2f}%"


def personas(valor: float) -> str:
    return "-" if pd.isna(valor) else f"{valor:,.0f}".replace(",", ".")


def mostrar_tabla(df: pd.DataFrame, columnas: list[str]) -> None:
    """Muestra solo columnas relevantes con etiquetas y formatos legibles."""
    tabla = df.loc[:, [columna for columna in columnas if columna in df.columns]].copy()
    formato = {}
    for columna in tabla.columns:
        if columna in COLUMNAS_PERSONAS:
            formato[columna] = personas
        elif columna.startswith(("tasa_", "su")):
            formato[columna] = porcentaje
    tabla = tabla.rename(columns=ETIQUETAS)
    formato_visible = {ETIQUETAS.get(columna, columna): funcion for columna, funcion in formato.items()}
    st.dataframe(tabla.style.format(formato_visible), use_container_width=True, hide_index=True)


def grafico_barras_ordenado(df: pd.DataFrame, grupo: str, indicador: str) -> None:
    """Barras descendentes con etiqueta visible, sin depender del tooltip."""
    datos = df[[grupo, indicador]].dropna().sort_values(indicador, ascending=False).copy()
    datos["etiqueta"] = datos[indicador].map(lambda valor: f"{valor:.2f}".replace(".", ",") + "%")
    titulo = ETIQUETAS.get(indicador, indicador)
    limite_superior = max(float(datos[indicador].max()) * 1.12, 1)
    barras = alt.Chart(datos).mark_bar(color="#62A9DD").encode(
        x=alt.X(f"{grupo}:N", sort=None, title=None, axis=alt.Axis(labelAngle=-55, labelFontSize=12)),
        y=alt.Y(f"{indicador}:Q", title=f"{titulo} (%)", scale=alt.Scale(domain=[0, limite_superior])),
        tooltip=[alt.Tooltip(f"{grupo}:N", title="Grupo"), alt.Tooltip(f"{indicador}:Q", title=titulo, format=".2f")],
    )
    etiquetas = alt.Chart(datos).mark_text(dy=-7, color="#E6EDF3", fontSize=12).encode(
        x=alt.X(f"{grupo}:N", sort=None), y=alt.Y(f"{indicador}:Q"), text="etiqueta:N",
    )
    st.altair_chart((barras + etiquetas).properties(height=390), use_container_width=True)


st.set_page_config(page_title="ENE 2025 | Indicadores laborales", page_icon="📊", layout="wide")
st.title("Indicadores laborales ENE 2025")
st.caption("Dashboard conectado a `salida/ene_2025.db` · estimaciones ponderadas con `fact_anual`.")

if not RUTA_BD.exists():
    st.error("No existe el repositorio analítico. Ejecuta primero: `python pipeline.py`.")
    st.stop()

version = RUTA_BD.stat().st_mtime_ns
nacional = leer_tabla("indicadores_nacionales", version).iloc[0]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Tasa de desocupación", porcentaje(nacional["tasa_desocupacion"]))
col2.metric("Tasa de ocupación", porcentaje(nacional["tasa_ocupacion"]))
col3.metric("Tasa de participación", porcentaje(nacional["tasa_participacion"]))
col4.metric("Ocupación informal", porcentaje(nacional["tasa_ocupacion_informal"]))

tab_region, tab_sexo, tab_edad, tab_calidad, tab_fuente = st.tabs(["Regiones", "Sexo", "Edad", "Calidad", "Trazabilidad"])
with tab_region:
    region = leer_tabla("indicadores_region", version)
    indicador = st.selectbox("Indicador para comparar", INDICADORES_GRAFICO, format_func=lambda valor: ETIQUETAS[valor])
    grafico_barras_ordenado(region, "grupo", indicador)
    mostrar_tabla(region, ["grupo", "muestra", "poblacion_edad_trabajar", "fuerza_trabajo", "personas_ocupadas", "personas_desocupadas", *INDICADORES_GRAFICO])

with tab_sexo:
    sexo = leer_tabla("indicadores_sexo", version)
    mostrar_tabla(sexo, ["grupo", "muestra", "poblacion_edad_trabajar", "personas_ocupadas", "personas_desocupadas", *INDICADORES_GRAFICO])

with tab_edad:
    edad = leer_tabla("indicadores_tramo_edad", version)
    st.caption("Tramos analíticos desde 15 años; las personas de 70 años o más se mantienen en `70+`.")
    grafico_barras_ordenado(edad, "grupo", "tasa_desocupacion")
    mostrar_tabla(edad, ["grupo", "muestra", "personas_ocupadas", "personas_desocupadas", *INDICADORES_GRAFICO])

with tab_calidad:
    calidad = leer_tabla("reporte_calidad_datos", version)
    mostrar_tabla(calidad, ["criterio", "regla_aplicada", "registros_afectados", "tratamiento"])
    st.info("Los registros inválidos no se eliminan: se preservan en `microdatos_analiticos` y se excluyen solo del cálculo que no pueden representar.")

with tab_fuente:
    metadata = leer_tabla("metadata_corrida", version)
    st.dataframe(metadata, use_container_width=True, hide_index=True)
    st.caption("La ENE no posee representatividad comunal. Los resultados se presentan a nivel nacional y regional.")
