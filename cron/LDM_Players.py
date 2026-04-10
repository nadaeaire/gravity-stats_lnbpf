import os
import json
import requests
import time
from datetime import datetime
from supabase import create_client, Client
import team_utils

# --- CONFIGURACION ---
COMPETICIONES_VALIDAS = {42033, 42034}

# LLAVES DE SUPABASE (desde variables de entorno)
URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")

# --- UTILIDADES ---
def safe_get(d, k, default=0):
    val = d.get(k, default)
    return val if val is not None else default

def safe_int(val):
    try:
        return int(float(val))
    except:
        return 0

def clean_name(name):
    if not name: return ""
    return str(name).strip().title()

def time_to_text(val):
    if not val: return "00:00"
    return str(val)

# --- MAPEO DE STATS ---
def map_player_stats(p_data):
    mapping = {
        'sMinutes': 'sminutes',
        'sPoints': 'spoints',
        'sPlusMinusPoints': 'splusminuspoints',
        'sFieldGoalsMade': 'sfieldgoalsmade',
        'sFieldGoalsAttempted': 'sfieldgoalsattempted',
        'sTwoPointersMade': 'stwopointersmade',
        'sTwoPointersAttempted': 'stwopointersattempted',
        'sThreePointersMade': 'sthreepointersmade',
        'sThreePointersAttempted': 'sthreepointersattempted',
        'sFreeThrowsMade': 'sfreethrowsmade',
        'sFreeThrowsAttempted': 'sfreethrowsattempted',
        'sReboundsOffensive': 'sreboundsoffensive',
        'sReboundsDefensive': 'sreboundsdefensive',
        'sReboundsTotal': 'sreboundstotal',
        'sAssists': 'sassists',
        'sTurnovers': 'sturnovers',
        'sSteals': 'ssteals',
        'sBlocks': 'sblocks',
        'sBlocksReceived': 'sblocksreceived',
        'sFoulsPersonal': 'sfoulspersonal',
        'sFoulsOn': 'sfoulson',
        'sPointsInThePaint': 'spointsinthepaint',
        'sPointsSecondChance': 'spointssecondchance',
        'sPointsFastBreak': 'spointsfastbreak'
    }
    row = {}
    for json_k, db_col in mapping.items():
        val = safe_get(p_data, json_k, 0)
        if db_col == 'sminutes':
            row[db_col] = time_to_text(val)
        else:
            row[db_col] = val
    return row

# --- LOGICA DE IDENTIDAD (V3) ---

def get_or_create_player(supabase, team_id, p_json, comp_id):
    """
    Estrategia V3: Busca primero en roster (equipo+camiseta), luego por nombre.
    """
    # 1. Limpieza de datos
    raw_first = p_json.get('firstName', '')
    raw_family = p_json.get('familyName', '')

    if not raw_first and not raw_family:
        full_arr = p_json.get('name', '').split()
        if len(full_arr) > 0: raw_first = full_arr[0]
        if len(full_arr) > 1: raw_family = " ".join(full_arr[1:])

    first_name_clean = clean_name(raw_first)
    family_name_clean = clean_name(raw_family)
    shirt_num = safe_int(p_json.get('shirtNumber', 0))

    player_id = None

    # 2. CANDADO PRINCIPAL: Buscar en ROSTER por equipo + camiseta + competicion
    try:
        res_r = supabase.table("rosters")\
            .select("player_id")\
            .eq("equipo_id", team_id)\
            .eq("shirt_number", shirt_num)\
            .eq("competicion_id", comp_id)\
            .execute()

        roster_data = res_r.data if hasattr(res_r, 'data') else res_r
        if roster_data and len(roster_data) > 0:
            return roster_data[0]['player_id']
    except Exception as e:
        print(f"   ⚠️ Error buscando roster: {e}")

    # 3. FALLBACK: Buscar en PLAYERS por nombre
    try:
        res_p = supabase.table("players")\
            .select("player_id")\
            .ilike("first_name", first_name_clean)\
            .ilike("family_name", family_name_clean)\
            .execute()

        found_players = res_p.data if hasattr(res_p, 'data') else res_p

        if found_players and len(found_players) > 0:
            player_id = found_players[0]['player_id']
    except Exception as e:
        print(f"   ⚠️ Error buscando jugador: {e}")

    # 4. CREACION (Solo si no existe en roster NI en players)
    if not player_id:
        print(f"   ✨ Creando NUEVA: {first_name_clean} {family_name_clean} (#{shirt_num})")
        new_player = {
            "first_name": first_name_clean,
            "family_name": family_name_clean
        }
        try:
            res_ins = supabase.table("players").insert(new_player).execute()
            data_ins = res_ins.data if hasattr(res_ins, 'data') else res_ins
            if data_ins:
                player_id = data_ins[0]['player_id']
            else:
                return None
        except Exception as e:
            print(f"   ❌ Error insertando player: {e}")
            return None

    # 5. GESTION DE ROSTER (upsert para evitar duplicados)
    try:
        new_roster = {
            "player_id": player_id,
            "equipo_id": team_id,
            "competicion_id": comp_id,
            "shirt_number": shirt_num,
            "effective_start_date": "2026-01-24"
        }
        supabase.table("rosters").upsert(
            new_roster,
            on_conflict="player_id,competicion_id,effective_start_date"
        ).execute()

    except Exception as e:
        print(f"   ⚠️ Nota roster: {e}")

    return player_id

