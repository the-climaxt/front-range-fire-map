#!/usr/bin/env python3
"""
Colorado Fire Map — single builder (live site, auto-publisher, and example).

  python build.py              -> index.html (re-scrapes forest/county pages)
  python build.py --no-scrape  -> index.html from the baked values (no network)
  python build.py --demo       -> Example_calm_day.html (simulated calm day)

Reads map_template3.html + rules.js + co_counties_all.geojson from this folder.
BLM and Red Flag Warnings are fetched live in the browser, so they never need
rebuilding.

Honesty rules (see AUDIT.md):
  * A scrape MISS never silently keeps a stale value as if fresh — the value is
    kept but marked verified=False with its last-verified date, and the miss is
    written to _build_report.json so CI can fail loudly.
  * County levels that were never read from an official page are shipped as
    floor=True ("at least Stage 1 — unverified"), never as confirmed.
  * Red-Flag auto-restriction applies ONLY to counties with a verified
    auto-rule (RF_AUTO below).
"""
import json, os, re, sys, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPE = ("--no-scrape" not in sys.argv) and ("--demo" not in sys.argv)
DEMO = "--demo" in sys.argv
UA = {"User-Agent": "ColoradoFireMap/2.0 (+github pages; public-safety info)"}
TODAY = datetime.date.today().isoformat()

REPORT = {"date": TODAY, "scrape": SCRAPE, "forests": {}, "counties": {}, "errors": [], "misses": []}

def fetch(url, timeout=25):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            if r.status != 200:
                REPORT["errors"].append("HTTP %s %s" % (r.status, url)); return ""
            return body
    except Exception as e:
        REPORT["errors"].append("fetch failed %s -> %s" % (url, e)); return ""

# --------------------------------------------------------------------------
# parse_stage v2 (AUDIT C4). The old regex required "Stage N ... in effect"
# within 80 chars and missed every real 2026 transition headline ("enters
# Stage 2", "moves to Stage 2", "effective July 1"), while matching
# definitional text ("when Stage 2 restrictions are in effect, ...").
# --------------------------------------------------------------------------
_ROMAN = {"1": "Stage 1", "i": "Stage 1", "2": "Stage 2", "ii": "Stage 2", "3": "Stage 3", "iii": "Stage 3"}
_TRANS = re.compile(
    r"(?:enter(?:s|ed|ing)?|mov(?:es?|ed|ing)\s+(?:in)?to|implement(?:s|ed|ing)?"
    r"|go(?:es|ing)?\s+(?:in)?to|went\s+(?:in)?to|begin(?:s|ning)?|adopt(?:s|ed)?"
    r"|issue(?:s|d)?|under)\s+stage\s*(iii|ii|i|3|2|1)\b")
_INEFF = re.compile(r"stage\s*(iii|ii|i|3|2|1)\b[^.]{0,80}?(?:now\s+in\s+effect|in\s+effect|in\s+place|implemented|effective)")
_GUARD = re.compile(r"(?:when|if|during|should|would|may\s+be|what\s+are|explanation)\W*$")   # definitional prefix
_LIFT = re.compile(
    r"(?:rescind(?:s|ed)?|lift(?:s|ed|ing)?|terminat(?:es?|ed)|remov(?:es?|ed))[^.]{0,60}"
    r"(?:stage\s*(?:iii|ii|i|3|2|1)|fire\s+restriction)"
    r"|stage\s*(?:iii|ii|i|3|2|1)\b[^.]{0,60}(?:rescinded|lifted|terminated|no\s+longer\s+in\s+effect)")
_NONE = re.compile(r"no\s+(?:current\s+)?fire\s+restrictions|no\s+active\s+fire\s+restriction"
                   r"|fire\s+restrictions\s+are\s+not\s+(?:currently\s+)?in\s+(?:effect|place)")

def _text(html):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).lower()

