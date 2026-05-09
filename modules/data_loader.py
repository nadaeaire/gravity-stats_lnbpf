# modules/data_loader.py
import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from datetime import datetime

# --- UTILIDAD INTERNA ---
def vectorizar_minutos(series):
    """Convierte minutos formato texto/float a float decimal."""
    mask_is_float = ~series.astype(str).str.contains(':')
    result_minutes = pd.Series(0.0, index=series.index)
    result_minutes.loc[mask_is_float] = pd.to_numeric(series.loc[mask_is_float], errors='coerce').fillna(0.0)
    m_s_part = series.loc[~mask_is_float].astype(str).str.split(':').str[:2].str.join(':')
    try:
        duration = pd.to_timedelta('00:' + m_s_part)
        result_minutes.loc[~mask_is_float] = duration.dt.total_seconds() / 60.0
    except:
        result_minutes.loc[~mask_is_float] = 0.0
    return result_minutes.fillna(0.0)

def _fetch_all_rows(table_name, select_cols="*", page_size=1000):
    """Descarga TODAS las filas de una tabla paginando en bloques.

    Supabase PostgREST limita las respuestas a 1,000 filas por defecto
    (max_rows del servidor). Esta función usa .range() para iterar
    en bloques y garantizar que se traigan todos los registros.

    OPTIMIZACIÓN: page_size=5000 reduce las llamadas HTTP de ~50 a ~10
    para tablas grandes (~50K filas). Si el servidor limita a menos,
    el loop sigue funcionando correctamente (detecta len < page_size).
    """
    supabase = get_supabase_client()
    all_data = []
    offset = 0
    while True:
        response = (
            supabase.table(table_name)
            .select(select_cols)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        all_data.extend(response.data)
        if len(response.data) < page_size:
            break
        offset += page_size
    return all_data

# --- CONEXIÓN SUPABASE ---
@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["supabase_config"]["url"]
        key = st.secrets["supabase_config"]["anon_key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Error Supabase Client: {e}")
        st.stop()

# --- Columnas específicas por vista (evitar SELECT *) ---
# OPTIMIZACIÓN: solo traer las columnas que realmente usan las vistas.
# Eliminadas: firstName, familyName (se usa Nombre), competition_id (se usa Categoria),
# Opp_POSS_DB (no se usa en ninguna vista).
_COLS_ANALITICA = ",".join([
    # Identificadores
    "id_player", "Nombre", "id_abe", "Fecha", "Categoria", "etapa", "equipo_nombre",
    # Stats individuales del jugador
    "sMinutes", "sPoints", "starter",
    "sFieldGoalsMade", "sFieldGoalsAttempted",
    "sTwoPointersMade", "sTwoPointersAttempted",
    "sThreePointersMade", "sThreePointersAttempted",
    "sFreeThrowsMade", "sFreeThrowsAttempted",
    "sReboundsOffensive", "sReboundsDefensive", "sReboundsTotal",
    "sAssists", "sTurnovers", "sSteals", "sBlocks", "sFoulsPersonal", "sFoulsOn",
    # Totales de equipo (Tm_)
    "Tm_Score", "Tm_MIN", "Tm_FG", "Tm_FGA", "Tm_3PM", "Tm_3PA", "Tm_2PM",
    "Tm_FTM", "Tm_FTA", "Tm_ORB", "Tm_DRB", "Tm_TRB",
    "Tm_AST", "Tm_TOV", "Tm_STL", "Tm_BLK", "Tm_PF",
    # Totales del rival (Opp_)
    "Opp_Name", "Opp_Score", "Opp_MIN",
    "Opp_FG", "Opp_FGA", "Opp_3PM", "Opp_3PA",
    "Opp_FTM", "Opp_FTA", "Opp_ORB", "Opp_DRB", "Opp_TRB",
    "Opp_TOV", "Opp_PF",
])

# vista_equipos_master — columnas usadas por equipos_smry, equipos_4f y equipos_avg.
_COLS_EQUIPOS = ",".join([
    "id_abe", "equipo_nombre", "Fecha", "Categoria", "etapa",
    "Tm_Score", "Tm_FG", "Tm_FGA", "Tm_3PM", "Tm_3PA", "Tm_2PM",
    "Tm_FTM", "Tm_FTA", "Tm_ORB", "Tm_DRB", "Tm_TRB",
    "Tm_AST", "Tm_TOV", "Tm_STL", "Tm_BLK", "Tm_PF", "Tm_PFR",
    "Opp_Score", "Opp_FG", "Opp_FGA", "Opp_3PM", "Opp_3PA", "Opp_2PM",
    "Opp_FTM", "Opp_FTA", "Opp_ORB", "Opp_DRB", "Opp_TRB",
    "Opp_AST", "Opp_TOV", "Opp_STL", "Opp_BLK", "Opp_PF", "Opp_PFR",
])

# --- CARGA 1: JUGADORES Y ESTADÍSTICAS (VISTA MAESTRA) ---
@st.cache_data(ttl=600)
def cargar_base_datos():
    try:
        # OPTIMIZACIÓN: columnas específicas en lugar de SELECT *
        # Reduce payload JSON (~8% menos datos transferidos).
        # OPTIMIZACIÓN: usar vista materializada (pre-computada por el cron)
        all_data = _fetch_all_rows("vista_analitica_master", select_cols=_COLS_ANALITICA)

        if not all_data: return pd.DataFrame()

        df_master = pd.DataFrame(all_data)

        # Limpieza de Minutos
        if 'sMinutes' in df_master.columns:
             if df_master['sMinutes'].dtype == object or df_master['sMinutes'].dtype == str:
                 df_master['sMinutes'] = vectorizar_minutos(df_master['sMinutes'])
             else:
                 df_master['sMinutes'] = pd.to_numeric(df_master['sMinutes'], errors='coerce').fillna(0)

        if 'Tm_MIN' in df_master.columns:
             if df_master['Tm_MIN'].dtype == object:
                 df_master['Tm_MIN'] = vectorizar_minutos(df_master['Tm_MIN'])
             else:
                 df_master['Tm_MIN'] = pd.to_numeric(df_master['Tm_MIN'], errors='coerce').fillna(0)

        # Fechas
        if 'Fecha' in df_master.columns:
            df_master['Fecha'] = pd.to_datetime(df_master['Fecha'], errors='coerce')
        else:
             df_master['Fecha'] = datetime.now()

        # --- CORRECCIÓN AQUÍ ---
        # Sanitización Numérica (EXCLUYENDO Opp_Name)
        # etapa → entero (1 = Temporada Regular, 2 = Playoffs)
        if 'etapa' in df_master.columns:
            df_master['etapa'] = pd.to_numeric(df_master['etapa'], errors='coerce').fillna(0).astype(int)

        cols_numericas = [c for c in df_master.columns if c.startswith('s') or c.startswith('Tm_') or c.startswith('Opp_')]

        for col in cols_numericas:
             # Agregamos 'Opp_Name' a las excepciones para que NO lo convierta a número
             if col not in ['sMinutes', 'Tm_MIN', 'Opp_Name']:
                df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

        # Limpieza específica para Opp_Name (Asegurar que sea Texto)
        if 'Opp_Name' in df_master.columns:
            df_master['Opp_Name'] = df_master['Opp_Name'].astype(str).replace(['nan', 'None', '0', '0.0'], '-')

        # --- LIMPIEZA DE CONTAMINACIÓN (vista_analitica_master) ---
        #
        # Eliminar filas "auto-rival": equipo_nombre == Opp_Name
        # (imposible en basket; son filas mal etiquetadas en la vista).
        if 'Opp_Name' in df_master.columns and 'equipo_nombre' in df_master.columns:
            df_master = df_master[df_master['Opp_Name'] != df_master['equipo_nombre']].copy()

        return df_master

    except Exception as e:
        st.error(f"⚠️ Error cargando datos de Jugadores: {e}")
        return pd.DataFrame()

# --- CARGA 2: EQUIPOS (CARRIL B - SIN DUPLICADOS) ---
@st.cache_data(ttl=600)
def cargar_datos_equipos_only():
    """Carga datos optimizados solo para la tabla de posiciones."""
    try:
        # OPTIMIZACIÓN: columnas específicas en lugar de SELECT *
        # Elimina 8 columnas no usadas (~27% menos datos transferidos).
        # OPTIMIZACIÓN: usar vista materializada (pre-computada por el cron)
        all_data = _fetch_all_rows("vista_equipos_master", select_cols=_COLS_EQUIPOS)
        if not all_data: return pd.DataFrame()

        df = pd.DataFrame(all_data)

        # LIMPIEZA DE DUPLICADOS (Vital para evitar 73 wins)
        if not df.empty and 'id_abe' in df.columns and 'equipo_nombre' in df.columns:
            df = df.drop_duplicates(subset=['id_abe', 'equipo_nombre'])

        # Tipos
        if 'Fecha' in df.columns:
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')

        # etapa → entero
        if 'etapa' in df.columns:
            df['etapa'] = pd.to_numeric(df['etapa'], errors='coerce').fillna(0).astype(int)

        # OPTIMIZACIÓN: solo sanitizar columnas que realmente se traen
        cols_num = ['Tm_Score', 'Opp_Score', 'Tm_FG', 'Tm_FGA', 'Tm_3PM', 'Tm_FTM',
                    'Tm_FTA', 'Tm_ORB', 'Tm_DRB', 'Tm_TOV', 'Opp_DRB', 'Opp_ORB',
                    'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_FTM', 'Opp_FTA', 'Opp_TOV']

        for c in cols_num:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

        return df
    except Exception as e:
        st.error(f"Error cargando vista equipos: {e}")
        return pd.DataFrame()
    
# --- CARGA 3: METADATA (PLAYERS & ROSTERS) ---
# Usamos un TTL más largo (ej. 1 hora) porque la estatura/peso no cambian seguido
@st.cache_data(ttl=3600) 
def cargar_metadata_jugadores():
    """
    Carga las tablas de dimensiones: players (bio) y rosters (equipos/posiciones).
    Retorna dos DataFrames: (df_players, df_rosters)
    """
    try:
        # 1. Fetch tabla 'players' (paginado para evitar límite de 1,000 filas)
        data_p = _fetch_all_rows("players")
        df_players = pd.DataFrame(data_p) if data_p else pd.DataFrame()

        # 2. Fetch tabla 'rosters' (paginado para evitar límite de 1,000 filas)
        data_r = _fetch_all_rows("rosters")
        df_rosters = pd.DataFrame(data_r) if data_r else pd.DataFrame()

        # --- Limpieza Preventiva ---
        
        # Convertir numéricos en Players
        if not df_players.empty:
            cols_bio = ['height_cm', 'weight_kg'] 
            for c in cols_bio:
                if c in df_players.columns:
                    df_players[c] = pd.to_numeric(df_players[c], errors='coerce').fillna(0)

        # Convertir fechas en Rosters (importante para ordenar por la más reciente)
        if not df_rosters.empty:
            if 'effective_start_date' in df_rosters.columns:
                df_rosters['effective_start_date'] = pd.to_datetime(df_rosters['effective_start_date'], errors='coerce')

        return df_players, df_rosters

    except Exception as e:
        st.error(f"⚠️ Error cargando Metadata (Players/Rosters): {e}")
        # Retornar DFs vacíos para no romper la app
        return pd.DataFrame(), pd.DataFrame()
    
# --- CARGA 4: TIROS (SHOT DATA) ---
@st.cache_data(ttl=600)
def cargar_tiros():
    """Carga la tabla de tiros desde Supabase para los mapas de tiro."""
    try:
        all_data = _fetch_all_rows(
            "tiros",
            select_cols="partido_id,equipo_id,player_id,r,x,y,actiontype,subtype,per"
        )
        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)

        # Tipos numéricos
        for c in ['x', 'y', 'r']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')

        # Eliminar filas sin coordenadas válidas
        df = df.dropna(subset=['x', 'y'])

        return df
    except Exception as e:
        st.error(f"Error cargando tiros: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def cargar_catalogo_equipos():
    """Carga solo el catálogo de equipos (ID y Nombre) para cruces."""
    try:
        # Pedimos explícitamente la tabla 'equipos' (paginado por seguridad)
        data = _fetch_all_rows("equipos", select_cols="equipo_id, nombre, competicion_id")
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"Error cargando catálogo equipos: {e}")
        return pd.DataFrame()