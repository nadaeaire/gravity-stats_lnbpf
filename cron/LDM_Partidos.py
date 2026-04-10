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

# --- FUNCIONES DE UTILIDAD ---

def safe_get(d, k, default=0):
    """Obtiene valores del diccionario de forma segura."""
    val = d.get(k, default)
    return val if val is not None else default

def time_to_seconds(time_val):
    """Convierte 'MM:SS' a segundos (int)."""
    if not time_val: return 0
    if isinstance(time_val, (int, float)): return time_val

    s_val = str(time_val).strip()
    try:
        if ':' in s_val:
            parts = s_val.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return float(s_val)
    except:
        return 0

def calcular_avanzadas(team_dict, rival_dict):
    """
    Calcula metricas avanzadas usando las nuevas llaves 'tot_s...' del JSON.
    """
    # Extraccion usando las llaves REALES que vimos en el diagnostico
    fga = safe_get(team_dict, 'tot_sFieldGoalsAttempted')
    fgm = safe_get(team_dict, 'tot_sFieldGoalsMade')
    fgm3 = safe_get(team_dict, 'tot_sThreePointersMade')
    fta = safe_get(team_dict, 'tot_sFreeThrowsAttempted')
    ftm = safe_get(team_dict, 'tot_sFreeThrowsMade')
    rebo = safe_get(team_dict, 'tot_sReboundsOffensive')
    rebd = safe_get(team_dict, 'tot_sReboundsDefensive')
    tov = safe_get(team_dict, 'tot_sTurnovers')
    ast = safe_get(team_dict, 'tot_sAssists')
    stl = safe_get(team_dict, 'tot_sSteals')
    blk = safe_get(team_dict, 'tot_sBlocks')

    score = safe_get(team_dict, 'score')

    # Datos rivales
    r_rebd = safe_get(rival_dict, 'tot_sReboundsDefensive')
    r_rebo = safe_get(rival_dict, 'tot_sReboundsOffensive')
    r_score = safe_get(rival_dict, 'score')

    # --- FORMULAS ---
    # 1. Posesiones
    denom_rebs = rebo + r_rebd
    orb_factor = (rebo / denom_rebs) if denom_rebs > 0 else 0

    posesiones = fga - (orb_factor * (fga - fgm) * 1.07) + tov + (0.4 * fta)
    posesiones = round(posesiones, 1)

    pos_calc = posesiones if posesiones > 0 else 1

    # 2. Ratings
    ortg = round((score / pos_calc) * 100, 1)
    drtg = round((r_score / pos_calc) * 100, 1)
    nrtg = round(ortg - drtg, 1)

    # 3. Four Factors
    tsa = fga + (0.44 * fta)
    tsp = round(score / (2 * tsa), 3) if tsa > 0 else 0

    ff_efg = round((fgm + 0.5 * fgm3) / fga, 3) if fga > 0 else 0

    denom_tov = fga + (0.44 * fta) + tov
    ff_tov = round(tov / denom_tov, 3) if denom_tov > 0 else 0

    ff_oreb = round(rebo / (rebo + r_rebd), 3) if (rebo + r_rebd) > 0 else 0
    ff_dreb = round(rebd / (rebd + r_rebo), 3) if (rebd + r_rebo) > 0 else 0
    ff_ftr = round(ftm / fga, 3) if fga > 0 else 0

    ast_tov = round(ast / tov, 1) if tov > 0 else 0

    # Métricas adicionales
    astp1 = round(ast / fgm, 3) if fgm > 0 else 0
    astp2 = round(ast / pos_calc, 3)
    stlp = round(stl / pos_calc, 3)
    blkp = round(blk / pos_calc, 3)

    return {
        "posesiones": posesiones,
        "ortg": ortg, "drtg": drtg, "nrtg": nrtg,
        "tsa": tsa, "tsp": tsp,
        "ff_efg": ff_efg, "ff_tov": ff_tov, "ff_oreb": ff_oreb, "ff_dreb": ff_dreb, "ff_ftr": ff_ftr,
        "ast_tov": ast_tov,
        "astp1": astp1, "astp2": astp2, "stlp": stlp, "blkp": blkp
    }