def parse_stage(html):
    """Return 'Stage 1|2|3', 'None', or None (= could not tell — caller must
    treat as unverified, NEVER as a silent keep-as-fresh)."""
    if not html:
        return None
    t = _text(html)
    strong = []
    for m in _TRANS.finditer(t):
        strong.append(_ROMAN[m.group(1)])
    weak = []
    for m in _INEFF.finditer(t):
        prefix = t[max(0, m.start() - 40):m.start()]
        if _GUARD.search(prefix):          # "when/if ... Stage 2 ... in effect" = definition, skip
            continue
        if re.search(r"\b(?:may|might|would|could|can|will)\s+be\b|\bwhen\b|\bif\b", m.group(0)):
            continue                       # "Stage 3 ... may be implemented" = speculation, skip
        weak.append(_ROMAN[m.group(1)])
    picked = strong or weak
    if picked:
        # If both an old and a new stage are on the page, take the most severe
        # (over-warn rather than under-warn; full rescinds are caught below).
        return max(picked, key=lambda s: int(s[-1]))
    if _LIFT.search(t) or _NONE.search(t):
        return "None"
    return None

# --------------------------------------------------------------------------
# Forests. Baked stages hand-verified 2026-07-02 against each forest's
# alert/newsroom pages (see AUDIT.md B1):
#   ARP Stage 1 (Sulphur RD none) · PSICC Stage 1 (forest-wide posted order)
#   White River Stage 2 (CO-WRF-2026-14, eff 6/26) · GMUG Stage 2 (6/30)
#   San Juan Stage 2 (eff 7/1) · Rio Grande None · Routt (MBR) Stage 1
# "uniform": scrape may apply a forest-wide stage to all its districts.
# ARP stays per-district (Sulphur differs) — never auto-overridden.
# --------------------------------------------------------------------------
USFS_BAKED_ASOF = "2026-07-02"
FORESTS = {
 "Arapaho-Roosevelt NF": {"slug": "arp", "uniform": False},
 "Pike-San Isabel NF":   {"slug": "psicc", "uniform": True},
 "White River NF":       {"slug": "whiteriver", "uniform": True},
 "GMUG NF":              {"slug": "gmug", "uniform": True},
 "Rio Grande NF":        {"slug": "riogrande", "uniform": True},
 "San Juan NF":          {"slug": "sanjuan", "uniform": True},
 "Medicine Bow-Routt NF": {"slug": "mbrtb", "uniform": True},
}
def D(name, stage, counties, forest):
    # counties: hand-entered, approximate — used for polygon FILL worst-case
    # and the area list only; click/GPS answers use the county at the exact
    # point. TODO: replace with a build-time spatial join (AUDIT B3).
    return {"name": name, "stage": stage, "counties": counties, "forest": forest,
            "verified": False, "checked": USFS_BAKED_ASOF}
