import streamlit as st
import pandas as pd
import modules.utils as utils
import modules.auth as auth
# Importamos las funciones de carga desde tu data_loader actualizado
from modules.data_loader import cargar_base_datos, cargar_metadata_jugadores, cargar_catalogo_equipos, cargar_datos_equipos_only, cargar_tiros

# Importamos las Vistas
import views.players_avg as view_players_avg
import views.players_adv as view_players_adv
import views.equipos_smry as view_equipos_smry
import views.equipos_4f as view_equipos_4f
import views.players_prfl as view_players_prfl
import views.equipos_tiros as view_equipos_tiros
import views.equipos_avg as view_equipos_avg
import views.equipos_tot as view_equipos_tot
import views.players_tot as view_players_tot

# --- Detección de entorno (test vs producción) ---
# En Streamlit Cloud → Secrets del app de test agregar: entorno = "test"
IS_TEST = st.secrets.get("entorno", "produccion") == "test"

# 1. Configuración Global
st.set_page_config(
    page_title="Analytics LNBP Femenil — GravityStats x Nada Está en el Aire",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Cargar estilos y tracking
utils.cargar_estilos_css()
utils.inyectar_ga()

# 2. Autenticación
if IS_TEST:
    # Test: acceso libre, sin login
    st.session_state["password_correct"] = True
    st.session_state["user_email"] = "develop@gravitystats.app"
else:
    # Producción: requiere login
    if not auth.check_password():
        st.stop()

# --- INICIALIZACIÓN DE ESTADO ---
if 'selected_player_id' not in st.session_state:
    st.session_state.selected_player_id = 190 

if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'main' # 'main' o 'profile'

# 3. Carga de Datos Global
# OPTIMIZACIÓN: df_tiros se carga de forma lazy (solo cuando se necesita)
# para reducir el tiempo de arranque en vistas que no usan mapas de tiro.
# Las funciones usan @st.cache_data, así que la query real solo corre 1 vez por TTL.
try:
    with st.spinner('Cargando base de datos...'):
        # A) Carga de Stats (Games) - Carril A
        df_raw = cargar_base_datos()

        # B) Carga de Metadata (Bio y Rosters) desde Supabase - Carril C (Nuevo)
        df_players, df_rosters = cargar_metadata_jugadores()

        # C) Carga de Catálogo de Equipos
        df_equipos_cat = cargar_catalogo_equipos()

        # D) Carga de Stats de Equipos (vista_equipos_master, sin depender de players_detalle)
        df_equipos_raw = cargar_datos_equipos_only()

        # E) Tiros: se cargan bajo demanda (lazy) en las vistas que los necesitan

except Exception as e:
    st.error(f"Error técnico cargando datos: {e}")
    st.stop()

# 4. Sidebar y Navegación
st.sidebar.image("GravityStats_Logo.png", width=300)
st.sidebar.markdown(
    """
    <div style="margin-top: -20px;">
        <h1 style="margin-top: 20px; margin-bottom: 0px; font-size: 25px; color: #dc362a;">Analytics LNBP Femenil</h1>
        <h3 style="margin-top: -25px; font-weight: bold; color: #0a173c;">GravityStats</h3>
        <h3 style="margin-top: -33px; font-weight: normal; color: #0a173c; font-size: 14px">Nada Está en el Aire</h3>
    </div>
    """,
    unsafe_allow_html=True
)

if IS_TEST:
    st.sidebar.markdown(
        '<div style="background-color:#ff4b4b;color:white;text-align:center;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:bold;margin-bottom:10px;">'
        'AMBIENTE DE PRUEBA'
        '</div>',
        unsafe_allow_html=True
    )

categoria_sel = "Femenil D1"

# --- SELECTOR DE ETAPA ---
etapa_opciones = {
    "Total":              None,
    "Temporada Regular":  1,
    "Playoffs":           "playoffs",        # etapa > 1, excluye Gran Final (4)
    "Playoffs Total":     "playoffs_total",  # etapa > 1 (incluye Gran Final)
    "Gran Final":         4,
}
st.sidebar.markdown("**Etapa:**")
etapa_sel = st.sidebar.radio(
    "Etapa:",
    list(etapa_opciones.keys()),
    index=0,
    label_visibility="collapsed",
    key="etapa_filter",
)
etapa_val = etapa_opciones[etapa_sel]

def _filtrar_etapa(frame, col="etapa"):
    """Aplica el filtro de etapa activo a un DataFrame."""
    if etapa_val is None or col not in frame.columns:
        return frame
    if isinstance(etapa_val, int):
        return frame[frame[col] == etapa_val]
    if etapa_val == "playoffs_total":
        return frame[frame[col] > 1]
    if etapa_val == "playoffs":
        return frame[(frame[col] > 1) & (frame[col] != 4)]
    return frame

# Filtrado Global del DataFrame de Jugadores (Game Logs)
if not df_raw.empty:
    df = df_raw[df_raw['Categoria'] == categoria_sel].copy()
    df = _filtrar_etapa(df)
else:
    df = pd.DataFrame()

# Filtrado Global del DataFrame de Equipos (Team-level, sin depender de players_detalle)
if not df_equipos_raw.empty:
    df_eq = df_equipos_raw[df_equipos_raw['Categoria'] == categoria_sel].copy()
    df_eq = _filtrar_etapa(df_eq)
else:
    df_eq = pd.DataFrame()

# IDs de partidos válidos para filtrar tiros (respeta la etapa seleccionada)
valid_partido_ids = set(df['id_abe'].astype(str).unique()) if not df.empty else None

# Aviso si no hay jugadores
if df.empty:
    st.sidebar.warning(f"No hay datos de stats para {categoria_sel}.")

st.sidebar.divider()

# --- CALLBACK PARA RESETEAR LA VISTA ---
# Si el usuario hace click en el menú lateral, salimos del modo "Perfil"
def reset_view():
    st.session_state.view_mode = 'main'

# Menú Principal (SIN "Perfil Jugador")
opciones_menu = ["🤝 Equipos", "📋 Equipos por partido", "🔢 Equipos totales", "4️⃣ Four Factors", "🎯 Mapa de Tiros Beta", "📊 Por partido", "🛸 Avanzadas", "📈 Totales"]
if IS_TEST:
    opciones_menu.append("🔍 Diagnóstico")

opcion = st.sidebar.radio(
    "Ir a:",
    opciones_menu,
    on_change=reset_view # Activamos el reset al cambiar
)
utils.rastrear_cambio("Vista Principal", opcion)

# --- LIMPIEZA DE NOMBRES (Alias) ---
alias_equipos = {
    "ANAHUAC QUERETARO": "Anáhuac QRO", "ANAHUAC XALAPA": "Anáhuac XAL",
    "AUTONOMA DE CHIHUAHUA": "UACH", "CETYS MEXICALI": "CETYS MXL",
    "CEU MONTERREY": "CEU", "INTERAMERICANA": "Inter",
    "TEC MTY GUADALAJARA": "Tec GDL", "TEC MTY HIDALGO": "Tec HGO",
    "TEC MTY MONTERREY": "Tec MTY", "TEC MTY PUEBLA": "Tec PUE",
    "TEC MTY SANTA FE": "Tec CSF", "TEC MTY TOLUCA": "Tec TOL",
    "UANE": "UANE", "UANL": "UANL", "UDLAP": "UDLAP",
    "UMAD": "UMAD", "UNIVERSIDAD MONTRER": "Montrer",
    "UP MEXICO": "UP MX", "UPAEP": "UPAEP",
    "ANAHUAC NORTE": "Anáhuac NTE", "CETYS TIJUANA": "CETYS TIJ",
    "MODELO MERIDA": "Modelo", "TEC MTY AGUASCALIENTES": "Tec AGS",
    "TEC MTY CEM": "Tec CEM", "TEC MTY QUERETARO": "Tec QRO",
    "UVAQ MORELIA": "UVAQ"
}

if not df.empty:
    df['equipo_nombre'] = df['equipo_nombre'].replace(alias_equipos)

if not df_eq.empty:
    df_eq['equipo_nombre'] = df_eq['equipo_nombre'].replace(alias_equipos)

# 5. Enrutador de Vistas (LÓGICA DRILL-DOWN)

# A) Si estamos en modo Perfil, mostramos SOLO el perfil (Overlay)
if st.session_state.view_mode == 'profile':
    # Botón para regresar
    if st.button("⬅️ Volver a la lista", type="secondary"):
        st.session_state.view_mode = 'main'
        st.rerun()
    
    # Renderizamos el perfil
    # OPTIMIZACIÓN: tiros se cargan solo al entrar al perfil (lazy load, cached)
    current_pid = st.session_state.selected_player_id
    df_tiros = cargar_tiros()
    if valid_partido_ids is not None:
        df_tiros = df_tiros[df_tiros['partido_id'].astype(str).isin(valid_partido_ids)]
    view_players_prfl.render_view(current_pid, df, df_players, df_rosters, df_equipos_cat, df_tiros)

# B) Si estamos en modo Normal, mostramos lo que diga el menú
else:
    if opcion == "📊 Por partido":
        if df.empty:
            st.error("No hay datos disponibles.")
        else:
            view_players_avg.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "🛸 Avanzadas":
        if df.empty:
            st.error("No hay datos disponibles.")
        else:
            view_players_adv.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "📈 Totales":
        if df.empty:
            st.error("No hay datos disponibles.")
        else:
            view_players_tot.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "🤝 Equipos":
        view_equipos_smry.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "📋 Equipos por partido":
        view_equipos_avg.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "🔢 Equipos totales":
        view_equipos_tot.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "4️⃣ Four Factors":
        view_equipos_4f.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "🎯 Mapa de Tiros Beta":
        # OPTIMIZACIÓN: tiros se cargan solo al entrar a esta vista (lazy load)
        df_tiros = cargar_tiros()
        if valid_partido_ids is not None:
            df_tiros = df_tiros[df_tiros['partido_id'].astype(str).isin(valid_partido_ids)]
        view_equipos_tiros.render_view(
            df_tiros,
            df_equipos_raw,
            categoria_sel,
            alias_equipos,
            df_equipos_cat
        )

    elif opcion == "🔍 Diagnóstico":
        st.title("Diagnóstico: partidos por equipo")
        st.caption("Vista temporal para depuración — eliminar después.")
        st.write(f"Categoría seleccionada: **{categoria_sel}**")

        # ============================================================
        # A) DATOS CRUDOS DE SUPABASE (sin alias, sin filtro de categoría)
        # ============================================================
        st.header("A. Datos crudos de Supabase")

        # A1: vista_equipos_master
        st.subheader("A1. vista_equipos_master (crudo)")
        try:
            df_veq = cargar_datos_equipos_only()
        except Exception as e:
            df_veq = pd.DataFrame()
            st.error(f"Error: {e}")

        if not df_veq.empty:
            st.write(f"Filas totales: **{len(df_veq)}** | Columnas: **{len(df_veq.columns)}**")
            st.write(f"Categorías encontradas: {df_veq['Categoria'].unique().tolist()}")
            st.write(f"Equipos encontrados (sin filtro): {df_veq['equipo_nombre'].nunique()}")
            veq_cat = df_veq[df_veq['Categoria'] == categoria_sel]
            veq_dedup = veq_cat.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
            conteo_veq = veq_dedup.groupby('equipo_nombre')['id_abe'].nunique().sort_values(ascending=False).reset_index()
            conteo_veq.columns = ['Equipo (nombre original)', 'Partidos']
            st.dataframe(conteo_veq, hide_index=True)
        else:
            st.warning("Sin datos de vista_equipos_master")

        st.divider()

        # A2: vista_analitica_master
        st.subheader("A2. vista_analitica_master (crudo, dedup juego-equipo)")
        if not df_raw.empty:
            st.write(f"Filas totales (jugadores): **{len(df_raw)}**")
            st.write(f"Categorías: {df_raw['Categoria'].unique().tolist()}")
            van_cat = df_raw[df_raw['Categoria'] == categoria_sel]
            st.write(f"Filas en {categoria_sel}: **{len(van_cat)}**")
            van_dedup = van_cat.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
            st.write(f"Filas tras dedup (juego-equipo): **{len(van_dedup)}**")
            conteo_van = van_dedup.groupby('equipo_nombre')['id_abe'].nunique().sort_values(ascending=False).reset_index()
            conteo_van.columns = ['Equipo (nombre original)', 'Partidos']
            st.dataframe(conteo_van, hide_index=True)

            # Columnas disponibles
            needed = ['Tm_Score', 'Opp_Score', 'Tm_FG', 'Tm_FGA', 'Tm_ORB', 'Tm_DRB',
                      'Tm_TOV', 'Tm_FTA', 'Opp_FG', 'Opp_FGA', 'Opp_ORB', 'Opp_DRB',
                      'Opp_FTA', 'Opp_TOV', 'Fecha']
            missing = [c for c in needed if c not in df_raw.columns]
            if missing:
                st.error(f"Columnas FALTANTES: {missing}")
            else:
                st.success("Todas las columnas Tm_/Opp_ necesarias están presentes.")
        else:
            st.warning("Sin datos de vista_analitica_master")

        st.divider()

        # ============================================================
        # B) EFECTO DEL ALIAS MAPPING
        # ============================================================
        st.header("B. Efecto del mapeo de alias")

        # Detectar colisiones
        alias_valores = list(alias_equipos.values())
        alias_duplicados = [v for v in set(alias_valores) if alias_valores.count(v) > 1]
        if alias_duplicados:
            st.error(f"COLISIONES DE ALIAS: los siguientes alias apuntan a más de un equipo:")
            for dup in alias_duplicados:
                originales = [k for k, v in alias_equipos.items() if v == dup]
                st.write(f"  - **'{dup}'** <-- {originales}")
        else:
            st.success("No hay colisiones de alias (cada alias es único).")

        if not df_raw.empty:
            van_cat_raw = df_raw[df_raw['Categoria'] == categoria_sel].copy()

            # Antes de alias
            pre_dedup = van_cat_raw.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
            pre_conteo = pre_dedup.groupby('equipo_nombre')['id_abe'].nunique()

            # Después de alias
            van_cat_alias = van_cat_raw.copy()
            van_cat_alias['equipo_nombre'] = van_cat_alias['equipo_nombre'].replace(alias_equipos)
            post_dedup = van_cat_alias.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
            post_conteo = post_dedup.groupby('equipo_nombre')['id_abe'].nunique()

            comp_alias = pd.DataFrame({
                'pre_alias': pre_conteo,
                'post_alias': post_conteo,
            }).fillna(0).astype(int)
            comp_alias['cambio'] = comp_alias['post_alias'] - comp_alias['pre_alias']
            comp_alias = comp_alias.sort_values('cambio', ascending=False)
            st.dataframe(comp_alias)

            cambios = comp_alias[comp_alias['cambio'] != 0]
            if not cambios.empty:
                st.warning(f"HAY {len(cambios)} EQUIPOS CUYO CONTEO CAMBIA POR EL ALIAS:")
                st.dataframe(cambios)
            else:
                st.info("El alias no cambia el conteo de partidos de ningún equipo.")

        st.divider()

        # ============================================================
        # C) LO QUE REALMENTE RECIBE equipos_smry.py
        # ============================================================
        st.header("C. Lo que realmente recibe equipos_smry.py")
        st.write(f"`df` = df_raw filtrado por **{categoria_sel}** + alias aplicados")
        if not df.empty:
            st.write(f"Filas totales en df: **{len(df)}**")
            df_dedup = df.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
            st.write(f"Filas tras dedup (juego-equipo): **{len(df_dedup)}**")
            conteo_real = df_dedup.groupby('equipo_nombre')['id_abe'].nunique().sort_values(ascending=False).reset_index()
            conteo_real.columns = ['Equipo (con alias)', 'Partidos']
            st.dataframe(conteo_real, hide_index=True)
            st.write(f"Total equipos: **{conteo_real.shape[0]}** | Max partidos: **{conteo_real['Partidos'].max()}** | Min partidos: **{conteo_real['Partidos'].min()}**")
        else:
            st.error("df está vacío.")

        st.divider()

        # ============================================================
        # D) DETALLE POR EQUIPO: id_abe's de cada equipo
        # ============================================================
        st.header("D. Detalle: IDs de partidos por equipo")
        if not df.empty:
            equipo_sel_diag = st.selectbox("Selecciona un equipo para ver sus partidos:",
                                           sorted(df['equipo_nombre'].unique()), key="diag_eq")
            sub = df[df['equipo_nombre'] == equipo_sel_diag]
            ids_unicos = sorted(sub['id_abe'].unique())
            st.write(f"**{equipo_sel_diag}** tiene **{len(ids_unicos)}** id_abe únicos:")
            st.write(ids_unicos)

            # Mostrar una fila por partido con las columnas clave
            cols_show = ['id_abe', 'equipo_nombre', 'Opp_Name', 'Fecha', 'Tm_Score', 'Opp_Score']
            cols_show = [c for c in cols_show if c in sub.columns]
            sub_dedup = sub.drop_duplicates(subset=['id_abe']).sort_values('Fecha', ascending=False)
            st.dataframe(sub_dedup[cols_show], hide_index=True)

            # Checar si hay nombres originales distintos mapeados a este alias
            if not df_raw.empty:
                raw_cat = df_raw[df_raw['Categoria'] == categoria_sel]
                raw_cat_alias = raw_cat.copy()
                raw_cat_alias['alias'] = raw_cat_alias['equipo_nombre'].replace(alias_equipos)
                nombres_orig = raw_cat_alias[raw_cat_alias['alias'] == equipo_sel_diag]['equipo_nombre'].unique()
                if len(nombres_orig) > 1:
                    st.error(f"ESTE ALIAS AGRUPA VARIOS EQUIPOS ORIGINALES: {list(nombres_orig)}")
                    for orig in nombres_orig:
                        n = raw_cat[raw_cat['equipo_nombre'] == orig].drop_duplicates(subset=['id_abe'])['id_abe'].nunique()
                        st.write(f"  - {orig}: {n} partidos")
                else:
                    st.info(f"Nombre original: {nombres_orig[0] if len(nombres_orig) else '?'}")

        st.divider()

        # ============================================================
        # E) VALIDACIÓN DE LIMPIEZA
        # ============================================================
        st.header("E. Limpieza de contaminación (auto-rival + categoría cruzada)")
        st.caption(
            "cargar_base_datos() ahora elimina filas donde Opp_Name == equipo_nombre "
            "y resuelve juegos duplicados entre categorías. "
            "Comparar estos totales con el sitio de la liga."
        )
        if not df_raw.empty:
            for cat in ["Femenil D1", "Varonil D1"]:
                cat_data = df_raw[df_raw['Categoria'] == cat]
                if cat_data.empty:
                    st.write(f"**{cat}**: sin datos")
                    continue
                dedup = cat_data.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
                conteo = (dedup.groupby('equipo_nombre')['id_abe']
                          .nunique().sort_values(ascending=False)
                          .reset_index())
                conteo.columns = ['Equipo', 'Partidos']
                st.write(f"**{cat}** — {conteo['Equipo'].nunique()} equipos, "
                         f"max {conteo['Partidos'].max()} partidos")
                st.dataframe(conteo, hide_index=True, height=200)
