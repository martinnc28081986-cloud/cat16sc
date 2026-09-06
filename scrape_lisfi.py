#!/usr/bin/env python3
"""
Scraper LISFI — con verificación triple.

La zona NO está hardcodeada: se lee de Firebase, que es donde la app la escribe
cuando se cambia de temporada. Al cambiar de zona en la app, este script se
reapunta solo en la corrida siguiente.

Orden de resolución de la zona:
  1) Variables de entorno (override manual):  LISFI_ZONA_URL / LIGA_ID
  2) Firebase:  ligas/_activa/{CLUB_ID}  (nodo público, lo escribe la app)
                y como respaldo clubs/{CLUB_ID}/config/ligaId -> ligas/{ligaId}/meta/fuente
  3) Fallback hardcodeado de abajo

Calcula las posiciones desde los resultados (más robusto que scrapear la tabla)
y genera liga_data.json solo si la verificación pasa.
"""
import requests
from bs4 import BeautifulSoup
import json, re, sys, time, os
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
FIREBASE_DB = os.environ.get(
    "FIREBASE_DB",
    "https://presentes-20226-cat-16-sc-default-rtdb.firebaseio.com"
)
CLUB_ID     = os.environ.get("CLUB_ID", "sagrado-corazon")

# Se usan solo si Firebase no responde o no tiene la zona cargada
FALLBACK_LIGA_ID  = "lisfi-zona-campeonato-2026"
FALLBACK_ZONA_URL = "https://www.lisfi.com.ar/index.php/zona-camp-2026"

CATEGORIES = [13, 14, 15, 16, 17, 18, 19, 20]
SC_RE      = re.compile(r'sagr', re.IGNORECASE)
HEADERS    = {"User-Agent": "Mozilla/5.0 (compatible; ClubSC-Bot/1.0)"}

def is_sc(name): return bool(SC_RE.search(name))

def parse_score(s):
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None

def get_soup(url):
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return BeautifulSoup(r.content, "lxml")
        except Exception as e:
            if attempt == 3: raise
            print(f"   ⚠️  Conexión falló (intento {attempt}): {e} — reintentando en 5s...")
            time.sleep(5)

