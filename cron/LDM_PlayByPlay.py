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
def safe_get(d, k, default=None):
    val = d.get(k)
    return val if val is not None else default

def safe_int(val):
    try:
        return int(float(val))
    except:
        return 0

def clean_name(name):
    if not name: return ""
    return str(name).strip().title()

def trunc(val, max_len=50):
    """Trunca un string al largo maximo de la columna varchar."""
    s = str(val) if val else ""
    return s[:max_len]

def clean_qualifier(val):
    """
    Convierte una lista ['a', 'b'] en un string limpio 'a, b'.
    Si ya es texto o nulo, lo maneja bien.
    """
    if val is None: return ""
    if isinstance(val, list):
        return ", ".join(str(x) for x in val)
    return str(val)

# --- CARGA DE CATALOGOS ---

def cargar_contexto(supabase):
    """Carga equipos (via team_utils) y rosters."""
    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = team_utils.cargar_mapa_equipos(supabase)

    # Rosters (Mapa: ID_Equipo + Camiseta -> ID_Jugador)
    print("📚 Cargando rosters...")
    try:
        res_r = supabase.table("rosters").select("equipo_id, shirt_number, player_id").execute()
        rows_r = res_r.data if hasattr(res_r, 'data') else res_r

        mapa_rosters = {}
        for r in rows_r:
            eid = r.get('equipo_id')
            num = r.get('shirt_number')
            pid = r.get('player_id')
            if eid and num is not None:
                mapa_rosters[(eid, num)] = pid
        print(f"   -> {len(rows_r)} registros de roster cargados.")
    except Exception as e:
        print(f"❌ Error cargando rosters: {e}")
        return {}, {}, [], {}, {}, {}, set()

    return mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup, mapa_rosters

def buscar_jugador(team_id, shirt_num, mapa_rosters):
    if not team_id or shirt_num is None: return None
    return mapa_rosters.get((team_id, safe_int(shirt_num)))

# --- PROCESO PRINCIPAL ---

def procesar_pbp():
    print("🏀 INICIANDO INGESTA DE PLAY-BY-PLAY (V3 LIMPIA)")

    try:
        supabase = create_client(URL, KEY)
    except Exception as e:
        print(f"❌ Error conexion inicial: {e}")
        return

    m_eq_n, m_eq_c, equipos_raw, m_eq_n_comp, m_eq_c_comp, codigos_dup, m_rosters = cargar_contexto(supabase)
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

        print(f"⚡ Procesando PBP: Partido {match_id_str}")

        try:
            data = requests.get(json_url, timeout=10).json()
        except: continue

        # Identificar Equipos (con normalización + fuzzy)
        tms = data.get('tm', {})
        if not tms or len(tms) < 2: continue

        team_ids_map = {}

        for k, t_data in tms.items():
            nombre_j = t_data.get('name', '')
            codigo_j = t_data.get('code', '')
            if not nombre_j and not codigo_j: continue
            eid, _ = team_utils.buscar_id_equipo(
                nombre_j, codigo_j, m_eq_n, m_eq_c, equipos_raw,
                competicion_id=comp_id, mapa_nombre_comp=m_eq_n_comp,
                mapa_codigo_comp=m_eq_c_comp,
                codigos_duplicados_comp=codigos_dup
            )
            if eid:
                team_ids_map[k] = eid
            else:
                team_utils.log_equipo_no_encontrado(nombre_j, codigo_j, match_id_str, "LDM_PBP")

        if len(team_ids_map) < 2:
            print(f"   ⚠️ Faltan equipos para PBP del partido {match_id_str}. Saltando.")
            continue

        pbp_list = data.get('pbp', [])
        payloads = []

        for action in pbp_list:
            act_num = safe_int(action.get('actionNumber'))
            t_num_json = str(action.get('tno'))

            equipo_id = team_ids_map.get(t_num_json)
            player_id = None
            shirt_num = action.get('shirtNumber')

            if equipo_id and shirt_num is not None:
                player_id = buscar_jugador(equipo_id, shirt_num, m_rosters)

            raw_qualifier = action.get('qualifier')
            qualifier_clean = clean_qualifier(raw_qualifier)

            pbp_row = {
                "partido_id": int(match_id_str),
                "actionnumber": act_num,
                "equipo_id": equipo_id,
                "player_id": player_id,

                "tno": safe_int(t_num_json) if t_num_json.isdigit() else None,
                "pno": safe_int(action.get('pno')),
                "gt": trunc(action.get('gt', '')),
                "clock": trunc(action.get('clock', '')),
                "s1": safe_int(action.get('s1')),
                "s2": safe_int(action.get('s2')),
                "lead": safe_int(action.get('lead')),
                "period": safe_int(action.get('period')),
                "periodtype": trunc(action.get('periodType', '')),
                "success": bool(action.get('success', 0)),
                "actiontype": trunc(action.get('actionType', '')),
                "previousaction": safe_int(action.get('previousAction')),

                "qualifier": trunc(qualifier_clean, 200),

                "subtype": trunc(action.get('subType', '')),
                "scoring": trunc(action.get('scoring', '')),
                "shirtnumber": safe_int(shirt_num),
                "player": trunc(action.get('player', '')),
                "firstname": trunc(action.get('firstName', '')),
                "familyname": trunc(action.get('familyName', ''))
            }
            payloads.append(pbp_row)

        if payloads:
            try:
                chunk_size = 500
                for i in range(0, len(payloads), chunk_size):
                    batch = payloads[i : i + chunk_size]
                    supabase.table("acciones_partido").upsert(batch, on_conflict="partido_id,actionnumber").execute()

                print(f"   ✅ {len(payloads)} acciones insertadas.")
            except Exception as e:
                print(f"   ❌ Error insertando: {e}")

    print("🏁 Fin del PBP.")

if __name__ == "__main__":
    procesar_pbp()