def map_basic_stats(team_dict):
    """
    Mapea las llaves 'tot_sKey' del JSON a tus columnas 'tot_skey' de la DB.
    """
    # Mapeo: JSON Key -> DB Column
    mapping = {
        'tot_sMinutes': 'tot_sminutes',

        'tot_sFieldGoalsMade': 'tot_sfieldgoalsmade',
        'tot_sFieldGoalsAttempted': 'tot_sfieldgoalsattempted',
        'tot_sThreePointersMade': 'tot_sthreepointersmade',
        'tot_sThreePointersAttempted': 'tot_sthreepointersattempted',
        'tot_sTwoPointersMade': 'tot_stwopointersmade',
        'tot_sTwoPointersAttempted': 'tot_stwopointersattempted',
        'tot_sFreeThrowsMade': 'tot_sfreethrowsmade',
        'tot_sFreeThrowsAttempted': 'tot_sfreethrowsattempted',

        'tot_sReboundsDefensive': 'tot_sreboundsdefensive',
        'tot_sReboundsOffensive': 'tot_sreboundsoffensive',
        'tot_sReboundsTotal': 'tot_sreboundstotal',

        'tot_sAssists': 'tot_sassists',
        'tot_sTurnovers': 'tot_sturnovers',
        'tot_sSteals': 'tot_ssteals',
        'tot_sBlocks': 'tot_sblocks',
        'tot_sBlocksReceived': 'tot_sblocksreceived',
        'tot_sFoulsPersonal': 'tot_sfoulspersonal',
        'tot_sFoulsOn': 'tot_sfoulson',

        'tot_sPointsInThePaint': 'tot_spointsinthepaint',
        'tot_sPointsFromTurnovers': 'tot_spointsfromturnovers',
        'tot_sPointsSecondChance': 'tot_spointssecondchance',
        'tot_sPointsFastBreak': 'tot_spointsfastbreak',
        'tot_sBenchPoints': 'tot_sbenchpoints',

        'tot_sBiggestScoringRun': 'tot_sbiggestscoringrun',
        'tot_sLeadChanges': 'tot_sleadchanges',
        'tot_sTimesScoresLevel': 'tot_stimesscoreslevel',
        'tot_sTimeLeading': 'tot_stimeleading',
    }

    result = {}
    for json_k, db_col in mapping.items():
        val = safe_get(team_dict, json_k, 0)

        # Conversiones de tipos
        if db_col == 'tot_sminutes':
            result[db_col] = str(val) if val else "00:00"
        elif db_col == 'tot_stimeleading':
            result[db_col] = time_to_seconds(val)
        else:
            result[db_col] = val

    return result

# --- CARGA DE EQUIPOS (delegada a team_utils) ---

def asegurar_temporada(supabase, temp_id):
    """Crea la temporada si no existe en la tabla temporadas."""
    try:
        res = supabase.table("temporadas").select("temporada_id").eq("temporada_id", temp_id).execute()
        data = res.data if hasattr(res, 'data') else res
        if data and len(data) > 0:
            return True
        supabase.table("temporadas").insert({"temporada_id": temp_id}).execute()
        print(f"   ✅ Temporada {temp_id} creada automaticamente.")
        return True
    except Exception as e:
        print(f"   ⚠️ No se pudo asegurar temporada {temp_id}: {e}")
        print(f"   👉 Crea manualmente una fila en 'temporadas' con temporada_id={temp_id}")
        return False

# --- PROCESO PRINCIPAL ---