USFS_STATUS = {
 # Arapaho-Roosevelt (per-district)
 "021005": D("Canyon Lakes Ranger District", "Stage 1", "Larimer", "Arapaho-Roosevelt NF"),
 "021001": D("Boulder Ranger District", "Stage 1", "Boulder, Gilpin", "Arapaho-Roosevelt NF"),
 "021007": D("Clear Creek Ranger District", "Stage 1", "Clear Creek, Jefferson, Gilpin", "Arapaho-Roosevelt NF"),
 "021008": D("Sulphur Ranger District", "None", "Grand", "Arapaho-Roosevelt NF"),
 "021006": D("Pawnee National Grassland", "Stage 1", "Weld", "Arapaho-Roosevelt NF"),
 # Pike-San Isabel
 "021202": D("Salida Ranger District", "Stage 1", "Chaffee, Fremont, Saguache, Lake", "Pike-San Isabel NF"),
 "021201": D("Leadville Ranger District", "Stage 1", "Lake, Chaffee, Park, Eagle, Summit", "Pike-San Isabel NF"),
 "021209": D("Pikes Peak Ranger District", "Stage 1", "El Paso, Teller", "Pike-San Isabel NF"),
 "021210": D("South Park Ranger District", "Stage 1", "Park, Jefferson", "Pike-San Isabel NF"),
 "021211": D("South Platte Ranger District", "Stage 1", "Jefferson, Douglas, Teller, Park, Clear Creek", "Pike-San Isabel NF"),
 "021203": D("San Carlos Ranger District", "Stage 1", "Custer, Fremont, Pueblo, Huerfano, Las Animas, Costilla, Saguache", "Pike-San Isabel NF"),
 "021206": D("Comanche National Grassland", "Stage 1", "Baca, Las Animas, Otero", "Pike-San Isabel NF"),
 # White River — Stage 2 since 6/26/2026 (Order CO-WRF-2026-14)
 "021502": D("Blanco Ranger District", "Stage 2", "Rio Blanco, Garfield", "White River NF"),
 "021501": D("Aspen Ranger District", "Stage 2", "Pitkin, Gunnison", "White River NF"),
 "021510": D("Dillon Ranger District", "Stage 2", "Summit", "White River NF"),
 "021503": D("Sopris Ranger District", "Stage 2", "Garfield, Pitkin, Eagle", "White River NF"),
 "021504": D("Eagle-Holy Cross Ranger District", "Stage 2", "Eagle", "White River NF"),
 "021507": D("Holy Cross Ranger District", "Stage 2", "Eagle, Lake", "White River NF"),
 "021508": D("Rifle Ranger District", "Stage 2", "Garfield, Rio Blanco", "White River NF"),
 # GMUG — Stage 2 since 6/30/2026
 "020402": D("Grand Valley Ranger District", "Stage 2", "Mesa", "GMUG NF"),
 "020405": D("Norwood Ranger District", "Stage 2", "San Miguel, Montrose", "GMUG NF"),
 "020406": D("Ouray Ranger District", "Stage 2", "Ouray, Montrose", "GMUG NF"),
 "020407": D("Gunnison Ranger District", "Stage 2", "Gunnison, Hinsdale, Saguache", "GMUG NF"),
 "020408": D("Paonia Ranger District", "Stage 2", "Delta, Gunnison", "GMUG NF"),
 # Rio Grande — no restrictions (fire danger Low, 7/2/2026)
 "020903": D("Conejos Peak Ranger District", "None", "Conejos, Archuleta, Rio Grande", "Rio Grande NF"),
 "020904": D("Divide Ranger District", "None", "Mineral, Rio Grande, Hinsdale", "Rio Grande NF"),
 "020907": D("Saguache Ranger District", "None", "Saguache", "Rio Grande NF"),
 # San Juan — Stage 2 effective 7/1/2026
 "021308": D("Columbine Ranger District", "Stage 2", "La Plata, San Juan, Hinsdale", "San Juan NF"),
 "021305": D("Mancos-Dolores Ranger District", "Stage 2", "Montezuma, Dolores, La Plata", "San Juan NF"),
 "021306": D("Pagosa Ranger District", "Stage 2", "Archuleta, Hinsdale, Mineral", "San Juan NF"),
 # Medicine Bow-Routt (Colorado districts) — Routt NF Stage 1 since 6/18/2026
 "020601": D("Yampa Ranger District", "Stage 1", "Routt, Garfield, Eagle", "Medicine Bow-Routt NF"),
 "020603": D("Hahns Peak-Bears Ears Ranger District", "Stage 1", "Routt, Moffat, Jackson", "Medicine Bow-Routt NF"),
 "020604": D("Parks Ranger District", "Stage 1", "Jackson, Grand, Larimer", "Medicine Bow-Routt NF"),
}

def scrape_forests():
    """Refresh each uniform forest's stage from its official pages.
    Success -> stage + verified=True + checked=today.
    Miss    -> keep baked stage, verified stays False, recorded in REPORT."""
    for fk, info in FORESTS.items():
        if not info["uniform"]:
            REPORT["forests"][fk] = "per-district (not scraped)"; continue
        sl = info["slug"]; stage = None
        # alert/newsroom pages first; the fire/fire-restrictions explainer LAST
        for path in ("alerts/fire-restrictions", "alerts", "fire/fire-restrictions"):
            stage = parse_stage(fetch("https://www.fs.usda.gov/r02/%s/%s" % (sl, path)))
            if stage:
                break
        REPORT["forests"][fk] = stage or "MISS"
        if stage:
            for code, d in USFS_STATUS.items():
                if d["forest"] == fk:
                    d["stage"] = stage; d["verified"] = True; d["checked"] = TODAY
        else:
            REPORT["misses"].append("forest: " + fk)