# --- CARGA EQUIPOS (delegada a team_utils) ---

# --- MAIN ---

def procesar_jugadores():
    print("🏀 INICIANDO INGESTA DE JUGADORES (V3 FINAL)")

    supabase = create_client(URL, KEY)

    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = team_utils.cargar_mapa_equipos(supabase)
    records = team_utils.cargar_partidos_desde_db(supabase)

    procesados = set()

    for row in records:
        match_id_str = str(row.get('matchId', '')).strip()
        json_url = row.get('game_url', '')
        comp_id = int(row.get('competitionId', 0))

        if not match_id_str or not json_url: continue
        if match_id_str in procesados: continue
        procesados.add(match_id_str)
        if comp_id not in COMPETICIONES_VALIDAS: continue

        print(f"⚡ Procesando Jugadores: Partido {match_id_str}")

        try:
            data = requests.get(json_url, timeout=10).json()
        except: continue

        tms = data.get('tm', {})
        if not tms or len(tms) < 2: continue

        for k_team, t_data in tms.items():
            nombre_j = t_data.get('name', '')
            codigo_j = t_data.get('code', '')
            if not nombre_j and not codigo_j: continue
            team_db_id, _ = team_utils.buscar_id_equipo(
                nombre_j, codigo_j, mapa_n, mapa_c, equipos_raw,
                competicion_id=comp_id, mapa_nombre_comp=mapa_n_comp,
                mapa_codigo_comp=mapa_c_comp,
                codigos_duplicados_comp=codigos_dup
            )
            if not team_db_id:
                team_utils.log_equipo_no_encontrado(nombre_j, codigo_j, match_id_str, "LDM_Players")
                continue

            players_dict = t_data.get('pl', {})
            payloads_detalle = []

            for k_pl, p_data in players_dict.items():
                pid = get_or_create_player(supabase, team_db_id, p_data, comp_id)
                if not pid: continue

                stats_row = map_player_stats(p_data)

                stats_row['player_id'] = pid
                stats_row['partido_id'] = int(match_id_str)
                stats_row['active'] = bool(p_data.get('active', 0))
                stats_row['starter'] = bool(p_data.get('starter', 0))
                stats_row['captain'] = bool(p_data.get('captain', 0))

                payloads_detalle.append(stats_row)

            if payloads_detalle:
                try:
                    supabase.table("players_detalle").upsert(payloads_detalle, on_conflict="player_id,partido_id").execute()
                    print(f"   ✅ {len(payloads_detalle)} jugadores procesados (Equipo {t_data.get('code')})")
                except Exception as e:
                    print(f"   ❌ Error guardando stats: {e}")

    print("🏁 Fin.")

if __name__ == "__main__":
    procesar_jugadores()
