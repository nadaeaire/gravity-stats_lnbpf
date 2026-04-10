import os
import requests
import time
from bs4 import BeautifulSoup
from supabase import create_client, Client
import team_utils

# --- CONFIGURACION ---
COMPETICIONES_VALIDAS = {42033, 42034}

URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")

GENIUS_TEAMS_URL = "https://hosted.dcd.shared.geniussports.com/embednf/ABE/es/competition/{comp_id}/teams"
GENIUS_ROSTER_URL = "https://hosted.dcd.shared.geniussports.com/embednf/ABE/es/competition/{comp_id}/team/{team_id}/roster"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

EFFECTIVE_START_DATE = "2026-01-24"

# --- UTILIDADES ---

def clean_name(name):
    if not name: return ""
    return str(name).strip().title()

def split_full_name(full_name):
    """Primer token = first_name, resto = family_name.
    Misma logica que LDM_Players.py lineas 83-85."""
    parts = full_name.strip().split()
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])

def safe_int_or_none(val):
    """Convierte a int, retorna None si vacio/invalido."""
    if not val or str(val).strip() == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None

# --- SCRAPING ---

def scrape_teams(comp_id):
    """Obtiene lista de equipos desde Genius Sports."""
    url = GENIUS_TEAMS_URL.format(comp_id=comp_id)
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    html = resp.json().get("html", "")
    soup = BeautifulSoup(html, 'html.parser')

    teams = []
    for div in soup.find_all('div', class_='team-link'):
        a_tags = div.find_all('a')
        if len(a_tags) >= 2:
            link = a_tags[1]
            name = link.text.strip()
            href = link.get('href', '')
            if '/team/' in href:
                tid = href.split('/team/')[1].split('?')[0]
                teams.append({"id": tid, "nombre": name})
    return teams

def scrape_roster(comp_id, team_id):
    """Obtiene roster HTML de un equipo y parsea cada jugador."""
    url = GENIUS_ROSTER_URL.format(comp_id=comp_id, team_id=team_id)
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    html = resp.json().get("html", "")
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='roster-table')
    if not table:
        return []

    players = []
    rows = table.find('tbody').find_all('tr')
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 8:
            continue

        link = cols[1].find('a')
        full_name = link.text.strip() if link else cols[1].text.strip()

        td_dob = cols[6]
        dob = td_dob.get('data-value', '').strip()

        players.append({
            "shirt_number": safe_int_or_none(cols[0].text.strip()),
            "full_name": full_name,
            "position": cols[2].text.strip() or None,
            "height_cm": safe_int_or_none(cols[3].text.strip()),
            "weight_kg": safe_int_or_none(cols[4].text.strip()),
            "date_of_birth": dob if dob else None,
            "nationality": cols[7].text.strip() or None,
        })
    return players

# --- LOGICA DE JUGADORES ---

