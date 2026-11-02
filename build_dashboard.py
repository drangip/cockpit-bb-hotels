"""Construit le cockpit B&B HOTELS (HTML autonome) à partir de l'export hôtels + performances.

Usage : python build_dashboard.py [chemin_xlsx]
        python build_dashboard.py --template   (réutilise les agrégats en cache)
Sortie : cockpit_bb_hotels.html + site/index.html (données, logos et carte embarqués)
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
XLSX = ARGS[0] if ARGS else os.path.join(ROOT, "perf", "b&b-adresse & performance.xlsx")
GEO_CACHE = os.path.join(ROOT, "data", "geocode_hotels.csv")
DEP_CACHE = os.path.join(ROOT, "data", "departements.geojson")
TEMPLATE = os.path.join(ROOT, "dashboard_template.html")
OUT = os.path.join(ROOT, "cockpit_bb_hotels.html")
SITE_OUT = os.path.join(ROOT, "site", "index.html")  # version servie par Vercel
PAYLOAD_CACHE = os.path.join(ROOT, "data", "agregats_mensuels.json")

BAN_URL = "https://api-adresse.data.gouv.fr/search/csv/"
DEP_URL = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson"

# Familles de channels affichées (ordre = empilement du graphique en aires, du bas vers le haut)
GROUPS = [
    ("seo", "SEO", ["SEO"]),
    ("sea_b", "SEA Brand", ["SEA Google - Brand", "SEA Google - Brand (conversion)",
                            "SEA Bing - Brand", "SEA Bing - Brand (conversion)"]),
    ("sea_nb", "SEA Non Brand", ["SEA Google - Non Brand", "SEA Google - Non Brand (awareness/consideration)",
                                 "SEA Bing - Non Brand", "SEA Bing - Non Brand (awareness/consideration)"]),
    ("gmaps", "Google Maps", ["Google Maps"]),
    ("meta", "Metasearch", ["Metasearch"]),
    ("aff", "Affiliation", ["Affiliation"]),
    ("direct", "Direct", ["Direct"]),
    # 8 familles max (lisibilité du graphique empilé) : Email, Referral, Display, Social, AI Assistants, Unassigned…
    ("other", "Autres", []),
]
ADDR_RX = re.compile(r"^(.*?)\s*,\s*(\d{5})\s+([^,]+?)\s*(?:,\s*France)?\s*$")


def norm_channel(c: str) -> str:
    return re.sub(r"\s+", " ", str(c)).strip()


def group_of(channel: str) -> str:
    n = norm_channel(channel)
    for k, _, members in GROUPS:
        if n in {norm_channel(m) for m in members}:
            return k
    return "other"


def dep_code(cp: str) -> str:
    if cp.startswith("20"):
        return "2A" if int(cp) < 20200 else "2B"
    if cp.startswith("97"):
        return cp[:3]
    return cp[:2]


def read_xlsx(path: str) -> dict:
    """Lit les deux onglets (fichier verrouillé = ouvert dans Excel ou en cours de synchro OneDrive)."""
    try:
        return pd.read_excel(path, sheet_name=None, engine="openpyxl")
    except PermissionError:
        sys.exit(f"Fichier verrouillé : fermez-le dans Excel puis relancez.\n  {path}")


def ban_csv(df: pd.DataFrame, **fields) -> pd.DataFrame:
    """Géocodage par lot via la Base Adresse Nationale."""
    boundary = "----bbcockpit"
    body = io.BytesIO()
    payload = df.to_csv(index=False).encode("utf-8")

    def part(name, value, filename=None):
        body.write(f"--{boundary}\r\n".encode())
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        body.write(f"Content-Disposition: {disp}\r\n\r\n".encode())
        body.write(value if isinstance(value, bytes) else value.encode())
        body.write(b"\r\n")

    part("data", payload, "in.csv")
    for k, v in fields.items():
        part(k, v)
    body.write(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        BAN_URL, data=body.getvalue(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return pd.read_csv(io.BytesIO(r.read()), dtype=str)


def geocode(hotels: pd.DataFrame) -> pd.DataFrame:
    if os.path.exists(GEO_CACHE):
        cache = pd.read_csv(GEO_CACHE, dtype={"key": str})
        if set(hotels["key"]) <= set(cache["key"]):
            return cache
    q = hotels[["key", "street", "cp", "town"]].copy()
    res = ban_csv(q, columns="street", postcode="cp", city="town")
    res["result_score"] = pd.to_numeric(res["result_score"], errors="coerce").fillna(0)
    ok = (res["result_score"] >= 0.5) & (res["result_postcode"].fillna("").str[:2] == res["cp"].str[:2])
    geo = res.loc[ok, ["key", "latitude", "longitude"]].assign(precision="adresse")
    # Repli : centre de la commune
    miss = q[~q["key"].isin(geo["key"])]
    if len(miss):
        res2 = ban_csv(miss[["key", "cp", "town"]], columns="town", postcode="cp")
        geo = pd.concat([geo, res2[["key", "latitude", "longitude"]].assign(precision="commune")])
    # Dernier recours (codes postaux CEDEX…) : nom de commune seul
    miss = q[~q["key"].isin(geo.dropna(subset=["latitude"])["key"])]
    if len(miss):
        res3 = ban_csv(miss[["key", "town"]], columns="town")
        geo = pd.concat([geo[~geo["key"].isin(miss["key"])],
                         res3[["key", "latitude", "longitude"]].assign(precision="commune")])
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    os.makedirs(os.path.dirname(GEO_CACHE), exist_ok=True)
    geo.to_csv(GEO_CACHE, index=False)
    print(f"Géocodage : {(geo['precision'] == 'adresse').sum()} à l'adresse, {(geo['precision'] == 'commune').sum()} à la commune")
    return geo


def departements() -> dict:
    if not os.path.exists(DEP_CACHE):
        os.makedirs(os.path.dirname(DEP_CACHE), exist_ok=True)
        urllib.request.urlretrieve(DEP_URL, DEP_CACHE)
    with open(DEP_CACHE, encoding="utf-8") as f:
        gj = json.load(f)

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]

    for ft in gj["features"]:
        ft["geometry"]["coordinates"] = rnd(ft["geometry"]["coordinates"])
    return gj


def b64(path: str, mime: str) -> str:
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def as_int(v):
    return None if pd.isna(v) else int(v)


def main():
    # Cache des agrégats : évite de relire l'Excel quand seul le template change
    if "--template" in sys.argv and os.path.exists(PAYLOAD_CACHE):
        with open(PAYLOAD_CACHE, encoding="utf-8") as f:
            payload = json.load(f)
        write_html(payload, departements())
        return
    print("Lecture", XLSX)
    sheets = read_xlsx(XLSX)
    h = sheets["hotel"]
    p = sheets["performance"]
    h.columns = [c.strip() for c in h.columns]
    p.columns = [c.strip() for c in p.columns]
    VB = "Hotel ID - Vertical Booking"

    # Référentiel hôtels
    h = h.drop_duplicates(VB).copy()
    parts = h["Adresse"].astype(str).str.strip().str.extract(ADDR_RX)
    h["street"], h["cp"], h["town"] = parts[0].fillna(h["Adresse"]), parts[1].fillna(""), parts[2].fillna(h["City Name"])
    h["key"] = h[VB].astype(str)
    h["dep"] = h["cp"].map(lambda c: dep_code(c) if c else "")
    geo = geocode(h).drop_duplicates("key")
    h = h.merge(geo[["key", "latitude", "longitude", "precision"]], on="key", how="left")

    # Performances mensuelles
    p["month"] = p["Year"].astype(int).astype(str) + "-" + p["Month (int)"].astype(int).astype(str).str.zfill(2)
    p["Channel"] = p["Channel"].map(norm_channel)
    months = sorted(p["month"].unique())
    channels = (p.groupby("Channel")["Revenue"].sum().sort_values(ascending=False).index.tolist())
    ch_idx = {c: i for i, c in enumerate(channels)}
    agg = p.groupby([VB, "Channel", "month"])["Revenue"].sum()
    print(f"Mois : {months[0]} -> {months[-1]} ({len(months)}), {len(channels)} channels")

    m_idx = {m: i for i, m in enumerate(months)}
    rev = {}
    for (hid, ch, m), v in agg.items():
        rec = rev.setdefault(int(hid), {})
        arr = rec.setdefault(ch_idx[ch], [0] * len(months))
        arr[m_idx[m]] = round(float(v))

    h = h.sort_values(["dep", "City Name", "Hotel Name"]).reset_index(drop=True)
    out = []
    for _, r in h.iterrows():
        hid, obj = int(r[VB]), r.get("Obj Room Rev Mois")
        out.append({
            "vb": hid, "pim": as_int(r["Hotel ID - PIM"]), "pms": as_int(r["Hotel ID - PMS"]),
            "n": r["Hotel Name"], "url": r["LP Hotel FR"], "ic": as_int(r["ID City"]), "c": r["City Name"],
            "st": r["street"], "cp": r["cp"], "t": r["town"], "d": r["dep"],
            "lat": None if pd.isna(r["latitude"]) else round(float(r["latitude"]), 5),
            "lng": None if pd.isna(r["longitude"]) else round(float(r["longitude"]), 5),
            "geo": r["precision"] if isinstance(r["precision"], str) else None,
            # Objectif absent ou à 0 : traité comme non renseigné
            "obj": None if obj is None or pd.isna(obj) or obj <= 0 else round(float(obj)),
            "r": {str(k): v for k, v in sorted(rev.get(hid, {}).items())},
        })

    gj = departements()
    payload = {
        "months": months,
        "channels": [{"n": c, "g": group_of(c)} for c in channels],
        "groups": [{"k": k, "n": n} for k, n, _ in GROUPS],
        "hotels": out,
        "deps": {f["properties"]["code"]: f["properties"]["nom"] for f in gj["features"]},
    }
    with open(PAYLOAD_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    write_html(payload, gj)


def write_html(payload, gj):
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = (
        html.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        .replace("__GEO__", json.dumps(gj, ensure_ascii=False, separators=(",", ":")))
        .replace("__LOGO_BB__", b64(os.path.join(ROOT, "logo", "b&b.png"), "image/png"))
        .replace("__LOGO_WPP__", b64(os.path.join(ROOT, "logo", "wppmedia.png"), "image/png"))
    )
    os.makedirs(os.path.dirname(SITE_OUT), exist_ok=True)
    for path in (OUT, SITE_OUT):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    print(f"OK -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} Mo, {len(payload['hotels'])} hôtels)")


if __name__ == "__main__":
    main()