# ── RESOLVER QUÉ ZONA SCRAPEAR ────────────────────────────────────────────────
def _fb(path):
    """GET a Firebase REST. Devuelve None si no se puede leer (reglas, red, etc.)."""
    try:
        r = requests.get(f"{FIREBASE_DB}/{path}.json", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"   ⚠️  Firebase {path} -> HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        print(f"   ⚠️  Firebase {path} -> {e}")
        return None

def resolver_zona():
    """Devuelve (liga_id, zona_url, equipos_esperados)."""
    # 1) Override manual por variables de entorno
    env_url = os.environ.get("LISFI_ZONA_URL")
    env_id  = os.environ.get("LIGA_ID")
    if env_url:
        print(f"🔧 Zona por variable de entorno: {env_url}")
        return (env_id or FALLBACK_LIGA_ID), env_url.rstrip("/"), None

    # 2a) Puntero público: ligas/_activa/{club}. Es el único nodo que la app deja
    #     abierto para lectura sin login, justamente para esto.
    activa = _fb(f"ligas/_activa/{CLUB_ID}")
    if activa and activa.get("fuente"):
        liga_id = env_id or activa.get("ligaId") or FALLBACK_LIGA_ID
        print(f"🔗 Zona leída de Firebase (puntero público): {liga_id}")
        print(f"   fuente: {activa['fuente']}")
        equipos = None
        meta = _fb(f"ligas/{liga_id}/meta")
        if meta and meta.get("equipos"):
            equipos = meta["equipos"]
            print(f"   equipos esperados: {len(equipos)}")
        return liga_id, str(activa["fuente"]).rstrip("/"), equipos

    # 2b) Config del club (requiere que las reglas permitan leerla)
    liga_id = env_id or _fb(f"clubs/{CLUB_ID}/config/ligaId")
    if liga_id:
        meta = _fb(f"ligas/{liga_id}/meta") or {}
        fuente = meta.get("fuente")
        equipos = meta.get("equipos")
        if fuente:
            print(f"🔗 Zona leída de Firebase: {liga_id}")
            print(f"   fuente: {fuente}")
            if equipos: print(f"   equipos esperados: {len(equipos)}")
            return liga_id, str(fuente).rstrip("/"), equipos
        # Sin meta/fuente: si el schedule está, al menos sabemos los equipos
        sched = _fb(f"ligas/{liga_id}/schedule")
        equipos = equipos_de_schedule(sched) if sched else None
        print(f"   ⚠️  {liga_id} no tiene meta/fuente cargada — se usa el fallback de URL")
        return liga_id, FALLBACK_ZONA_URL, equipos

    # 3) Fallback
    print(f"   ⚠️  No se pudo resolver la zona desde Firebase — usando fallback")
    return FALLBACK_LIGA_ID, FALLBACK_ZONA_URL, None

def equipos_de_schedule(schedule):
    """Lista de equipos que aparecen en un schedule de liga."""
    eq = set()
    if not schedule: return []
    fechas = schedule.values() if isinstance(schedule, dict) else schedule
    for partidos in fechas:
        if not partidos: continue
        items = partidos.values() if isinstance(partidos, dict) else partidos
        for m in items:
            if not isinstance(m, dict): continue
            for k in ("h", "a", "local", "visitante", "libre"):
                if m.get(k): eq.add(str(m[k]).strip())
    return sorted(eq)

# ── SCRAPING DE RESULTADOS ────────────────────────────────────────────────────
def scrape_all(results_url):
    """
    Parsea TODOS los partidos de la página de resultados.
    Retorna:
      sc_results    {cat: [{fecha, rival, cond, gf, gc}]}
      rival_results {cat: {rival: [{f, vs, gf, gc}]}}          (legacy)
      team_results  {cat: {equipo: [{fecha, rival, cond, gf, gc}]}}
      all_matches   {cat: [(local, visit, gf_l, gc_l, fecha)]}
    """
    soup = get_soup(results_url)
    sc_results    = {cat: [] for cat in CATEGORIES}
    rival_results = {cat: {} for cat in CATEGORIES}
    team_results  = {cat: {} for cat in CATEGORIES}
    all_matches   = {cat: [] for cat in CATEGORIES}

    body = soup.find("body") or soup
    current_fecha = None

    for elem in body.descendants:
        if not hasattr(elem, "name") or not elem.name: continue

        if elem.name in ("p","h2","h3","strong","b","div","td"):
            m = re.search(r"Fecha\s*N[°º]?\s*(\d+)", elem.get_text(), re.IGNORECASE)
            if m:
                nf = int(m.group(1))
                if nf != current_fecha: current_fecha = nf

        if elem.name == "table" and current_fecha is not None:
            rows = elem.find_all("tr")
            if len(rows) < 2: continue
            hcells = [td.get_text().strip() for td in rows[0].find_all(["th","td"])]
            cat_cols = {}
            for i,h in enumerate(hcells):
                m2 = re.search(r"Cat\.?\s*\.?(\d+)", h, re.IGNORECASE)
                if m2: cat_cols[int(m2.group(1))] = i
            if not cat_cols: continue

            for row in rows[1:]:
                cells = [td.get_text().strip() for td in row.find_all("td")]
                if not cells: continue
                parts = re.split(r"\s+vs\.?\s+", cells[0], maxsplit=1, flags=re.IGNORECASE)
                if len(parts) != 2: continue
                local, visit = parts[0].strip(), parts[1].strip()

                for cat, col in cat_cols.items():
                    if col >= len(cells): continue
                    score = parse_score(cells[col])
                    if not score: continue
                    gf_l, gc_l = score

                    all_matches[cat].append((local, visit, gf_l, gc_l, current_fecha))

                    # sc_results: solo sagcor (retrocompatibilidad)
                    if is_sc(local):
                        sc_results[cat].append({"fecha":current_fecha,"rival":visit,"cond":"L","gf":gf_l,"gc":gc_l})
                    elif is_sc(visit):
                        sc_results[cat].append({"fecha":current_fecha,"rival":local,"cond":"V","gf":gc_l,"gc":gf_l})
                    else:
                        for team,gf,gc,vs in [(local,gf_l,gc_l,visit),(visit,gc_l,gf_l,local)]:
                            rival_results[cat].setdefault(team,[]).append({"f":current_fecha,"vs":vs,"gf":gf,"gc":gc})

                    # team_results: TODOS los equipos, formato unificado
                    team_results[cat].setdefault(local, []).append({"fecha":current_fecha,"rival":visit,"cond":"L","gf":gf_l,"gc":gc_l})
                    team_results[cat].setdefault(visit, []).append({"fecha":current_fecha,"rival":local,"cond":"V","gf":gc_l,"gc":gf_l})

            current_fecha = None

    for cat in CATEGORIES:
        sc_results[cat].sort(key=lambda x: x["fecha"])
        for team in team_results[cat]:
            team_results[cat][team].sort(key=lambda x: x["fecha"])
    return sc_results, rival_results, team_results, all_matches

# ── CALCULAR POSICIONES DESDE RESULTADOS ─────────────────────────────────────
def build_standings(all_matches, equipos_zona=None):
    """
    Tabla de posiciones a partir de los partidos scrapeados.
    LISFI: 2 puntos por victoria, 1 por empate, 0 por derrota.
    Si se conocen los equipos de la zona, los que todavía no jugaron
    aparecen igual en la tabla, en cero.
    """
    posiciones = {}
    for cat, matches in all_matches.items():
        teams = {}
        for eq in (equipos_zona or []):
            teams[eq] = {"pj":0,"pg":0,"pe":0,"pp":0,"gf":0,"gc":0}

        for local, visit, gf_l, gc_l, fecha in matches:
            for team in (local, visit):
                if team not in teams:
                    teams[team] = {"pj":0,"pg":0,"pe":0,"pp":0,"gf":0,"gc":0}

            teams[local]["pj"] += 1
            teams[local]["gf"] += gf_l
            teams[local]["gc"] += gc_l
            if   gf_l > gc_l:  teams[local]["pg"] += 1
            elif gf_l == gc_l: teams[local]["pe"] += 1
            else:              teams[local]["pp"] += 1

            teams[visit]["pj"] += 1
            teams[visit]["gf"] += gc_l
            teams[visit]["gc"] += gf_l
            if   gc_l > gf_l:  teams[visit]["pg"] += 1
            elif gc_l == gf_l: teams[visit]["pe"] += 1
            else:              teams[visit]["pp"] += 1

        standings = []
        for eq, s in teams.items():
            pts = s["pg"]*2 + s["pe"]
            standings.append({"eq":eq,"pj":s["pj"],"pg":s["pg"],"pe":s["pe"],
                              "pp":s["pp"],"gf":s["gf"],"gc":s["gc"],"pts":pts})
        standings.sort(key=lambda x: (-x["pts"], -(x["gf"]-x["gc"]), -x["gf"]))
        posiciones[cat] = standings
    return posiciones

# ── VERIFICACIÓN ──────────────────────────────────────────────────────────────
def verify(sc_results, posiciones, n, equipos_zona=None):
    errors = []

    # 1. Las 8 categorías presentes en posiciones
    for cat in CATEGORIES:
        if not posiciones.get(cat):
            errors.append(f"Cat {cat}: tabla de posiciones vacía")

    # 2. Cantidad de equipos.
    #    Si Firebase dice cuántos son, se compara contra eso. Si no, rango amplio
    #    (6-24) para que no falle al cambiar a una zona más grande o más chica.
    esperados = len(equipos_zona) if equipos_zona else None
    for cat in CATEGORIES:
        n_eq = len(posiciones.get(cat, []))
        if n_eq == 0: continue
        if esperados:
            if n_eq > esperados:
                errors.append(f"Cat {cat}: {n_eq} equipos, la zona tiene {esperados}")
        elif n_eq < 6 or n_eq > 24:
            errors.append(f"Cat {cat}: {n_eq} equipos (esperado 6-24)")

    # 3. PTS = PG*2 + PE
    for cat in CATEGORIES:
        for row in posiciones.get(cat, []):
            expected = row["pg"]*2 + row["pe"]
            if row["pts"] != expected:
                errors.append(f"Cat {cat} — {row['eq']}: pts={row['pts']} esperado {expected}")

    # 4. PJ = PG + PE + PP
    for cat in CATEGORIES:
        for row in posiciones.get(cat, []):
            if row["pj"] != row["pg"]+row["pe"]+row["pp"]:
                errors.append(f"Cat {cat} — {row['eq']}: PJ inconsistente")

    # 5. Goles razonables
    for cat in CATEGORIES:
        for r in sc_results.get(cat, []):
            if r["gf"] < 0 or r["gc"] < 0:
                errors.append(f"Cat {cat} F{r['fecha']}: goles negativos")
            if r["gf"] > 25 or r["gc"] > 25:
                errors.append(f"Cat {cat} F{r['fecha']} vs {r['rival']}: marcador sospechoso {r['gf']}-{r['gc']}")

    # 6. SC tiene resultados en al menos 6 de 8 categorías.
    #    Al principio de una zona nueva puede no haber ningún partido jugado:
    #    eso no es un error de scraping, así que solo se exige si hay partidos.
    hay_partidos = any(posiciones.get(cat) and any(r["pj"] for r in posiciones[cat]) for cat in CATEGORIES)
    if hay_partidos:
        cats_ok = sum(1 for cat in CATEGORIES if sc_results.get(cat))
        if cats_ok < 6:
            errors.append(f"Solo {cats_ok}/8 categorías con resultados SC (posible fallo de scraping)")
    else:
        print("   ℹ️  Zona sin partidos jugados todavía — tabla en cero (no es error)")

    # 7. Sin fechas duplicadas para SC
    for cat in CATEGORIES:
        fechas = [r["fecha"] for r in sc_results.get(cat, [])]
        if len(fechas) != len(set(fechas)):
            errors.append(f"Cat {cat}: fechas duplicadas en SC — {sorted(fechas)}")

    # 8. Los equipos scrapeados tienen que ser los de la zona vigente.
    #    Si no coinciden, la página que se está scrapeando es de otra zona.
    if equipos_zona:
        norm = lambda s: re.sub(r"[.\s]", "", str(s)).upper()[:5]
        de_la_zona = {norm(e) for e in equipos_zona}
        vistos = {norm(r["eq"]) for cat in CATEGORIES for r in posiciones.get(cat, []) if r["pj"]}
        if vistos:
            comunes = len(vistos & de_la_zona)
            if comunes / len(vistos) < 0.7:
                errors.append(f"Los equipos scrapeados no son los de la zona vigente "
                              f"({comunes}/{len(vistos)} coinciden) — ¿la URL apunta a otra zona?")

    ok = len(errors) == 0
    print(f"   Verificación #{n}: {'✅ OK' if ok else f'❌ {len(errors)} error/es'}")
    for e in errors: print(f"      • {e}")
    return ok, errors

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_errors = []

    print("🔎 Resolviendo zona vigente...")
    liga_id, zona_url, equipos_zona = resolver_zona()
    results_url = f"{zona_url}/resultados"
    print(f"   liga_id : {liga_id}")
    print(f"   URL     : {results_url}")

    for attempt in range(1, 4):
        print(f"\n{'='*50}\n  INTENTO {attempt}/3\n{'='*50}")
        try:
            print("⏳ Scrapeando resultados...")
            sc_results, rival_results, team_results, all_matches = scrape_all(results_url)
            print("📐 Calculando posiciones desde resultados...")
            posiciones = build_standings(all_matches, equipos_zona)
        except Exception as e:
            msg = f"Error: {e}"
            print(f"❌ {msg}")
            all_errors.append(msg)
            if attempt < 3:
                print("   Reintentando en 10s...")
                time.sleep(10)
            continue

        print("🔍 Verificando datos...")
        ok, errors = verify(sc_results, posiciones, attempt, equipos_zona)

        if ok:
            updated_at = datetime.now().strftime("%d/%m/%Y")
            liga_data = {
                "updatedAt":    updated_at,
                # 'zona' es lo que mira la app para saber si estos datos son de la
                # zona vigente. Sin este campo compara equipos; con él, es directo.
                "zona":         liga_id,
                "fuente":       zona_url,
                "scResults":    {str(k): v for k, v in sc_results.items()},
                "rivalResults": {str(k): v for k, v in rival_results.items()},
                "teamResults":  {str(k): v for k, v in team_results.items()},
                "posiciones":   {str(k): v for k, v in posiciones.items()},
            }
            with open("liga_data.json", "w", encoding="utf-8") as f:
                json.dump(liga_data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ liga_data.json actualizado — {updated_at}")
            print(f"   zona: {liga_id}  (verificado en intento {attempt}/3)\n")
            for cat in CATEGORIES:
                print(f"   Cat {cat}: {len(sc_results.get(cat,[]))} SC · {len(posiciones.get(cat,[]))} equipos")
            sys.exit(0)
        else:
            all_errors.extend(errors)
            if attempt < 3:
                print("   Reintentando en 15s...")
                time.sleep(15)

    print(f"\n{'='*50}")
    print("  ❌ LOS 3 INTENTOS FALLARON — liga_data.json NO modificado")
    print(f"{'='*50}")
    seen = set()
    for e in all_errors:
        if e not in seen:
            print(f"  • {e}")
            seen.add(e)
    print("\n⚠️  Revisá la pestaña Actions en GitHub para ver los detalles.\n")
    sys.exit(1)

if __name__ == "__main__":
    main()
