#!/usr/bin/env python3
"""
Scraper de LAPF (Liga Amateur Platense de Fútbol) — lapf.com.ar

Estructura de página MUY distinta a scrape_lisfi.py: ahí una sola página trae
TODAS las categorías juntas (columnas "Cat.13", "Cat.14"...). Acá cada
fecha de cada división es su propia página:

    https://lapf.com.ar/datos-torneo/{torneoId}/{categoriaId}/{fecha}/{rueda}

Por eso hay que recorrer, para cada zona activa, una página por fecha (la
paginación "Fechas: 1 2 3...N" la trae la propia página, no está escrita a
mano acá). La tabla de posiciones de la rueda, en cambio, sale entera en
cualquier fecha — no hace falta sumarla partido por partido. Ojo: el sitio
tiene una tabla aparte que él mismo llama "Acumulada" y no es lo que parece
(no es "esta rueda con todos los partidos sumados": es un acumulado de TODOS
los torneos históricos del club) — no se usa acá, ver el comentario en
scrape_una_division().

Solo se scrapea la RUEDA QUE ESTÁ EN CURSO: la que quedó guardada en
ligas/_activa al dar de alta el club (ver saCrearClubFinal en index.html).
Una rueda ya terminada no se toca sola — se archiva a mano el día que haga
falta, con el mismo mecanismo de override manual que ya tiene scrape_lisfi.py
(variables de entorno), para no perder el número de fecha en que se cerró.

Salida: liga_data_{ligaId}.json por cada zona LAPF activa (mismo formato que
liga_data_{ligaId}.json de scrape_lisfi.py: schedule/teamResults/posiciones/
meta), para que el resto de la app (deriveFixtureFromSchedule,
resultadosDelClub, etc.) lea exactamente igual sin importar de qué liga
vino el dato.

Varias divisiones por zona (TRICOLORES en 5ta y 6ta, por ejemplo): se
comprobó a mano contra el sitio que TODAS las divisiones de un mismo torneo
juegan el mismo fixture (misma fecha, mismo club rival — solo cambian los
resultados y la tabla de cada una), así que el `schedule` es uno solo por
zona, pero `teamResults`/`posiciones` se guardan por separado por división
(mismo número que DIVISION_CATS en index.html), igual que ya hace
scrape_lisfi.py con sus categorías. Qué divisiones scrapear de cada zona sale
de sumar los `cats` de todos los clubes que la tienen como `ligas/_activa`
(un club puede jugar más de una), no de adivinar ni de hardcodear una sola.
"""

import requests
from bs4 import BeautifulSoup
import json, re, os, sys, time
from datetime import datetime

# GitHub Actions corre en Linux con UTF-8 y nunca lo notó, pero corriendo esto
# a mano en Windows la consola por defecto usa cp1252, que no tiene los
# emojis de los mensajes de abajo -- print() revienta con UnicodeEncodeError
# antes de llegar a scrapear nada.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

FIREBASE_DB = os.environ.get(
    "FIREBASE_DB",
    "https://presentes-20226-cat-16-sc-default-rtdb.firebaseio.com"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ClubSC-Bot/1.0)"}

# Mismo número que DIVISION_CATS en index.html — si se cambia acá, hay que
# cambiarlo ahí también, o las tablas de posiciones/resultados de esta
# división le van a chocar a otra en LIGA_DATA.teamResults[num]/posiciones[num].
DIVISION_NUM = {
    "5TA DIVISION": 101, "6TA DIVISION": 102, "7MA DIVISION": 103,
    "8VA DIVISION": 104, "9NA DIVISION": 105, "PRE-9NA DIVISION": 106,
}


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


