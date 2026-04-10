import os
import json
import requests
import time
from datetime import datetime
from supabase import create_client, Client
import team_utils
from tiro_zonas import classify_shot

# --- CONFIGURACION ---
COMPETICIONES_VALIDAS = {42033, 42034}

# LLAVES DE SUPABASE (desde variables de entorno)
URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")

# --- UTILIDADES ---
def safe_int(val):
    try: return int(float(val))
    except: return 0

def safe_float(val):
    try: return float(val)
    except: return 0.0

def clean_name(name):
    if not name: return ""
    return str(name).strip().title()

# --- CARGA DE CONTEXTO ---
def cargar_contexto(supabase):
    """Carga equipos (via team_utils) y rosters."""
    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = team_utils.cargar_mapa_equipos(supabase)

    # Rosters (Mapa: ID_Equipo + # -> ID_Jugador)
    print("📚 Cargando rosters...")
    try:
        res = supabase.table("rosters").select("equipo_id, shirt_number, player_id").execute()
        rosters = res.data if hasattr(res, 'data') else res
        mapa_rosters = {}
        for r in rosters:
            eid = r.get('equipo_id')
            num = r.get('shirt_number')
            if eid and num is not None:
                mapa_rosters[(eid, num)] = r.get('player_id')
        print(f"   -> {len(rosters)} registros de roster cargados.")
    except Exception as e:
        print(f"❌ Error rosters: {e}")
        return {}, {}, [], {}, {}, set(), {}

    return mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup, mapa_rosters

def buscar_jugador(team_id, shirt_num, mapa_rosters):
    if not team_id or shirt_num is None: return None
    return mapa_rosters.get((team_id, safe_int(shirt_num)))

# --- MAIN ---
def procesar_tiros():
    print("🏀 INICIANDO INGESTA DE TIROS + ZONAS")

    try:
        supabase = create_client(URL, KEY)
    except Exception as e:
        print(f"❌ Error conexion: {e}")
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

        print(f"⚡ Procesando Tiros: Partido {match_id_str}")

        try:
            data = requests.get(json_url, timeout=10).json()
        except: continue

        tms = data.get('tm', {})
        if not tms or len(tms) < 2: continue

        payloads = []

        for k_tm, t_data in tms.items():
            nombre_j = t_data.get('name', '')
            codigo_j = t_data.get('code', '')
            if not nombre_j and not codigo_j: continue
            equipo_id, _ = team_utils.buscar_id_equipo(
                nombre_j, codigo_j, m_eq_n, m_eq_c, equipos_raw,
                competicion_id=comp_id, mapa_nombre_comp=m_eq_n_comp,
                mapa_codigo_comp=m_eq_c_comp,
                codigos_duplicados_comp=codigos_dup
            )

            if not equipo_id:
                team_utils.log_equipo_no_encontrado(nombre_j, codigo_j, match_id_str, "LDM_Tiros")
                continue

            shots = t_data.get('shot', [])
            for s in shots:
                x = safe_float(s.get('x'))
                y = safe_float(s.get('y'))
                tno = s.get('tno')
                act_type = s.get('actionType')

                shirt_num = s.get('shirtNumber')
                player_id = buscar_jugador(equipo_id, shirt_num, m_rosters)

                zona = classify_shot(x, y)

                tiro_row = {
                    "partido_id": int(match_id_str),
                    "equipo_id": equipo_id,
                    "player_id": player_id,
                    "r": safe_float(s.get('r')),
                    "x": x,
                    "y": y,
                    "tiro_zona": zona,
                    "p": safe_int(s.get('p')),
                    "pno": safe_int(s.get('pno')),
                    "tno": safe_int(tno),
                    "per": safe_int(s.get('per')),
                    "pertype": str(s.get('perType', '')),
                    "actiontype": str(act_type),
                    "actionnumber": safe_int(s.get('actionNumber')),
                    "previousaction": safe_int(s.get('previousAction')),
                    "subtype": str(s.get('subType', '')),
                    "player": str(s.get('player', '')),
                    "shirtnumber": safe_int(shirt_num)
                }
                payloads.append(tiro_row)

        if payloads:
            try:
                chunk_size = 500
                for i in range(0, len(payloads), chunk_size):
                    batch = payloads[i:i+chunk_size]
                    supabase.table("tiros").upsert(batch, on_conflict="partido_id,actionnumber").execute()
                print(f"   ✅ {len(payloads)} tiros guardados.")
            except Exception as e:
                print(f"   ❌ Error insertando: {e}")

    print("🏁 Fin de Ingesta Tiros.")

if __name__ == "__main__":
    procesar_tiros()
