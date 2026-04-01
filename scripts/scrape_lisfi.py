#!/usr/bin/env python3
"""
Scraper LISFI Zona II B 2026 — con verificación triple.
Genera liga_data.json solo si los 3 intentos de verificación pasan.
"""
import requests
from bs4 import BeautifulSoup
import json, re, sys, time
from datetime import datetime

RESULTS_URL  = "https://www.lisfi.com.ar/index.php/liga-2b-2026/resultados"
POSICION_URL = "https://www.lisfi.com.ar/index.php/liga-2b-2026/posiciones"
CATEGORIES   = [13, 14, 15, 16, 17, 18, 19, 20]
SC_RE        = re.compile(r'sagr', re.IGNORECASE)
HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; ClubSC-Bot/1.0)"}

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

# ── RESULTADOS ────────────────────────────────────────────────────────────────
def scrape_results():
    soup = get_soup(RESULTS_URL)
    sc_results    = {cat: [] for cat in CATEGORIES}
    rival_results = {cat: {} for cat in CATEGORIES}
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
                    if is_sc(local):
                        sc_results[cat].append({"fecha":current_fecha,"rival":visit,"cond":"L","gf":gf_l,"gc":gc_l})
                    elif is_sc(visit):
                        sc_results[cat].append({"fecha":current_fecha,"rival":local,"cond":"V","gf":gc_l,"gc":gf_l})
                    else:
                        for team,gf,gc,vs in [(local,gf_l,gc_l,visit),(visit,gc_l,gf_l,local)]:
                            rival_results[cat].setdefault(team,[]).append({"f":current_fecha,"vs":vs,"gf":gf,"gc":gc})
            current_fecha = None

    for cat in CATEGORIES: sc_results[cat].sort(key=lambda x: x["fecha"])
    return sc_results, rival_results

# ── POSICIONES ────────────────────────────────────────────────────────────────
def scrape_standings():
    soup = get_soup(POSICION_URL)
    posiciones = {cat: [] for cat in CATEGORIES}
    current_cat = None
    body = soup.find("body") or soup

    for elem in body.descendants:
        if not hasattr(elem, "name") or not elem.name: continue
        if elem.name != "table":
            m = re.search(r"Posiciones\s+Categor[íi]a\s*(\d{4})", elem.get_text(), re.IGNORECASE)
            if m:
                cat = int(m.group(1))
                if cat in CATEGORIES: current_cat = cat
            continue
        if current_cat is None: continue
        rows = elem.find_all("tr")
        if len(rows) < 3: continue
        hcells = [td.get_text().strip().upper() for td in rows[0].find_all(["th","td"])]
        if "PJ" not in hcells or "PTS" not in hcells: continue
        def col(name):
            try: return next(i for i,h in enumerate(hcells) if h==name)
            except StopIteration: return None
        eq_c  = next((i for i,h in enumerate(hcells) if "EQUIPO" in h or h==""), None)
        pj_c,pg_c,pe_c,pp_c,gf_c,gc_c,pts_c = col("PJ"),col("PG"),col("PE"),col("PP"),col("GF"),col("GC"),col("PTS")
        if None in (eq_c,pj_c,pg_c,pe_c,pp_c,gf_c,gc_c,pts_c): continue
        standings = []
        for row in rows[1:]:
            cells = [td.get_text().strip() for td in row.find_all("td")]
            if len(cells) <= pts_c: continue
            eq = cells[eq_c].strip()
            if not eq: continue
            try:
                standings.append({"eq":eq,"pj":int(cells[pj_c]),"pg":int(cells[pg_c]),"pe":int(cells[pe_c]),
                                   "pp":int(cells[pp_c]),"gf":int(cells[gf_c]),"gc":int(cells[gc_c]),"pts":int(cells[pts_c])})
            except (ValueError, IndexError): continue
        if standings:
            posiciones[current_cat] = standings
            current_cat = None
    return posiciones