# ── RESOLVER QUÉ ZONAS DE LAPF SCRAPEAR ───────────────────────────────────
def resolver_zonas_lapf():
    """
    Lee ligas/_activa (mismo nodo público que ya usa scrape_lisfi.py) y
    devuelve solo las que apuntan a lapf.com.ar, agrupadas por ligaId —
    varios clubes pueden compartir la misma división y no hace falta
    bajarla dos veces. De paso junta, para cada zona, las divisiones que
    juega CUALQUIERA de sus clubes.

    Esas divisiones salen del propio campo "divisiones" de ligas/_activa/{id}
    (lo escribe el wizard de Super Admin al dar de alta o ampliar un club) y
    NO de clubs/{id}/cats: ese nodo no es público, las reglas de Firebase le
    devuelven 401 a una lectura sin sesión como la de este script.
    """
    env_url = os.environ.get("LAPF_ZONA_URL")
    env_id = os.environ.get("LIGA_ID")
    if env_url:
        print(f"🔧 Zona por variable de entorno: {env_url}")
        return [{"liga_id": env_id or "lapf-override", "url": env_url.rstrip("/"), "clubes": ["(env)"], "divisiones": set()}]

    activa = _fb("ligas/_activa")
    zonas = {}
    if isinstance(activa, dict):
        for club_id, info in activa.items():
            if not isinstance(info, dict): continue
            liga_id = info.get("ligaId")
            fuente = info.get("fuente")
            if not liga_id or not fuente or "lapf.com.ar" not in fuente:
                continue
            z = zonas.setdefault(liga_id, {"liga_id": liga_id, "url": str(fuente).rstrip("/"), "clubes": [], "divisiones": set()})
            z["clubes"].append(club_id)
            divisiones = info.get("divisiones") or []
            if isinstance(divisiones, dict):
                divisiones = list(divisiones.values())
            for d in divisiones:
                if d:
                    z["divisiones"].add(str(d).upper())

    if zonas:
        print(f"🔗 {len(zonas)} zona(s) de LAPF activa(s):")
        for z in zonas.values():
            print(f"   • {z['liga_id']}  ← {', '.join(sorted(z['clubes']))}")
            print(f"     {z['url']}  ·  divisiones: {', '.join(sorted(z['divisiones'])) or '(solo la de la URL)'}")
    else:
        print("   ⚠️  Ninguna zona de LAPF activa en ligas/_activa — nada para scrapear")
    return list(zonas.values())


