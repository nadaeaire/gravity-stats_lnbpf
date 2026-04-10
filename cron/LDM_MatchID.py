import requests
import json
import gspread
import time
from datetime import datetime

# --- CONFIGURACION ---
SPREADSHEET_NAME = "2025_ABE_01_MatchID-TEST"
WORKSHEET_NAME = "MatchId"
CREDENTIALS_FILE = "credentials.json"
COMPETICIONES = ["42033", "42034"]

# Plantillas
URL_TEMPLATE_DATA = "https://fibalivestats.dcd.shared.geniussports.com/data/{}/data.json"
URL_TEMPLATE_BOXSCORE = "https://fibalivestats.dcd.shared.geniussports.com/u/ABE/{}/bs.html"

def fetch_json(url):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except:
        return None

def main():
    print("🚀 MATCH ID (MODO SIMPLE - SIN DRIVE)")

    # 1. Conexion a Google Sheets
    try:
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.worksheet(WORKSHEET_NAME)
    except Exception as e:
        print(f"❌ Error conectando a Sheets: {e}")
        return

    # 2. Leer IDs existentes
    try:
        existing_ids_raw = ws.col_values(3) # Columna C es MatchID
        existing_ids = {str(v).strip() for v in existing_ids_raw if v}
    except:
        existing_ids = set()

    new_rows = []
    # Si la hoja esta vacia, encabezados
    if not existing_ids:
        new_rows.append(["timestamp", "competitionId", "matchId", "matchTimeUTC", "game_boxscore", "game_url"])

    # 3. Procesar
    for comp_id in COMPETICIONES:
        url = f"https://fibalivestats.dcd.shared.geniussports.com/data/competition/{comp_id}.json"
        matches = fetch_json(url)
        if not matches: continue

        print(f"📋 Revisando competencia {comp_id}...")
        for match in matches:
            mid = str(match.get("matchId")).strip()

            # Si es nuevo...
            if mid and mid not in existing_ids:
                print(f"⚡ Nuevo Partido detectado: {mid}")

                match_time = match.get("matchTimeUTC")
                game_url = URL_TEMPLATE_DATA.format(mid)

                new_rows.append([
                    datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    str(match.get("competitionId")),
                    mid,
                    match_time,
                    URL_TEMPLATE_BOXSCORE.format(mid),
                    game_url
                ])
                existing_ids.add(mid)
                time.sleep(0.5)

    # 4. Guardar
    if new_rows:
        ws.append_rows(new_rows, value_input_option='USER_ENTERED')
        print(f"✅ {len(new_rows)} partidos registrados en Sheets.")
    else:
        print("💤 Todo actualizado.")

if __name__ == "__main__":
    main()
