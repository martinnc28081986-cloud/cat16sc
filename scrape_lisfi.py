#!/usr/bin/env python3
"""
Scraper de ligas — multi-zona, con verificación triple.

Ninguna zona está escrita en el código: se leen de Firebase, del nodo público
`ligas/_activa`, que la app escribe cuando migra un club de temporada.

Antes este script bajaba UNA sola zona: la del club fijo CLUB_ID. Con varios
clubes en ligas distintas (LISFI, LAFIR, ...) eso dejaba a la mayoría sin datos.
Ahora recorre todas las zonas activas y genera un archivo por zona.

Orden de resolución:
  1) Variables de entorno (override manual, una sola zona):
        LISFI_ZONA_URL / LIGA_ID
  2) Firebase: ligas/_activa  → todas las zonas que juega algún club
  3) Fallback hardcodeado de abajo

Salida:
  liga_data_{ligaId}.json   una por zona activa
  liga_data.json            copia de la zona de CLUB_ID (compatibilidad:
                            es la que bajan las versiones viejas de la app)
  liga_data_index.json      qué zonas hay, cuándo se actualizó cada una

Una zona que no pasa la verificación NO se escribe — su archivo anterior queda
intacto. El job falla solo si fallaron TODAS.
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
CLUB_ID = os.environ.get("CLUB_ID", "sagrado-corazon")

# Se usan solo si Firebase no responde o no tiene ninguna zona cargada
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


# ── RESOLVER QUÉ ZONAS SCRAPEAR ───────────────────────────────────────────────
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


def _equipos_de_zona(liga_id):
    """Equipos esperados de una zona: de meta/equipos, o derivados del schedule."""
    meta = _fb(f"ligas/{liga_id}/meta") or {}
    if meta.get("equipos"):
        return meta["equipos"]
    sched = _fb(f"ligas/{liga_id}/schedule")
    return equipos_de_schedule(sched) if sched else None


def resolver_zonas():
    """
    Devuelve la lista de zonas a scrapear:
        [{"liga_id":..., "url":..., "equipos":[...], "clubes":[...]}, ...]
    """
    # 1) Override manual: una sola zona, para forzar algo puntual a mano
    env_url = os.environ.get("LISFI_ZONA_URL")
    env_id  = os.environ.get("LIGA_ID")
    if env_url:
        liga_id = env_id or FALLBACK_LIGA_ID
        print(f"🔧 Zona por variable de entorno: {env_url}")
        print("   (no se toca liga_data.json: el override sirve para recuperar")
        print("    una zona vieja sin pisar la de la temporada en curso)")
        return [{"liga_id": liga_id, "url": env_url.rstrip("/"),
                 "equipos": _equipos_de_zona(liga_id), "clubes": ["(env)"],
                 "es_override": True}]

    # 2) Todas las zonas activas. ligas/_activa es el único nodo que la app deja
    #    abierto sin login, justamente para que este script lo pueda leer.
    activa = _fb("ligas/_activa")
    zonas = {}
    if isinstance(activa, dict):
        for club_id, info in activa.items():
            if not isinstance(info, dict): continue
            liga_id = info.get("ligaId")
            fuente  = info.get("fuente")
            if not liga_id or not fuente:
                print(f"   ⚠️  {club_id}: sin ligaId o sin fuente — se saltea")
                continue
            z = zonas.setdefault(liga_id, {"liga_id": liga_id,
                                           "url": str(fuente).rstrip("/"),
                                           "equipos": None, "clubes": []})
            z["clubes"].append(club_id)

    if zonas:
        print(f"🔗 {len(zonas)} zona(s) activa(s) en Firebase:")
        for z in zonas.values():
            z["equipos"] = _equipos_de_zona(z["liga_id"])
            n = len(z["equipos"]) if z["equipos"] else "?"
            print(f"   • {z['liga_id']}  ({n} equipos)  ← {', '.join(sorted(z['clubes']))}")
            print(f"     {z['url']}")
        # La zona del club principal va primera: es la que se copia a liga_data.json
        orden = sorted(zonas.values(), key=lambda z: (CLUB_ID not in z["clubes"], z["liga_id"]))
        return orden

    # 3) Fallback
    print("   ⚠️  No se pudo resolver ninguna zona desde Firebase — usando fallback")
    return [{"liga_id": FALLBACK_LIGA_ID, "url": FALLBACK_ZONA_URL,
             "equipos": _equipos_de_zona(FALLBACK_LIGA_ID), "clubes": ["(fallback)"]}]


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
def scrape_general(zona_url):
    """
    Tabla GENERAL de la zona, tal como la publica LISFI en la página de la zona
    (no en /posiciones, que solo trae las tablas por categoría).

    Importa traerla y no calcularla: LISFI la arma sumando SOLO las categorías
    2013 a 2018 — las 2019 y 2020 no entran —, y ese criterio es de ellos y puede
    cambiar. Calculándola por nuestra cuenta el número no daría igual y el
    coordinador vería una tabla que no coincide con la de la liga.

    Devuelve [{"eq","pj","pg","pe","pp","gf","gc","pts"}, ...] o [] si no está.
    """
    soup = get_soup(zona_url)
    for tabla in soup.find_all("table"):
        filas = tabla.find_all("tr")
        if len(filas) < 6:
            continue
        cab = [c.get_text(strip=True).upper() for c in filas[0].find_all(["th", "td"])]
        # La reconocemos por sus columnas, no por su posición ni por un título:
        # si LISFI reordena la página, esto sigue funcionando.
        if not cab or "PTS" not in cab:
            continue
        if not any(k in cab[0] for k in ("CLUB", "EQUIPO")):
            continue
        idx = {n: i for i, n in enumerate(cab)}
        out = []
        for tr in filas[1:]:
            celdas = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(celdas) < len(cab):
                continue
            eq = celdas[0].strip()
            if not eq:
                continue
            def num(col):
                try:
                    return int(celdas[idx[col]])
                except (KeyError, ValueError, IndexError):
                    return 0
            out.append({"eq": eq, "pj": num("PJ"), "pg": num("PG"), "pe": num("PE"),
                        "pp": num("PP"), "gf": num("GF"), "gc": num("GC"), "pts": num("PTS")})
        if len(out) >= 6:
            print(f"   ✓ Tabla general: {len(out)} clubes")
            return out
    print("   ⚠️  No se encontró la tabla general en la página de la zona")
    return []


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
def verify(sc_results, posiciones, n, equipos_zona=None, exigir_sc=True):
    """
    exigir_sc: solo tiene sentido en la zona donde juega Sagrado Corazón.
    En las otras zonas (LAFIR, etc.) sc_results viene vacío y eso es correcto.
    """
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
    if not hay_partidos:
        print("   ℹ️  Zona sin partidos jugados todavía — tabla en cero (no es error)")
    elif exigir_sc:
        cats_ok = sum(1 for cat in CATEGORIES if sc_results.get(cat))
        if cats_ok < 6:
            errors.append(f"Solo {cats_ok}/8 categorías con resultados SC (posible fallo de scraping)")

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


# ── UNA ZONA ──────────────────────────────────────────────────────────────────
def procesar_zona(zona):
    """
    Scrapea y verifica una zona, con 3 intentos.
    Devuelve (liga_data | None, errores).
    """
    liga_id = zona["liga_id"]
    equipos = zona["equipos"]
    results_url = f"{zona['url']}/resultados"
    # Sagrado solo juega en su zona; en las demás no tiene que haber resultados suyos
    exigir_sc = CLUB_ID in zona.get("clubes", []) and is_sc(CLUB_ID)

    print(f"\n{'─'*58}\n  ZONA: {liga_id}\n  URL : {results_url}\n{'─'*58}")
    errores = []

    for attempt in range(1, 4):
        print(f"  Intento {attempt}/3")
        try:
            print("   ⏳ Scrapeando resultados...")
            sc_results, rival_results, team_results, all_matches = scrape_all(results_url)
            print("   📐 Calculando posiciones desde resultados...")
            posiciones = build_standings(all_matches, equipos)
            # La general se BAJA de LISFI, no se calcula: ellos suman solo de la
            # 2013 a la 2018 y ese criterio es suyo. Si falla, se sigue igual:
            # es un dato de más, no vale abortar el scrapeo por él.
            try:
                print("   ⏳ Bajando la tabla general de la zona...")
                general = scrape_general(zona["url"])
            except Exception as e:
                print(f"   ⚠️  No se pudo bajar la tabla general: {e}")
                general = []
        except Exception as e:
            msg = f"[{liga_id}] Error: {e}"
            print(f"   ❌ {msg}")
            errores.append(msg)
            if attempt < 3:
                print("      Reintentando en 10s...")
                time.sleep(10)
            continue

        print("   🔍 Verificando datos...")
        ok, errs = verify(sc_results, posiciones, attempt, equipos, exigir_sc)
        if ok:
            return {
                "updatedAt":    datetime.now().strftime("%d/%m/%Y"),
                # 'zona' es lo que mira la app para saber si estos datos son de la
                # zona vigente. Sin este campo compara equipos; con él, es directo.
                "zona":         liga_id,
                "fuente":       zona["url"],
                "clubes":       sorted(zona.get("clubes", [])),
                "scResults":    {str(k): v for k, v in sc_results.items()},
                "rivalResults": {str(k): v for k, v in rival_results.items()},
                "teamResults":  {str(k): v for k, v in team_results.items()},
                "posiciones":   {str(k): v for k, v in posiciones.items()},
                # Tal cual la publica LISFI. Vacía si esta vez no se pudo leer.
                "general":      general,
            }, errores
        errores.extend(f"[{liga_id}] {e}" for e in errs)
        if attempt < 3:
            print("      Reintentando en 15s...")
            time.sleep(15)

    return None, errores


def escribir(nombre, data):
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   💾 {nombre}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("🔎 Resolviendo zonas activas...")
    zonas = resolver_zonas()

    ok_zonas, fallidas, todos_los_errores = [], [], []

    for zona in zonas:
        data, errores = procesar_zona(zona)
        todos_los_errores.extend(errores)
        if data:
            escribir(f"liga_data_{zona['liga_id']}.json", data)
            # La primera zona de la lista es la del club principal: se copia a
            # liga_data.json, que es lo que bajan las versiones viejas de la app.
            # Con un override manual NO se copia: se estaría pisando la zona
            # vigente con una vieja que se está recuperando.
            if zona is zonas[0] and not zona.get("es_override"):
                escribir("liga_data.json", data)
            ok_zonas.append((zona, data))
        else:
            fallidas.append(zona["liga_id"])
            print(f"   ⚠️  {zona['liga_id']}: los 3 intentos fallaron — su archivo NO se toca")

    # Índice: sirve para ver de un vistazo qué zonas hay y de cuándo son
    if ok_zonas:
        escribir("liga_data_index.json", {
            "generadoEl": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "zonas": [{
                "ligaId":    z["liga_id"],
                "archivo":   f"liga_data_{z['liga_id']}.json",
                "fuente":    z["url"],
                "clubes":    sorted(z.get("clubes", [])),
                "updatedAt": d["updatedAt"],
                "equipos":   len(d["posiciones"].get("16", [])),
            } for z, d in ok_zonas],
            "fallidas": fallidas,
        })

    print(f"\n{'='*58}")
    print(f"  {len(ok_zonas)}/{len(zonas)} zona(s) actualizada(s)")
    for z, d in ok_zonas:
        n_cats = sum(1 for c in CATEGORIES if d["posiciones"].get(str(c)))
        print(f"   ✅ {z['liga_id']}  ({n_cats} categorías · {', '.join(sorted(z.get('clubes',[])))})")
    for lid in fallidas:
        print(f"   ❌ {lid}")
    print(f"{'='*58}")

    if not ok_zonas:
        print("\n  ❌ NINGUNA ZONA PUDO ACTUALIZARSE — no se modificó ningún archivo")
        seen = set()
        for e in todos_los_errores:
            if e not in seen:
                print(f"  • {e}")
                seen.add(e)
        print("\n⚠️  Revisá la pestaña Actions en GitHub para ver los detalles.\n")
        sys.exit(1)

    if fallidas:
        # Que falle una zona no puede impedir que se guarden las que sí anduvieron.
        print("\n⚠️  Algunas zonas fallaron. Sus archivos quedaron como estaban.")
        seen = set()
        for e in todos_los_errores:
            if e not in seen:
                print(f"  • {e}")
                seen.add(e)
    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