# ── SCRAPEAR UNA DIVISIÓN/RUEDA COMPLETA ──────────────────────────────────
def scrape_una_division(torneo_id, cat_id, rueda, primera_soup=None):
    """
    Recorre todas las fechas de torneo_id/cat_id/*/rueda y arma schedule +
    resultados de todos los equipos + posiciones de ESA división. Devuelve
    None si la página no tiene la forma esperada (sitio caído, categoría que
    ya no existe, etc.) — no revienta el resto de las divisiones/zonas.

    primera_soup: si ya se bajó la fecha 1 de esta división (por ejemplo al
    descubrir las divisiones de la zona), se reutiliza en vez de pedirla de
    nuevo.
    """
    base = f"https://lapf.com.ar/datos-torneo/{torneo_id}/{cat_id}"
    primera = primera_soup or get_soup(f"{base}/1/{rueda}")
    if primera is None:
        return None

    # El nombre de la división se saca cruzando cat_id contra el "value" de
    # cada <option> del selector — ESE es el dato confiable. El atributo
    # "selected" del HTML no se usa: depende de cómo lo arme el framework del
    # sitio, y si algún día cambia, agarrar la primera opción por error
    # metería los resultados de OTRA división acá.
    sel_cat = primera.find(id="categoriaSelectDesktopFixture") or primera.find(id="categoriaSelectMobile")
    nombre_division = None
    if sel_cat:
        for opt in sel_cat.find_all("option"):
            om = re.search(r"/datos-torneo/\d+/(\d+)/", opt.get("value", ""))
            if om and om.group(1) == cat_id:
                nombre_division = opt.get_text(strip=True)
                break
    cat_num = DIVISION_NUM.get((nombre_division or "").upper())
    if cat_num is None:
        print(f"   ⚠️  División \"{nombre_division}\" no está en DIVISION_NUM — agregarla ahí y en index.html")
        return None

    sel_torneo = primera.find(id="torneoSelect")
    nombre_torneo = None
    if sel_torneo:
        opt = sel_torneo.find("option", selected=True)
        if opt: nombre_torneo = opt.get_text(strip=True)

    # Cuántas fechas tiene esta rueda: se leen los links de paginación de la
    # propia página en vez de hardcodear 15 (una división con menos equipos
    # tiene menos fechas).
    fecha_links = primera.find_all("a", href=re.compile(rf"/datos-torneo/{torneo_id}/{cat_id}/\d+/{rueda}"))
    fechas_nums = sorted({int(re.search(r"/(\d+)/\d+$", a["href"]).group(1)) for a in fecha_links if re.search(r"/(\d+)/\d+$", a["href"])})
    n_fechas = max(fechas_nums) if fechas_nums else 1

    schedule = {}
    team_results = {}
    equipos = set()
    ultima_soup = primera

    for fecha in range(1, n_fechas + 1):
        if fecha == 1:
            soup = primera
        else:
            try:
                soup = get_soup(f"{base}/{fecha}/{rueda}")
            except Exception as e:
                print(f"   ⚠️  Fecha {fecha}: {e} — se saltea, las demás fechas siguen")
                soup = None
        if soup is None:
            continue
        ultima_soup = soup
        # OJO: el id exacto, no "Fixture" suelto — la página también tiene un
        # GVFixtureMobile (versión celular) que aparece ANTES en el HTML y
        # tiene una estructura de celdas totalmente distinta (sin el nombre
        # del equipo en el <td>, va aparte); con un regex suelto agarraba esa
        # por error y salían partidos con nombres vacíos.
        tabla = soup.find("table", id="GVFixtureDesktop")
        if tabla is None:
            continue
        partidos = []
        for tr in tabla.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            local = tds[0].get_text(strip=True)
            gf_txt = tds[1].get_text(strip=True)
            visit = tds[4].get_text(strip=True)
            gc_txt = tds[3].get_text(strip=True)
            estado = tds[5].get_text(strip=True)
            if not local or not visit:
                continue
            equipos.add(local); equipos.add(visit)
            partidos.append({"h": local, "a": visit})
            if estado.lower().startswith("termin") and gf_txt.isdigit() and gc_txt.isdigit():
                gf, gc = int(gf_txt), int(gc_txt)
                team_results.setdefault(local, []).append({"fecha": fecha, "rival": visit, "cond": "L", "gf": gf, "gc": gc})
                team_results.setdefault(visit, []).append({"fecha": fecha, "rival": local, "cond": "V", "gf": gc, "gc": gf})
        if partidos:
            schedule[str(fecha)] = partidos
        time.sleep(0.3)  # no golpear el sitio fecha tras fecha sin respiro

    for eq in team_results:
        team_results[eq].sort(key=lambda x: x["fecha"])

    # Tabla de posiciones de ESTA rueda: sale completa en cualquier página, no
    # hace falta ir a buscarla aparte. OJO acá también con el id exacto: hay
    # una "GVPosicionesAcumuladasDesktop" que no es "esta rueda con todos los
    # partidos sumados" como parece por el nombre, sino un acumulado de TODOS
    # los torneos históricos del club (se probó: da 135 partidos jugados para
    # una rueda de 8 fechas) — no sirve para nada de lo que necesita la app.
    posiciones = []
    ptabla = ultima_soup.find("table", id="GVPosicionesDesktop")
    if ptabla:
        for tr in ptabla.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 9:
                continue
            eq = tds[1].get_text(strip=True)
            if not eq:
                continue
            try:
                nums = [int(tds[i].get_text(strip=True) or 0) for i in range(2, 9)]
            except ValueError:
                continue
            pts, pj, pg, pe, pp, gf, gc = nums
            posiciones.append({"eq": eq, "pts": pts, "pj": pj, "pg": pg, "pe": pe, "pp": pp, "gf": gf, "gc": gc})

    return {
        "cat_num": cat_num,
        "nombre_division": nombre_division,
        "nombre_torneo": nombre_torneo,
        "n_fechas": n_fechas,
        "schedule": schedule,
        "team_results": team_results,
        "posiciones": posiciones,
        "equipos": equipos,
    }