# ── VERIFICACIÓN ──────────────────────────────────────────────────────────────
def verify(sc_results, posiciones, n):
    errors = []

    # 1. Las 8 categorías presentes en posiciones
    for cat in CATEGORIES:
        if not posiciones.get(cat):
            errors.append(f"Cat {cat}: tabla de posiciones vacía o no encontrada")

    # 2. Cantidad de equipos razonable (Zona II B tiene 11)
    for cat in CATEGORIES:
        n_eq = len(posiciones.get(cat, []))
        if 0 < n_eq < 6 or n_eq > 14:
            errors.append(f"Cat {cat}: {n_eq} equipos en tabla (esperado 8-14)")

    # 3. PTS = PG*2 + PE  (LISFI: 2 puntos por victoria)
    for cat in CATEGORIES:
        for row in posiciones.get(cat, []):
            expected = row["pg"]*2 + row["pe"]
            if row["pts"] != expected:
                errors.append(f"Cat {cat} — {row['eq']}: pts={row['pts']} pero PG×2+PE={expected}")

    # 4. PJ = PG + PE + PP
    for cat in CATEGORIES:
        for row in posiciones.get(cat, []):
            if row["pj"] != row["pg"] + row["pe"] + row["pp"]:
                errors.append(f"Cat {cat} — {row['eq']}: PJ={row['pj']} ≠ PG+PE+PP={row['pg']+row['pe']+row['pp']}")

    # 5. Goles no negativos ni absurdos
    for cat in CATEGORIES:
        for r in sc_results.get(cat, []):
            if r["gf"] < 0 or r["gc"] < 0:
                errors.append(f"Cat {cat} F{r['fecha']}: goles negativos ({r['gf']}-{r['gc']})")
            if r["gf"] > 25 or r["gc"] > 25:
                errors.append(f"Cat {cat} F{r['fecha']} vs {r['rival']}: marcador sospechoso {r['gf']}-{r['gc']}")

    # 6. SC tiene resultados en al menos 6 de 8 categorías
    cats_ok = sum(1 for cat in CATEGORIES if sc_results.get(cat))
    if cats_ok < 6:
        errors.append(f"Solo {cats_ok}/8 categorías tienen resultados de SC (posible fallo de scraping)")

    # 7. Sin fechas duplicadas para SC
    for cat in CATEGORIES:
        fechas = [r["fecha"] for r in sc_results.get(cat, [])]
        if len(fechas) != len(set(fechas)):
            errors.append(f"Cat {cat}: fechas duplicadas en SC — {sorted(fechas)}")

    ok = len(errors) == 0
    print(f"   Verificación #{n}: {'✅ OK' if ok else f'❌ {len(errors)} error/es'}")
    for e in errors: print(f"      • {e}")
    return ok, errors

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_errors = []

    for attempt in range(1, 4):
        print(f"\n{'='*50}\n  INTENTO {attempt}/3\n{'='*50}")
        try:
            print("⏳ Scrapeando resultados...")
            sc_results, rival_results = scrape_results()
            print("⏳ Scrapeando posiciones...")
            posiciones = scrape_standings()
        except Exception as e:
            msg = f"Error de conexión: {e}"
            print(f"❌ {msg}")
            all_errors.append(msg)
            if attempt < 3:
                print("   Reintentando en 10s...")
                time.sleep(10)
            continue

        print("🔍 Verificando datos...")
        ok, errors = verify(sc_results, posiciones, attempt)

        if ok:
            updated_at = datetime.now().strftime("%d/%m/%Y")
            liga_data = {
                "updatedAt":    updated_at,
                "scResults":    {str(k): v for k, v in sc_results.items()},
                "rivalResults": {str(k): v for k, v in rival_results.items()},
                "posiciones":   {str(k): v for k, v in posiciones.items()},
            }
            with open("liga_data.json", "w", encoding="utf-8") as f:
                json.dump(liga_data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ liga_data.json actualizado — {updated_at}")
            print(f"   (verificado en intento {attempt}/3)\n")
            for cat in CATEGORIES:
                print(f"   Cat {cat}: {len(sc_results.get(cat,[]))} SC · {len(posiciones.get(cat,[]))} equipos")
            sys.exit(0)
        else:
            all_errors.extend(errors)
            if attempt < 3:
                print("   Reintentando en 15s...")
                time.sleep(15)

    # Los 3 intentos fallaron
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