# --------------------------------------------------------------------------
# Counties. verified entries were read from each county's official page on
# 2026-07-02 (AUDIT B1). RF_AUTO = counties with a VERIFIED automatic
# Red-Flag restriction rule — the only ones the map may legally flip.
# Denver & Broomfield are consolidated city-counties -> municipal rules.
# --------------------------------------------------------------------------
RF_AUTO = {"Jefferson", "Clear Creek"}
DFPC_URL = "https://dfpc.colorado.gov/sections/wildfire-information-center/fire-restriction-information"
VERIFIED = {
 "Jefferson County": {"stage": "Stage 2", "url": "https://www.jeffcosheriffco.gov/safety/wildland-fire/fire-restrictions",
   "note": "Red Flag Warning auto-triggers Stage 1 county-wide; Jeffco Open Space & Denver Mountain Parks are always Stage 2."},
 "Douglas County": {"stage": "Stage 2", "url": "https://dcsheriff.net/sheriffs-office/divisions/emergency-management/fire-restrictions/",
   "note": "Escalated to Stage 2 on 7/2/2026; includes Larkspur and Castle Pines."},
 "Chaffee County": {"stage": "Stage 2", "url": "https://www.chaffeecounty.org/departments/sheriff/fire_restrictions.php",
   "note": "Includes Salida, Buena Vista, Poncha Springs by joint adoption (6/24/2026)."},
 "Summit County": {"stage": "Stage 2", "url": "https://www.summitcountyco.gov/services/community_development/csu_extension/forest_health/fire_restrictions.php",
   "note": "Stage 2 since 6/26/2026."},
 "Eagle County": {"stage": "Stage 2", "url": "https://www.eaglecounty.us/departments___services/emergency_management/fire_restrictions.php",
   "note": "Stage 2 since 6/24/2026; county policy: Red Flag during Stage 2 escalates to Stage 3."},
 "El Paso County": {"stage": "Stage 2", "url": "https://epcsheriffsoffice.com/services/fire-information/",
   "note": "Stage II since 6/29/2026; open burning is auto-banned during any Red Flag Warning."},
 "Boulder County": {"stage": "Stage 1", "url": "https://bouldercounty.gov/safety/fire/fire-restrictions/",
   "note": "Mountains/foothills; a Stage 2 (west) amendment was reported 7/2 — order in flux. Open burning auto-banned during Red Flag / High Wind alerts."},
 "Larimer County": {"stage": "Stage 1", "url": "https://www.larimer.gov/emergency",
   "note": "Unlabeled countywide order through 7/21/2026, zoned by elevation and stricter than a typical Stage 1 (bans contained open fires) — see the county's restriction map."},
 "Garfield County": {"stage": "Stage 1", "url": "https://www.garfieldcountyco.gov/emergency-management/fire-restrictions/",
   "note": "Joint county/BLM/fire-district Stage 1 since 6/10/2026; exceptional drought."},
}
VERIFIED_ON = "2026-07-02"
MUNICIPAL = {
 "Denver County": "https://www.denvergov.org",
 "Broomfield County": "https://www.broomfield.org",
}
# Plains / SLV counties with no order reported as of late June 2026 — NOT
# re-verified daily; shipped as unverified None, not "confirmed".
NONE_UNVERIFIED = {"Bent", "Cheyenne", "Crowley", "Kiowa", "Logan", "Morgan", "Otero",
                   "Phillips", "Prowers", "Sedgwick", "Weld", "Alamosa", "Conejos"}
FLOOR_URL = DFPC_URL
FLOOR_NOTE = "Level never read from an official source — treat “Stage 1” as a conservative floor and check before burning."