def process_player(supabase, player_data, equipo_id, comp_id):
    """Busca o crea un jugador con datos bio completos y gestiona su roster."""
    first_name, family_name = split_full_name(player_data["full_name"])
    first_name = clean_name(first_name)
    family_name = clean_name(family_name)
    shirt_num = player_data["shirt_number"] or 0

    player_id = None
    needs_bio_update = False

    # 1. Buscar en roster por equipo + camiseta + competicion
    try:
        res = supabase.table("rosters")\
            .select("player_id")\
            .eq("equipo_id", equipo_id)\
            .eq("shirt_number", shirt_num)\
            .eq("competicion_id", comp_id)\
            .execute()
        data = res.data if hasattr(res, 'data') else res
        if data and len(data) > 0:
            player_id = data[0]['player_id']
            needs_bio_update = True
    except Exception as e:
        print(f"   ⚠️ Error buscando roster: {e}")

    # 2. Fallback: buscar en players por nombre
    if not player_id:
        try:
            res = supabase.table("players")\
                .select("player_id, height_cm, weight_kg, date_of_birth, nationality")\
                .ilike("first_name", first_name)\
                .ilike("family_name", family_name)\
                .execute()
            data = res.data if hasattr(res, 'data') else res
            if data and len(data) > 0:
                player_id = data[0]['player_id']
                existing = data[0]
                if any(existing.get(f) is None for f in ['height_cm', 'weight_kg', 'date_of_birth', 'nationality']):
                    needs_bio_update = True
        except Exception as e:
            print(f"   ⚠️ Error buscando player: {e}")

    # 3. Crear jugador nuevo CON datos bio
    if not player_id:
        new_player = {
            "first_name": first_name,
            "family_name": family_name,
            "height_cm": player_data["height_cm"],
            "weight_kg": player_data["weight_kg"],
            "date_of_birth": player_data["date_of_birth"],
            "nationality": player_data["nationality"],
        }
        try:
            res = supabase.table("players").insert(new_player).execute()
            data = res.data if hasattr(res, 'data') else res
            if data:
                player_id = data[0]['player_id']
                print(f"   ✨ Nuevo: {first_name} {family_name} (#{shirt_num})")
            else:
                return None
        except Exception as e:
            print(f"   ❌ Error creando player: {e}")
            return None

    # 4. Actualizar bio en jugador existente (solo campos NULL)
    if needs_bio_update and player_id:
        update_fields = {}
        for scrape_key in ["height_cm", "weight_kg", "date_of_birth", "nationality"]:
            val = player_data.get(scrape_key)
            if val is not None:
                update_fields[scrape_key] = val

        if update_fields:
            try:
                supabase.table("players")\
                    .update(update_fields)\
                    .eq("player_id", player_id)\
                    .execute()
            except Exception as e:
                print(f"   ⚠️ Error actualizando bio: {e}")

    # 5. Upsert roster con posicion
    try:
        roster_row = {
            "player_id": player_id,
            "equipo_id": equipo_id,
            "competicion_id": comp_id,
            "shirt_number": shirt_num,
            "playing_position": player_data["position"],
            "effective_start_date": EFFECTIVE_START_DATE,
        }
        supabase.table("rosters").upsert(
            roster_row,
            on_conflict="player_id,competicion_id,effective_start_date"
        ).execute()
    except Exception as e:
        print(f"   ⚠️ Error en roster upsert: {e}")

    return player_id

# --- MAIN ---

def procesar_rosters():
    """Punto de entrada: scrapea y sincroniza todos los rosters."""
    print("📋 INICIANDO INGESTA DE ROSTERS (Scraper Genius Sports)")

    supabase = create_client(URL, KEY)

    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = \
        team_utils.cargar_mapa_equipos(supabase)

    total_players = 0

    for comp_id in COMPETICIONES_VALIDAS:
        print(f"\n🏆 Competición {comp_id}")

        try:
            teams = scrape_teams(comp_id)
            print(f"   {len(teams)} equipos encontrados")
        except Exception as e:
            print(f"   ❌ Error obteniendo equipos: {e}")
            continue

        for team in teams:
            genius_team_name = team["nombre"]
            genius_team_id = team["id"]

            equipo_id, method = team_utils.buscar_id_equipo(
                genius_team_name, "",
                mapa_n, mapa_c, equipos_raw,
                competicion_id=comp_id,
                mapa_nombre_comp=mapa_n_comp,
                mapa_codigo_comp=mapa_c_comp,
                codigos_duplicados_comp=codigos_dup
            )

            if not equipo_id:
                team_utils.log_equipo_no_encontrado(
                    genius_team_name, "", f"roster-{comp_id}", "LDM_Rosters"
                )
                continue

            print(f"   📂 {genius_team_name} (equipo_id={equipo_id}, via {method})")

            try:
                roster = scrape_roster(comp_id, genius_team_id)
            except Exception as e:
                print(f"      ❌ Error scraping roster: {e}")
                continue

            for p in roster:
                pid = process_player(supabase, p, equipo_id, comp_id)
                if pid:
                    total_players += 1

            time.sleep(1)

    print(f"\n📋 Rosters sincronizados: {total_players} jugadores procesados")
    print("🏁 Fin de LDM_Rosters.")

if __name__ == "__main__":
    procesar_rosters()