def procesar_partidos():
    print("🏀 INICIANDO INGESTA DE PARTIDOS (JSON V2)")

    try:
        supabase: Client = create_client(URL, KEY)
    except Exception as e:
        print(f"❌ Error de conexion: {e}")
        return

    asegurar_temporada(supabase, 1)
    team_utils.reset_log()
    mapa_nombres, mapa_codigos, equipos_raw, mapa_nombres_comp, mapa_codigos_comp, codigos_dup = team_utils.cargar_mapa_equipos(supabase)
    if not mapa_nombres:
        print("⚠️ Error: Catalogo de equipos vacio.")
        return

    records = team_utils.cargar_partidos_desde_db(supabase)
    print(f"📋 Revisando {len(records)} partidos...")

    procesados = set()

    for row in records:
        match_id_str = str(row.get('matchId', '')).strip()
        json_url = row.get('game_url', '')
        fecha_str = row.get('matchTimeUTC', '')

        if not match_id_str or not json_url: continue
        if match_id_str in procesados: continue
        procesados.add(match_id_str)

        # --- FILTRO COMPETICION ---
        comp_id = int(row.get('competitionId', 0))
        if comp_id not in COMPETICIONES_VALIDAS: continue

        # --- PARSEO FECHA ---
        fecha_dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z",
                     "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y %H:%M:%S"):
            try:
                fecha_dt = datetime.strptime(fecha_str.strip(), fmt)
                break
            except:
                continue
        if not fecha_dt:
            print(f"   ⚠️ Formato de fecha no reconocido: '{fecha_str}' (Partido {match_id_str})")
            continue

        print(f"⚡ Procesando ID: {match_id_str}")

        try:
            data = requests.get(json_url, timeout=10).json()
        except Exception as e:
            print(f"   ❌ Error descarga JSON: {e}")
            continue

        tms = data.get('tm', {})
        if not tms or len(tms) < 2:
            print(f"   ⚠️ PARTIDO {match_id_str} SALTADO: JSON no contiene 2 equipos (tm={len(tms) if tms else 0})")
            continue

        team_ids_db = {}
        team_objs = {}

        # 1. Identificar Equipos (con normalización + fuzzy)
        for k, t_data in tms.items():
            nombre_j = t_data.get('name', '')
            codigo_j = t_data.get('code', '')
            if not nombre_j and not codigo_j:
                print(f"   ⚠️ Equipo {k} con nombre y código vacíos en partido {match_id_str} (dato corrupto en API)")
                continue
            db_id, metodo = team_utils.buscar_id_equipo(
                nombre_j, codigo_j, mapa_nombres, mapa_codigos, equipos_raw,
                competicion_id=comp_id, mapa_nombre_comp=mapa_nombres_comp,
                mapa_codigo_comp=mapa_codigos_comp,
                codigos_duplicados_comp=codigos_dup
            )
            if db_id:
                team_ids_db[k] = db_id
                team_objs[k] = t_data
            else:
                team_utils.log_equipo_no_encontrado(nombre_j, codigo_j, match_id_str, "LDM_Partidos")

        if len(team_ids_db) < 2:
            faltantes = [t.get('name', '?') for k, t in tms.items() if k not in team_ids_db]
            print(f"   ❌ PARTIDO {match_id_str} NO INGRESADO: falta(n) equipo(s) {faltantes}")
            print(f"      → Agrega estos equipos al catálogo 'equipos' en Supabase y re-ejecuta.")
            continue

        # Detectar si ambos equipos resuelven al mismo ID (dato corrupto en API)
        ids_unicos = set(team_ids_db.values())
        if len(ids_unicos) < 2:
            print(f"   ⚠️ PARTIDO {match_id_str} SALTADO: ambos equipos resuelven al mismo ID ({ids_unicos})")
            continue

        # 2. Guardar PARTIDO
        try:
            partido_payload = {
                "partido_id": int(match_id_str),
                "competicion_id": int(row.get('competitionId', 0)),
                "temporada_id": 1,
                "equipo_local_id": team_ids_db.get('1'),
                "equipo_visitante_id": team_ids_db.get('2'),
                "match_time_utc": fecha_str,
                "timestamp_ingestion": datetime.now().isoformat(),
                "game_json_url": json_url,
                "game_boxscore_url": row.get('game_boxscore', '')
            }
            supabase.table("partidos").upsert(partido_payload).execute()
        except Exception as e:
            print(f"   ❌ Error en tabla 'partidos': {e}")
            continue

        # 3. Guardar DETALLES (Stats)
        try:
            t1 = team_objs['1'] # Equipo Local
            t2 = team_objs['2'] # Equipo Visita

            # Calcular Avanzadas
            m1 = calcular_avanzadas(t1, t2)
            m2 = calcular_avanzadas(t2, t1)

            ritmo = round((m1['posesiones'] + m2['posesiones']) / 2, 1)

            payloads = []

            for k, metrics, rival_obj in [('1', m1, t2), ('2', m2, t1)]:
                tm = team_objs[k]
                stats_base = map_basic_stats(tm)

                row_detalle = {
                    "partido_id": int(match_id_str),
                    "equipo_id": team_ids_db[k],
                    "dia": fecha_dt.strftime("%Y-%m-%d"),
                    "hora": fecha_dt.strftime("%H:%M:%S"),
                    "score": safe_get(tm, 'score'),
                    "full_score": safe_get(tm, 'full_score', safe_get(tm, 'score')),
                    "victoria": metrics['ortg'] > metrics['drtg'],
                    "puntos_rival": safe_get(rival_obj, 'score'),
                    "rebotes_d_rival": safe_get(rival_obj, 'tot_sReboundsDefensive'),
                    "coach_nombre": safe_get(tm, 'coach', ''),
                    "rol_partido": "L" if k == '1' else "V",
                    "etapa": "1",
                    "ritmo": ritmo,
                    **stats_base,
                    **metrics
                }
                payloads.append(row_detalle)

            supabase.table("partidos_detalle").upsert(payloads, on_conflict="partido_id,equipo_id").execute()
            print(f"   ✅ Stats guardadas (Local: {t1.get('score')} - Visita: {t2.get('score')})")

        except Exception as e:
            print(f"   ❌ Error en tabla 'partidos_detalle': {e}")

    # Resumen de equipos no encontrados
    no_encontrados = team_utils.get_equipos_no_encontrados()
    if no_encontrados:
        print(f"\n⚠️ RESUMEN: {len(no_encontrados)} equipo(s) no encontrado(s) en catálogo:")
        for nombre, codigo in no_encontrados:
            print(f"   - Nombre: '{nombre}' | Código: '{codigo}'")
        print("   → Agrégalos a la tabla 'equipos' en Supabase y re-ejecuta.")
    else:
        print("\n✅ Todos los equipos fueron encontrados en el catálogo.")

    print("🏁 Fin del proceso.")

if __name__ == "__main__":
    procesar_partidos()