def build_counties(counties, demo=False):
    out = {}
    demo_s1 = {"Larimer County", "El Paso County", "Teller County"}; demo_s2 = {"Pueblo County"}
    for f in counties["features"]:
        nm = f["properties"]["NAME"]; base = nm[:-7] if nm.endswith(" County") else nm
        if demo:
            stage = "Stage 2" if nm in demo_s2 else ("Stage 1" if nm in demo_s1 else "None")
            out[nm] = {"stage": stage, "verified": True, "floor": False, "redFlagAuto": False,
                       "kind": "county", "url": FLOOR_URL, "verified_on": "SIMULATED", "note": ""}
            continue
        rf = base in RF_AUTO
        if nm in MUNICIPAL:
            out[nm] = {"stage": "Unknown", "verified": False, "floor": False, "redFlagAuto": False,
                       "kind": "municipal", "url": MUNICIPAL[nm], "verified_on": None, "note": ""}
            continue
        if nm in VERIFIED:
            v = VERIFIED[nm]
            entry = {"stage": v["stage"], "verified": True, "floor": False, "redFlagAuto": rf,
                     "kind": "county", "url": v["url"], "verified_on": VERIFIED_ON, "note": v.get("note", "")}
            if SCRAPE:
                st = parse_stage(fetch(v["url"]))
                REPORT["counties"][nm] = st or "MISS"
                if st:
                    entry["stage"] = st; entry["verified_on"] = TODAY
                else:
                    REPORT["misses"].append("county: " + nm)
            out[nm] = entry
        elif base in NONE_UNVERIFIED:
            out[nm] = {"stage": "None", "verified": False, "floor": False, "redFlagAuto": rf,
                       "kind": "county", "url": FLOOR_URL, "verified_on": None,
                       "note": "No county order reported as of late June 2026 — not re-verified; check before burning."}
        else:
            out[nm] = {"stage": "Stage 1", "verified": False, "floor": True, "redFlagAuto": rf,
                       "kind": "county", "url": FLOOR_URL, "verified_on": None, "note": FLOOR_NOTE}
    return out

def main():
    counties = json.load(open(os.path.join(HERE, "co_counties_all.geojson")))
    rules = open(os.path.join(HERE, "rules.js")).read()
    usfs = json.loads(json.dumps(USFS_STATUS))  # deep copy
    if DEMO:
        for code, d in usfs.items():
            d["stage"] = "Stage 1" if code in ("021005", "021209") else "None"
            d["verified"] = True; d["checked"] = "SIMULATED"
    elif SCRAPE:
        globals()["USFS_STATUS"] = usfs  # scrape mutates the copy
        scrape_forests()
    county = build_counties(counties, demo=DEMO)

    n_verified = sum(1 for v in county.values() if v["verified"])
    n_floor = sum(1 for v in county.values() if v.get("floor"))
    usfs_note = ("SIMULATED" if DEMO else
                 ("scraped %s; baked fallback %s" % (TODAY, USFS_BAKED_ASOF) if SCRAPE
                  else "hand-verified %s" % USFS_BAKED_ASOF))
    county_note = ("SIMULATED calm day" if DEMO else
                   "%d counties verified from official pages (%s); %d shown as an unverified “at least Stage 1” floor"
                   % (n_verified, TODAY if SCRAPE else VERIFIED_ON, n_floor))
    meta = {"build_date": TODAY, "usfs_note": usfs_note, "county_note": county_note,
            "usfs_baked_asof": USFS_BAKED_ASOF,
            "county_checked": TODAY if SCRAPE else VERIFIED_ON,
            "county_counts": {"verified": n_verified, "floor": n_floor}}

    T = open(os.path.join(HERE, "map_template3.html")).read()
    html = (T.replace("__RULES__", rules)
             .replace("__DEMO__", "true" if DEMO else "false")
             .replace("__USFS__", json.dumps(usfs, indent=1))
             .replace("__COUNTY__", json.dumps(county, indent=1))
             .replace("__COUNTIES__", json.dumps(counties))
             .replace("__META__", json.dumps(meta)))
    assert "FireRules" in html, "rules.js was not inlined"
    # __RULES__ excluded: the inlined rules.js header comment mentions it literally
    for ph in ("__USFS__", "__COUNTY__", "__COUNTIES__", "__META__", "__DEMO__"):
        assert ph not in html, "placeholder %s not replaced" % ph
    out = "Example_calm_day.html" if DEMO else "index.html"
    open(os.path.join(HERE, out), "w").write(html)
    json.dump(REPORT, open(os.path.join(HERE, "_build_report.json"), "w"), indent=1)
    print("wrote", out, len(html), "bytes | USFS districts:", len(usfs), "| counties:", len(county))
    if REPORT["misses"] or REPORT["errors"]:
        print("!! scrape problems (published with honest 'unverified' marks):")
        for m in REPORT["misses"]: print("   MISS:", m)
        for e in REPORT["errors"][:20]: print("   ERR:", e)

if __name__ == "__main__":
    main()
