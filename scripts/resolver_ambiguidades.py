import csv
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
import tempfile
from collections import Counter
from pathlib import Path

# Constantes de configuração e rede
USER_AGENT = "mpb-corpus/0.2 (https://github.com/ProjetoMPB/mpb-corpus)"
MUSICBRAINZ_PAUSE = 2.0
COMPOSITIONS_CSV = Path("metadata/compositions.csv")

def request_mb(url):
    """Faz requisições ao MusicBrainz com backoff exponencial nativo para erros 503."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {}
            if error.code in {503, 502, 500, 429}:
                wait = min(300, 10 * 2 ** attempt)
                print(f"    HTTP {error.code} recebido; aguardando {wait}s...")
                time.sleep(wait)
                continue
            raise
    return {}

def extract_earliest_date(recording):
    """Extrai todas as datas vinculadas a uma gravação e retorna a mais antiga."""
    dates = []
    # Data de busca textual
    if recording.get("first-release-date"):
        dates.append(recording["first-release-date"])
    # Data de busca via ISRC (dentro da tag releases)
    for release in recording.get("releases", []):
        if release.get("date"):
            dates.append(release["date"])
            
    # Filtra formatos inválidos e ordena cronologicamente (YYYY-MM-DD)
    valid_dates = [d for d in dates if len(d) >= 4]
    return min(valid_dates) if valid_dates else "9999-99-99"

def get_oldest_by_isrc(isrc):
    """Aciona a API via ISRC exigindo a inclusão das datas de lançamento."""
    url = f"https://musicbrainz.org/ws/2/isrc/{urllib.parse.quote(isrc)}?fmt=json&inc=releases"
    data = request_mb(url)
    recordings = data.get("recordings", [])
    if not recordings:
        return None
    
    # Ordena as gravações pela data mais antiga e retorna o ID da primeira
    recordings.sort(key=extract_earliest_date)
    return recordings[0].get("id")

def get_by_text(title, artist):
    """Aciona a busca textual no MusicBrainz e define o ID pela gravação mais antiga."""
    clean_title = title.replace('"', '').replace(':', '')
    clean_artist = artist.replace('"', '').replace(':', '')
    query = f'recording:"{clean_title}" AND artist:"{clean_artist}"'
    params = urllib.parse.urlencode({"fmt": "json", "query": query})
    
    url = f"https://musicbrainz.org/ws/2/recording/?{params}"
    data = request_mb(url)
    recordings = data.get("recordings", [])
    
    if len(recordings) == 0:
        return None, "not_found"
    elif len(recordings) == 1:
        # Se achou só uma, retorna o ID dela e classifica como match exato
        return recordings[0].get("id"), "text_exact_match"
    else:
        # Se achou várias, ordena pela data, retorna o ID da mais antiga
        recordings.sort(key=extract_earliest_date)
        return recordings[0].get("id"), "text_oldest_match"

def save_csv(fields, rows):
    """Escrita atômica segura para evitar corrupção de arquivo no Windows."""
    temp_name = ""
    # A correção está aqui: adicionamos dir=COMPOSITIONS_CSV.parent
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=COMPOSITIONS_CSV.parent, delete=False) as temp:
        writer = csv.DictWriter(temp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        temp_name = temp.name
    os.replace(temp_name, COMPOSITIONS_CSV)

def main():
    print("Iniciando varredura heurística de datas e criação de matriz de rastreabilidade...")
    
    with COMPOSITIONS_CSV.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)
        
    if "musicbrainz_match_criteria" not in fields:
        fields.append("musicbrainz_match_criteria")

    for number, row in enumerate(rows, 1):
        isrc = row.get("isrc", "")
        mb_status = row.get("musicbrainz_match_status", "")
        current_id = row.get("musicbrainz_recording_id", "")
        criteria = row.get("musicbrainz_match_criteria", "")
        
        # Pula processamento de rede se já foi resolvido com sucesso pelo script
        if criteria in ("isrc_exact_match", "isrc_oldest_match", "text_exact_match", "text_oldest_match", "not_found"):
            continue

        # 1. RESOLUÇÃO $O(1)$ LOCAL: Aproveita os IDs que já deram match perfeito antes!
        if mb_status == "one_recording" and current_id:
            row["musicbrainz_match_criteria"] = "isrc_exact_match"
            continue
            
        if mb_status == "text_fallback_one" and current_id:
            row["musicbrainz_match_criteria"] = "text_exact_match"
            continue
            
        # 2. REDE: ISRC Múltiplo (Desempata por data)
        if mb_status == "several_recordings":
            print(f"[{number}/{len(rows)}] Desempatando ISRC múltiplo por data: {row['composition_name']}")
            oldest_id = get_oldest_by_isrc(isrc)
            if oldest_id:
                row["musicbrainz_recording_id"] = oldest_id  # Salva o ID!
                row["musicbrainz_match_criteria"] = "isrc_oldest_match"
            time.sleep(MUSICBRAINZ_PAUSE)
            continue
            
        # 3. REDE: Busca por Texto e Data
        print(f"[{number}/{len(rows)}] Desempatando texto por data: {row['composition_name']}")
        title = row.get("spotify_track_title") or row.get("composition_name")
        artist = row.get("spotify_track_artist") or ""
        
        new_id, new_criteria = get_by_text(title, artist)
        row["musicbrainz_recording_id"] = new_id if new_id else ""  # Salva o ID!
        row["musicbrainz_match_criteria"] = new_criteria
        
        time.sleep(MUSICBRAINZ_PAUSE)
        
        # Checkpoint de salvamento a cada 25 consultas
        if number % 25 == 0:
            save_csv(fields, rows)

    # Salvamento final ao sair do laço
    save_csv(fields, rows)

    print("\nProcesso concluído com sucesso. Resumo da matriz de rastreabilidade gerada:")
    counts = Counter(r.get("musicbrainz_match_criteria") for r in rows)
    for crit, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {crit}: {count}")

if __name__ == "__main__":
    main()