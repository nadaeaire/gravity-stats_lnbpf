import os
import sys
import time
from datetime import datetime
from supabase import create_client, Client

# --- IMPORTAR MODULOS ---
try:
    import LDM_Partidos
    import LDM_Rosters
    import LDM_Players
    import LDM_PlayByPlay
    import LDM_Tiros
    import team_utils
except ImportError as e:
    print(f"❌ Error CRITICO: No se pudo importar un modulo. Verifica los nombres de archivo.\nDetalle: {e}")
    sys.exit(1)

def log_step(step_name):
    print(f"\n{'='*60}")
    print(f"🚀 EJECUTANDO PASO: {step_name}")
    print(f"⏰ Hora: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

def validar_integridad():
    """Consulta Supabase y valida que los datos ingresados sean consistentes.

    Checks:
    1. Cada partido en partidos_detalle tiene exactamente 2 equipos.
    2. Todos los equipos tienen un número similar de partidos (alerta si hay asimetría).
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("   ⚠️ Sin credenciales de Supabase, saltando validación.")
        return

    supabase = create_client(url, key)

    # 1. Verificar que cada partido tiene exactamente 2 registros en partidos_detalle
    print("   🔍 Verificando registros por partido...")
    try:
        res = supabase.table("partidos_detalle").select("partido_id, equipo_id").execute()
        rows = res.data if hasattr(res, 'data') else res

        from collections import Counter
        conteo_partido = Counter(r['partido_id'] for r in rows)

        partidos_mal = {pid: cnt for pid, cnt in conteo_partido.items() if cnt != 2}
        if partidos_mal:
            print(f"   ⚠️ {len(partidos_mal)} partido(s) NO tienen exactamente 2 registros:")
            for pid, cnt in sorted(partidos_mal.items())[:10]:
                print(f"      partido_id={pid} → {cnt} registro(s)")
            if len(partidos_mal) > 10:
                print(f"      ... y {len(partidos_mal) - 10} más.")
        else:
            print(f"   ✅ Todos los {len(conteo_partido)} partidos tienen exactamente 2 registros.")
    except Exception as e:
        print(f"   ⚠️ Error verificando partidos_detalle: {e}")

    # 2. Verificar simetría de partidos por equipo (por competición)
    print("   🔍 Verificando partidos por equipo...")
    try:
        res_p = supabase.table("partidos").select("partido_id, competicion_id").execute()
        partidos_data = res_p.data if hasattr(res_p, 'data') else res_p
        comp_map = {p['partido_id']: p['competicion_id'] for p in partidos_data}

        # Contar partidos por equipo por competición
        from collections import defaultdict
        equipo_partidos = defaultdict(lambda: defaultdict(int))
        for r in rows:
            pid = r['partido_id']
            eid = r['equipo_id']
            comp = comp_map.get(pid, '?')
            equipo_partidos[comp][eid] += 1

        for comp_id, equipos in sorted(equipo_partidos.items()):
            conteos = list(equipos.values())
            if not conteos:
                continue
            max_g = max(conteos)
            min_g = min(conteos)
            print(f"   Competición {comp_id}: {len(equipos)} equipos, "
                  f"rango partidos: {min_g}-{max_g}")
            if max_g - min_g > 3:
                print(f"   ⚠️ ASIMETRÍA DETECTADA (diferencia > 3 partidos):")
                for eid, cnt in sorted(equipos.items(), key=lambda x: x[1]):
                    if cnt < max_g - 2:
                        print(f"      equipo_id={eid} → {cnt} partidos (posible problema)")
    except Exception as e:
        print(f"   ⚠️ Error verificando simetría: {e}")


def main_orchestrator():
    print(f"🏀 INICIANDO ROBOT DE INGESTA LIGA ABE")
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d')}")
    start_total = time.time()

    # --- PASO 1: OMITIDO ---
    # Los partidos ya están pre-cargados en la tabla 'partidos' via LDM_BulkLoad.py.
    # Ya no es necesario descubrir partidos desde la API de Genius Sports.
    print(f"\n{'='*60}")
    print(f"ℹ️  Paso 1 (Match ID) OMITIDO: partidos pre-cargados desde CSV.")
    print(f"{'='*60}")

    # --- PASO 2: INGESTA DE PARTIDOS (Cabeceras y Marcadores) ---
    log_step("2. PARTIDOS (Tabla General)")
    try:
        LDM_Partidos.procesar_partidos()
    except Exception as e:
        print(f"❌ Fallo el Paso 2 (Partidos). Se intentara continuar, pero revisa los logs.")
        print(f"Error: {e}")

    # --- PASO 2.5: ROSTERS (Scraper Genius Sports) ---
    log_step("2.5 ROSTERS (Scraper Bio Jugadores)")
    try:
        LDM_Rosters.procesar_rosters()
    except Exception as e:
        print(f"⚠️ Fallo el Paso 2.5 (Rosters). Se continuará sin datos bio actualizados.")
        print(f"Error: {e}")

    # --- PASO 3: JUGADORES (Censo y Rosters) ---
    log_step("3. JUGADORES (Rosters y Players)")
    players_success = False
    try:
        LDM_Players.procesar_jugadores()
        players_success = True
    except Exception as e:
        print(f"❌ ERROR CRITICO en Paso 3 (Jugadores).")
        print(f"Error: {e}")
        print("⛔ DETENIENDO EJECUCION: No se pueden procesar acciones ni tiros sin jugadores identificados.")
        sys.exit(1)

    if not players_success:
        print("⛔ DETENIENDO: El proceso de jugadores no finalizo correctamente.")
        sys.exit(1)

    # --- PASO 4: PLAY BY PLAY (Acciones) ---
    log_step("4. PLAY BY PLAY (Acciones)")
    try:
        LDM_PlayByPlay.procesar_pbp()
    except Exception as e:
        print(f"❌ Fallo el Paso 4 (PBP).")
        print(f"Error: {e}")

    # --- PASO 5: TIROS (Shotchart) ---
    log_step("5. TIROS (Coordenadas y Zonas)")
    try:
        LDM_Tiros.procesar_tiros()
    except Exception as e:
        print(f"❌ Fallo el Paso 5 (Tiros).")
        print(f"Error: {e}")

    # --- PASO 6: REFRESCAR VISTAS MATERIALIZADAS ---
    log_step("6. REFRESH VISTAS MATERIALIZADAS")
    try:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if url and key:
            sb = create_client(url, key)
            sb.rpc("refresh_vistas_mat").execute()
            print("   ✅ Vistas materializadas refrescadas correctamente.")
        else:
            print("   ⚠️ Sin credenciales de Supabase, saltando refresh de vistas.")
    except Exception as e:
        print(f"   ⚠️ Error refrescando vistas materializadas (no crítico): {e}")

    # --- PASO 7: VALIDACIÓN POST-INGESTA ---
    log_step("7. VALIDACIÓN (Integridad de Datos)")
    try:
        validar_integridad()
    except Exception as e:
        print(f"⚠️ Error en validación (no crítico): {e}")

    # --- RESUMEN FINAL ---
    end_total = time.time()
    duration = round(end_total - start_total, 2)

    # Resumen de equipos no encontrados (acumulados de todos los pasos)
    no_encontrados = team_utils.get_equipos_no_encontrados()
    if no_encontrados:
        print(f"\n{'='*60}")
        print(f"⚠️ EQUIPOS NO ENCONTRADOS EN CATÁLOGO ({len(no_encontrados)}):")
        for nombre, codigo in sorted(no_encontrados):
            print(f"   - Nombre: '{nombre}' | Código: '{codigo}'")
        print(f"   → Agrégalos a la tabla 'equipos' en Supabase y re-ejecuta.")
        print(f"{'='*60}")

    print(f"\n{'='*60}")
    print(f"✅ CICLO COMPLETADO")
    print(f"⏱️ Tiempo Total: {duration} segundos")
    print(f"{'='*60}")

if __name__ == "__main__":
    main_orchestrator()
