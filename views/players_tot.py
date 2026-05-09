import streamlit as st
import pandas as pd
import numpy as np
import math
import modules.utils as utils


def render_view(df, df_players, df_rosters, categoria_sel):
    st.title(f"Totales por jugadora | {categoria_sel}")

    # --- 0. METADATA ---
    df_players['player_id_str'] = df_players['player_id'].astype(str)
    df_rosters['player_id_str'] = df_rosters['player_id'].astype(str)

    mapa_posicion = {}
    if not df_rosters.empty and 'effective_start_date' in df_rosters.columns:
        df_last_pos = df_rosters.sort_values('effective_start_date', ascending=False).drop_duplicates(subset=['player_id_str'])
        mapa_posicion = pd.Series(df_last_pos.playing_position.values, index=df_last_pos.player_id_str).to_dict()

    mapa_altura = {}
    mapa_peso   = {}
    if not df_players.empty:
        df_players['height_cm'] = pd.to_numeric(df_players['height_cm'], errors='coerce').fillna(0)
        df_players['weight_kg'] = pd.to_numeric(df_players['weight_kg'], errors='coerce').fillna(0)
        mapa_altura = pd.Series(df_players.height_cm.values, index=df_players.player_id_str).to_dict()
        mapa_peso   = pd.Series(df_players.weight_kg.values, index=df_players.player_id_str).to_dict()

    # --- 1. FILTROS BÁSICOS ---
    lista_equipos = sorted(df['equipo_nombre'].unique())
    lista_equipos.insert(0, "Todos")

    col_team, _ = st.columns([1, 1])
    with col_team:
        equipo_filtro = st.selectbox("Filtrar por Equipo:", lista_equipos, key="sel_team_tot")
        utils.rastrear_cambio("Filtro Equipo (Tot)", equipo_filtro)

    # --- 2. FILTRADO DE DATA ---
    df_view = df[df['equipo_nombre'] == equipo_filtro] if equipo_filtro != "Todos" else df
    df_active = df_view[df_view['sMinutes'] > 0].copy()

    # --- 3. AGRUPACIÓN (SUMA) ---
    leaderboard = df_active.groupby(['id_player', 'Nombre', 'equipo_nombre']).agg({
        'sPoints':              'sum',
        'sReboundsTotal':       'sum',
        'sAssists':             'sum',
        'sThreePointersMade':   'sum',
        'sMinutes':             'sum',
        'starter':              'sum',
        'sFieldGoalsMade':      'sum',
        'sFieldGoalsAttempted': 'sum',
        'sTwoPointersMade':     'sum',
        'sTwoPointersAttempted':'sum',
        'sThreePointersAttempted': 'sum',
        'sFreeThrowsMade':      'sum',
        'sFreeThrowsAttempted': 'sum',
        'sReboundsOffensive':   'sum',
        'sReboundsDefensive':   'sum',
        'sTurnovers':           'sum',
        'sSteals':              'sum',
        'sBlocks':              'sum',
        'sFoulsPersonal':       'sum',
        'sFoulsOn':             'sum',
        'id_abe':               'count',
    }).reset_index()

    leaderboard.rename(columns={
        'id_abe':               'GP',
        'sMinutes':             'MIN',
        'starter':              'JT',
        'sFieldGoalsMade':      'FGM',
        'sFieldGoalsAttempted': 'FGA',
        'sTwoPointersMade':     '2PM',
        'sTwoPointersAttempted':'2PA',
        'sThreePointersAttempted': '3PA',
        'sFreeThrowsMade':      'FTM',
        'sFreeThrowsAttempted': 'FTA',
        'sReboundsOffensive':   'RBO',
        'sReboundsDefensive':   'RBD',
        'sTurnovers':           'TOV',
        'sSteals':              'STL',
        'sBlocks':              'BLK',
        'sFoulsPersonal':       'PF',
        'sFoulsOn':             'PFR',
    }, inplace=True)

    def calc_pct(num, den):
        return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den != 0) * 100

    leaderboard['FG%'] = calc_pct(leaderboard['FGM'],                  leaderboard['FGA'])
    leaderboard['2P%'] = calc_pct(leaderboard['2PM'],                  leaderboard['2PA'])
    leaderboard['3P%'] = calc_pct(leaderboard['sThreePointersMade'],   leaderboard['3PA'])
    leaderboard['FT%'] = calc_pct(leaderboard['FTM'],                  leaderboard['FTA'])

    # --- 4. ENRIQUECIMIENTO ---
    leaderboard['id_player_str'] = leaderboard['id_player'].astype(str)
    leaderboard['Pos']    = leaderboard['id_player_str'].map(mapa_posicion).fillna("N/A")
    leaderboard['Altura'] = leaderboard['id_player_str'].map(mapa_altura).fillna(0)

    # --- 5. FILTROS AVANZADOS ---
    st.markdown("---")
    c_search, c_pos, c_hgt = st.columns([1.5, 1.5, 2])
    with c_search:
        search_query = st.text_input("🔍 Buscar jugadora", placeholder="Nombre o Apellido...", key="search_tot")
        if search_query:
            utils.rastrear_cambio("Búsqueda Texto (Tot)", search_query)
    with c_pos:
        opciones_pos = sorted(leaderboard[leaderboard['Pos'] != "N/A"]['Pos'].unique())
        filtro_posicion = st.multiselect("Posición", options=opciones_pos, placeholder="Todas", key="pos_tot")
        if filtro_posicion:
            utils.rastrear_cambio("Filtro Posición (Tot)", str(filtro_posicion))
    with c_hgt:
        alturas_validas = leaderboard[leaderboard['Altura'] > 0]['Altura']
        if not alturas_validas.empty:
            min_h, max_h = int(alturas_validas.min()), int(alturas_validas.max())
        else:
            min_h, max_h = 150, 210
        if min_h == max_h:
            min_h = max(140, min_h - 10)
            max_h = min(230, max_h + 10)
        filtro_altura = st.slider("Rango de Estatura (cm)", min_value=min_h, max_value=max_h,
                                  value=(min_h, max_h), key="slider_height_tot")

    # --- 6. APLICACIÓN DE FILTROS ---
    if search_query:
        leaderboard = leaderboard[leaderboard['Nombre'].str.contains(search_query, case=False, na=False)]
    if filtro_posicion:
        leaderboard = leaderboard[leaderboard['Pos'].isin(filtro_posicion)]
    if filtro_altura != (min_h, max_h):
        leaderboard = leaderboard[(leaderboard['Altura'] >= filtro_altura[0]) & (leaderboard['Altura'] <= filtro_altura[1])]

    # --- 7. ORDENAMIENTO ---
    if 'sort_col_tot' not in st.session_state: st.session_state.sort_col_tot = 'sPoints'
    if 'sort_asc_tot' not in st.session_state: st.session_state.sort_asc_tot = False
    if 'page_number_tot' not in st.session_state: st.session_state.page_number_tot = 0

    opciones_orden = {
        "MIN": "MIN", "FGM": "FGM", "FGA": "FGA", "FG%": "FG%",
        "2PM": "2PM", "2PA": "2PA", "2P%": "2P%",
        "3PM": "sThreePointersMade", "3PA": "3PA", "3P%": "3P%",
        "FTM": "FTM", "FTA": "FTA", "FT%": "FT%",
        "RBO": "RBO", "RBD": "RBD", "RBT": "sReboundsTotal",
        "AST": "sAssists", "TOV": "TOV", "STL": "STL",
        "BLK": "BLK", "PF": "PF", "PFR": "PFR",
        "PTS": "sPoints", "ALT": "Altura",
    }
    nombres_largos = {
        "PTS": "Puntos totales", "RBT": "Rebotes totales",
        "AST": "Asistencias",    "MIN": "Minutos totales",
        "3PM": "Triples anotados","FGM": "Tiros anotados",
        "FG%": "% de Campo",     "2P%": "% de Dobles",
        "FT%": "% de Libres",    "3P%": "% de Triples",
        "ALT": "Altura (cm)",
    }

    st.markdown("##### Ordenar por:")
    lista_opciones = list(opciones_orden.keys())
    try:
        idx = lista_opciones.index("PTS")
    except ValueError:
        idx = 0

    sort_key_sel = st.radio("Métrica:", options=lista_opciones, index=idx,
                            horizontal=True, label_visibility="collapsed", key="rad_tot")
    utils.rastrear_cambio("Ordenar Por (Tot)", sort_key_sel)

    nueva_col = opciones_orden[sort_key_sel]
    if st.session_state.sort_col_tot != nueva_col:
        st.session_state.sort_col_tot = nueva_col
        st.session_state.sort_asc_tot = False
        st.session_state.page_number_tot = 0

    flecha = "⬆️ Menor a Mayor" if st.session_state.sort_asc_tot else "⬇️ Mayor a Menor"
    st.caption(f"Ordenando por **{nombres_largos.get(sort_key_sel, sort_key_sel)}** ({flecha})")

    c_btn, _, c_check = st.columns([1.5, 6, 3])
    with c_btn:
        if st.button("🔄 Invertir Orden", key="btn_inv_tot", use_container_width=True):
            st.session_state.sort_asc_tot = not st.session_state.sort_asc_tot
            st.rerun()
    with c_check:
        min_games = max(1, int(leaderboard['GP'].max() * 0.40)) if not leaderboard.empty else 1
        qualified_on = st.checkbox(f"Qualified: mínimo {min_games} juegos", value=False, key="chk_tot")
        utils.rastrear_cambio("Filtro Qualified (Tot)", qualified_on)

    if qualified_on:
        leaderboard = leaderboard[leaderboard['GP'] >= min_games]

    leaderboard = leaderboard.sort_values(by=st.session_state.sort_col_tot,
                                          ascending=st.session_state.sort_asc_tot)

    # --- 8. TABLA CON PAGINACIÓN ---
    ROWS_PER_PAGE = 30
    total_rows  = len(leaderboard)
    total_pages = math.ceil(total_rows / ROWS_PER_PAGE) if total_rows > 0 else 1

    if st.session_state.page_number_tot >= total_pages:
        st.session_state.page_number_tot = 0

    start_idx = st.session_state.page_number_tot * ROWS_PER_PAGE
    df_page   = leaderboard.iloc[start_idx:start_idx + ROWS_PER_PAGE]

    orden_columnas = [
        "Nombre", "equipo_nombre", "Pos", "GP", "JT", "MIN",
        "FGM", "FGA", "FG%", "2PM", "2PA", "2P%",
        "sThreePointersMade", "3PA", "3P%", "FTM", "FTA", "FT%",
        "RBO", "RBD", "sReboundsTotal", "sAssists",
        "TOV", "STL", "BLK", "PF", "PFR", "sPoints", "Altura",
    ]
    cols_finales = [c for c in orden_columnas if c in df_page.columns]

    event = st.dataframe(
        df_page[cols_finales],
        hide_index=True,
        use_container_width=True,
        height=(len(df_page) + 1) * 35 + 3,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Nombre":             st.column_config.TextColumn("Nombre"),
            "equipo_nombre":      st.column_config.TextColumn("Equipo"),
            "Pos":                st.column_config.TextColumn("Pos"),
            "Altura":             st.column_config.NumberColumn("ALT",  format="%d"),
            "GP":                 st.column_config.NumberColumn("JJ",   format="%d"),
            "JT":                 st.column_config.NumberColumn("JT",   format="%d"),
            "MIN":                st.column_config.NumberColumn("MIN",  format="%.1f"),
            "sPoints":            st.column_config.NumberColumn("PTS",  format="%d"),
            "sReboundsTotal":     st.column_config.NumberColumn("RBT",  format="%d"),
            "sAssists":           st.column_config.NumberColumn("AST",  format="%d"),
            "sThreePointersMade": st.column_config.NumberColumn("3PM",  format="%d"),
            "FGM":                st.column_config.NumberColumn("FGM",  format="%d"),
            "FGA":                st.column_config.NumberColumn("FGA",  format="%d"),
            "2PM":                st.column_config.NumberColumn("2PM",  format="%d"),
            "2PA":                st.column_config.NumberColumn("2PA",  format="%d"),
            "3PA":                st.column_config.NumberColumn("3PA",  format="%d"),
            "FTM":                st.column_config.NumberColumn("FTM",  format="%d"),
            "FTA":                st.column_config.NumberColumn("FTA",  format="%d"),
            "RBO":                st.column_config.NumberColumn("RBO",  format="%d"),
            "RBD":                st.column_config.NumberColumn("RBD",  format="%d"),
            "TOV":                st.column_config.NumberColumn("TOV",  format="%d"),
            "STL":                st.column_config.NumberColumn("STL",  format="%d"),
            "BLK":                st.column_config.NumberColumn("BLK",  format="%d"),
            "PF":                 st.column_config.NumberColumn("PF",   format="%d"),
            "PFR":                st.column_config.NumberColumn("PFR",  format="%d"),
            "FG%":                st.column_config.NumberColumn("FG%",  format="%.1f%%"),
            "2P%":                st.column_config.NumberColumn("2P%",  format="%.1f%%"),
            "FT%":                st.column_config.NumberColumn("FT%",  format="%.1f%%"),
            "3P%":                st.column_config.NumberColumn("3P%",  format="%.1f%%"),
        }
    )

    # Navegación a perfil al hacer click
    if len(event.selection.rows) > 0:
        selected_row_idx = event.selection.rows[0]
        player_id_sel = df_page.iloc[selected_row_idx]['id_player']
        st.session_state['selected_player_id'] = player_id_sel
        st.session_state['view_mode'] = 'profile'
        st.rerun()

    # Paginación
    c_p1, c_pi, c_p2 = st.columns([1, 2, 1])
    with c_p1:
        if st.session_state.page_number_tot > 0:
            if st.button("⬅️ Anterior", key="prev_tot"):
                st.session_state.page_number_tot -= 1
                st.rerun()
    with c_pi:
        if total_pages > 0:
            st.markdown(
                f"<div style='text-align:center'>Página <b>{st.session_state.page_number_tot + 1}</b> de <b>{total_pages}</b></div>",
                unsafe_allow_html=True
            )
        else:
            st.warning("No hay jugadoras que coincidan con los filtros.")
    with c_p2:
        if st.session_state.page_number_tot < total_pages - 1:
            if st.button("Siguiente ➡️", key="next_tot"):
                st.session_state.page_number_tot += 1
                st.rerun()