# ── SCRAPEAR UNA ZONA COMPLETA (una o varias divisiones) ──────────────────
def scrape_zona(url, divisiones_extra):
    """
    url: la fuente con la que se dio de alta la zona — una división puntual
    (torneoId/categoriaId/fecha/rueda). Su categoriaId SIEMPRE se scrapea.
    divisiones_extra: nombres de división (ver DIVISION_NUM) de otros clubes
    de la misma zona que juegan una división distinta — se agregan si el
    propio selector de categorías del sitio las conoce para este torneo.
    """
    m = re.search(r"/datos-torneo/(\d+)/(\d+)/\d+/(\d+)", url)
    if not m:
        print(f"   ⚠️  URL con forma inesperada, no es datos-torneo/T/C/F/R: {url}")
        return None
    torneo_id, cat_id_base, rueda = m.groups()

    primera = get_soup(f"https://lapf.com.ar/datos-torneo/{torneo_id}/{cat_id_base}/1/{rueda}")
    if primera is None:
        return None

    # categoriaId de cada división de ESTE torneo, según el propio selector
    # del sitio (no se hardcodea: cada torneo puede numerarlas distinto).
    sel_cat = primera.find(id="categoriaSelectDesktopFixture") or primera.find(id="categoriaSelectMobile")
    cat_id_por_nombre = {}
    if sel_cat:
        for opt in sel_cat.find_all("option"):
            om = re.search(r"/datos-torneo/\d+/(\d+)/", opt.get("value", ""))
            if om:
                cat_id_por_nombre[opt.get_text(strip=True).upper()] = om.group(1)

    a_scrapear = [(cat_id_base, primera)]  # la de la URL, ya bajada
    for nombre_div in sorted(divisiones_extra):
        cid = cat_id_por_nombre.get(nombre_div)
        if not cid:
            print(f"   ⚠️  \"{nombre_div}\" no aparece en el selector de este torneo — se saltea")
            continue
        if cid == cat_id_base:
            continue
        a_scrapear.append((cid, None))

    schedule_zona = None
    team_results_por_cat = {}
    posiciones_por_cat = {}
    equipos_zona = set()
    nombre_torneo_zona = None
    n_fechas_zona = 0

    for cid, soup_ya_bajada in a_scrapear:
        print(f"   … división categoriaId={cid}")
        d = scrape_una_division(torneo_id, cid, rueda, primera_soup=soup_ya_bajada)
        if d is None:
            print(f"      ⚠️  no se pudo scrapear categoriaId={cid} — se saltea, las demás siguen")
            continue
        # El schedule es el mismo fixture para todas las divisiones del
        # torneo (mismo club rival cada fecha, comprobado a mano contra el
        # sitio) — alcanza con guardarlo una vez, de la división con más
        # fechas resueltas por si alguna vino incompleta.
        if schedule_zona is None or len(d["schedule"]) > len(schedule_zona):
            schedule_zona = d["schedule"]
        team_results_por_cat[str(d["cat_num"])] = d["team_results"]
        posiciones_por_cat[str(d["cat_num"])] = d["posiciones"]
        equipos_zona |= d["equipos"]
        nombre_torneo_zona = nombre_torneo_zona or d["nombre_torneo"]
        n_fechas_zona = max(n_fechas_zona, d["n_fechas"])

    if not team_results_por_cat:
        return None

    return {
        "updatedAt": datetime.now().strftime("%d/%m/%Y"),
        "zona": f"{torneo_id}-{cat_id_base}-{rueda}",
        "schedule": schedule_zona or {},
        "teamResults": team_results_por_cat,
        "posiciones": posiciones_por_cat,
        "meta": {
            "ligaId": None,  # lo completa quien llama, ya sabe el liga_id real
            "nombre": nombre_torneo_zona,
            "liga": "LAPF",
            "fechas": n_fechas_zona,
            "equipos": sorted(equipos_zona),
            "actualizadoEl": datetime.now().strftime("%Y-%m-%d"),
        },
    }


def main():
    zonas = resolver_zonas_lapf()
    if not zonas:
        return
    index = {}
    alguna_ok = False
    for z in zonas:
        print(f"\n📥 Scrapeando {z['liga_id']} ({z['url']})...")
        # Que falle esta zona (sitio caído, HTML cambiado, lo que sea) no
        # puede impedir que se guarden las demás — cada una es independiente.
        try:
            datos = scrape_zona(z["url"], z.get("divisiones", set()))
        except Exception as e:
            print(f"   ❌ {z['liga_id']}: {e}")
            datos = None
        if not datos or not datos["teamResults"]:
            print(f"   ❌ {z['liga_id']}: no se pudo scrapear (o quedó vacía) — se deja el archivo anterior como estaba")
            continue
        datos["meta"]["ligaId"] = z["liga_id"]
        # "zona" tiene que ser el ligaId real, no el identificador interno de
        # LAPF (torneo-categoria-rueda): es lo que compara _coincideZona() en
        # index.html contra la zona que la app tiene abierta. Con cualquier
        # otro valor, el archivo se descarga pero nunca se aplica.
        datos["zona"] = z["liga_id"]
        fname = f"liga_data_{z['liga_id']}.json"
        n_equipos_res = sum(len(v) for v in datos["teamResults"].values())
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        print(f"   ✅ {fname}: {len(datos['schedule'])} fechas, {len(datos['meta']['equipos'])} equipos, "
              f"{len(datos['teamResults'])} división(es), {n_equipos_res} equipos con resultados cargados")
        index[z["liga_id"]] = {"actualizadoEl": datos["meta"]["actualizadoEl"], "equipos": len(datos["meta"]["equipos"])}
        alguna_ok = True

    if index:
        with open("liga_data_lapf_index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    if not alguna_ok:
        raise SystemExit("Todas las zonas de LAPF fallaron")


if __name__ == "__main__":
    main()
