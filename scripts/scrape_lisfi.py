#!/usr/bin/env python3
"""
Scraper LISFI Zona II B 2026
Genera liga_data.json con resultados y posiciones actualizados.
Ejecutado por GitHub Actions dos veces por semana.
"""
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

RESULTS_URL  = "https://www.lisfi.com.ar/index.php/liga-2b-2026/resultados"
POSICION_URL = "https://www.lisfi.com.ar/index.php/liga-2b-2026/posiciones"
CATEGORIES   = [13, 14, 15, 16, 17, 18, 19, 20]
SC_RE        = re.compile(r'sagr', re.IGNORECASE)
HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; ClubSC-Bot/1.0)"}


def is_sc(name):
    return bool(SC_RE.search(name))


def parse_score(s):
    """'3-1' → (3, 1)  |  cualquier otra cosa → None"""
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def get_soup(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.content, "lxml")


# ── RESULTADOS ────────────────────────────────────────────────────────────────
def scrape_results():
    soup = get_soup(RESULTS_URL)
    sc_results    = {cat: [] for cat in CATEGORIES}
    rival_results = {cat: {} for cat in CATEGORIES}

    body = soup.find("body") or soup
    current_fecha = None

    for elem in body.descendants:
        if not hasattr(elem, "name") or not elem.name:
            continue

        # Detectar cabecera de fecha
        if elem.name in ("p", "h2", "h3", "strong", "b", "div", "td"):
            text = elem.get_text()
            m = re.search(r"Fecha\s*N[°º]?\s*(\d+)", text, re.IGNORECASE)
            if m:
                new_fecha = int(m.group(1))
                if new_fecha != current_fecha:
                    current_fecha = new_fecha

        # Procesar tabla cuando hay fecha activa
        if elem.name == "table" and current_fecha is not None:
            rows = elem.find_all("tr")
            if len(rows) < 2:
                continue

            # Cabecera → índices de columnas por categoría
            header_cells = [td.get_text().strip() for td in rows[0].find_all(["th", "td"])]
            cat_cols = {}
            for i, h in enumerate(header_cells):
                m2 = re.search(r"Cat\.?\s*\.?(\d+)", h, re.IGNORECASE)
                if m2:
                    cat_cols[int(m2.group(1))] = i

            if not cat_cols:
                continue

            for row in rows[1:]:
                cells = [td.get_text().strip() for td in row.find_all("td")]
                if not cells:
                    continue

                # Parsear "Local vs. Visitante"
                parts = re.split(r"\s+vs\.?\s+", cells[0], maxsplit=1, flags=re.IGNORECASE)
                if len(parts) != 2:
                    continue
                local, visit = parts[0].strip(), parts[1].strip()
                sc_l, sc_v   = is_sc(local), is_sc(visit)

                for cat, col in cat_cols.items():
                    if col >= len(cells):
                        continue
                    score = parse_score(cells[col])
                    if not score:
                        continue
                    gf_l, gc_l = score

                    if sc_l:
                        sc_results[cat].append(
                            {"fecha": current_fecha, "rival": visit, "cond": "L", "gf": gf_l, "gc": gc_l}
                        )
                    elif sc_v:
                        sc_results[cat].append(
                            {"fecha": current_fecha, "rival": local, "cond": "V", "gf": gc_l, "gc": gf_l}
                        )
                    else:
                        # Guardar resultados de rivales para comparativa
                        for team, gf, gc, vs in [
                            (local, gf_l, gc_l, visit),
                            (visit, gc_l, gf_l, local),
                        ]:
                            rival_results[cat].setdefault(team, []).append(
                                {"f": current_fecha, "vs": vs, "gf": gf, "gc": gc}
                            )

            current_fecha = None  # tabla consumida

    for cat in CATEGORIES:
        sc_results[cat].sort(key=lambda x: x["fecha"])

    return sc_results, rival_results


# ── POSICIONES ────────────────────────────────────────────────────────────────
def scrape_standings():
    soup = get_soup(POSICION_URL)
    posiciones   = {cat: [] for cat in CATEGORIES}
    current_cat  = None

    body = soup.find("body") or soup

    for elem in body.descendants:
        if not hasattr(elem, "name") or not elem.name:
            continue

        # Cabecera de categoría
        if elem.name not in ("table",):
            text = elem.get_text()
            m = re.search(r"Posiciones\s+Categor[íi]a\s*(\d{4})", text, re.IGNORECASE)
            if m:
                cat = int(m.group(1))
                if cat in CATEGORIES:
                    current_cat = cat
            continue

        # Tabla de posiciones
        if current_cat is None:
            continue

        rows = elem.find_all("tr")
        if len(rows) < 3:
            continue

        header_cells = [td.get_text().strip().upper() for td in rows[0].find_all(["th", "td"])]
        if "PJ" not in header_cells or "PTS" not in header_cells:
            continue

        def col(name):
            try:
                return next(i for i, h in enumerate(header_cells) if h == name)
            except StopIteration:
                return None

        eq_c  = next((i for i, h in enumerate(header_cells) if "EQUIPO" in h or h == ""), None)
        pj_c  = col("PJ");  pg_c = col("PG"); pe_c = col("PE"); pp_c = col("PP")
        gf_c  = col("GF");  gc_c = col("GC"); pts_c = col("PTS")

        if None in (eq_c, pj_c, pg_c, pe_c, pp_c, gf_c, gc_c, pts_c):
            continue

        standings = []
        for row in rows[1:]:
            cells = [td.get_text().strip() for td in row.find_all("td")]
            if len(cells) <= pts_c:
                continue
            eq = cells[eq_c].strip()
            if not eq:
                continue
            try:
                standings.append({
                    "eq": eq,
                    "pj": int(cells[pj_c]),
                    "pg": int(cells[pg_c]),
                    "pe": int(cells[pe_c]),
                    "pp": int(cells[pp_c]),
                    "gf": int(cells[gf_c]),
                    "gc": int(cells[gc_c]),
                    "pts": int(cells[pts_c]),
                })
            except (ValueError, IndexError):
                continue

        if standings:
            posiciones[current_cat] = standings
            current_cat = None

    return posiciones


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("⏳ Scrapeando resultados LISFI Zona II B...")
    sc_results, rival_results = scrape_results()

    print("⏳ Scrapeando posiciones...")
    posiciones = scrape_standings()

    updated_at = datetime.now().strftime("%d/%m/%Y")

    liga_data = {
        "updatedAt": updated_at,
        "scResults":     {str(k): v for k, v in sc_results.items()},
        "rivalResults":  {str(k): v for k, v in rival_results.items()},
        "posiciones":    {str(k): v for k, v in posiciones.items()},
    }

    with open("liga_data.json", "w", encoding="utf-8") as f:
        json.dump(liga_data, f, ensure_ascii=False, indent=2)

    print(f"✅ liga_data.json actualizado — {updated_at}")
    for cat in CATEGORIES:
        n_sc  = len(sc_results.get(cat, []))
        n_pos = len(posiciones.get(cat, []))
        print(f"   Cat {cat}: {n_sc} resultados SC · {n_pos} equipos en tabla")


if __name__ == "__main__":
    main()
