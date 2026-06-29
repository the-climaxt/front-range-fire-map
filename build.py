#!/usr/bin/env python3
"""
Auto-build the Colorado Fire Map. Run by the GitHub Action daily.
Reads map_template3.html + co_counties_all.geojson, re-checks each county's
official page for its CURRENT stage, and writes index.html.
BLM, USFS boundaries, and Red Flag Warnings are fetched live in the browser,
so they are always current without rebuilding.
"""
import json, os, re, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "ColoradoFireMap/1.0 (github action; contact via repo)"}

def fetch(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:
        print("  fetch failed:", url, e); return ""

def parse_stage(html):
    """Conservative heuristic: only return a stage when a current 'in effect' phrase is found."""
    t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", html)).lower()
    inq = r"(in effect|in place|implemented|are in effect|now in effect)"
    if re.search(r"stage\s*(3|iii)\b[^.]{0,70}"+inq, t) or re.search(inq+r"[^.]{0,40}stage\s*(3|iii)\b", t): return "Stage 3"
    if re.search(r"stage\s*(2|ii)\b[^.]{0,70}"+inq, t) or re.search(inq+r"[^.]{0,40}stage\s*(2|ii)\b", t): return "Stage 2"
    if re.search(r"stage\s*(1|i)\b[^.]{0,70}"+inq, t) or re.search(inq+r"[^.]{0,40}stage\s*(1|i)\b", t): return "Stage 1"
    if re.search(r"no current fire restriction|no fire restrictions are|fire restrictions[^.]{0,20}lifted|no active fire restriction|no current restriction", t): return "None"
    return None  # unknown -> keep floor

# ----- USFS forest orders (static; low churn). Edit here or extend scraper later. -----
AR_BOULDER="https://www.fs.usda.gov/r02/arp/alerts/stage-1-fire-restrictions-boulder-and-clear-creek-ranger-districts"
PSICC="https://www.fs.usda.gov/r02/psicc/alerts/psicc-stage-1-fire-restrictions"
USFS_STATUS={
 "021005":{"name":"Canyon Lakes Ranger District","stage":"Stage 1","counties":"Larimer","forest":"Arapaho-Roosevelt NF","order":"https://www.fs.usda.gov/r02/arp/alerts/stage-1-fire-restrictions-canyon-lakes-ranger-district"},
 "021001":{"name":"Boulder Ranger District","stage":"Stage 1","counties":"Boulder, Gilpin","forest":"Arapaho-Roosevelt NF","order":AR_BOULDER},
 "021007":{"name":"Clear Creek Ranger District","stage":"Stage 1","counties":"Clear Creek, Jefferson, Gilpin","forest":"Arapaho-Roosevelt NF","order":AR_BOULDER},
 "021008":{"name":"Sulphur Ranger District","stage":"None","counties":"Grand","forest":"Arapaho-Roosevelt NF","order":"https://www.fs.usda.gov/r02/arp/alerts/fire-restrictions"},
 "021006":{"name":"Pawnee National Grassland","stage":"Stage 1","counties":"Weld","forest":"Arapaho-Roosevelt NF","order":"https://www.fs.usda.gov/r02/arp/alerts/stage-1-fire-restrictions-pawnee-national-grassland"},
 "021201":{"name":"Leadville Ranger District","stage":"Stage 1","counties":"Lake, Chaffee, Park, Eagle, Summit","forest":"Pike-San Isabel NF","order":PSICC},
 "021202":{"name":"Salida Ranger District","stage":"Stage 1","counties":"Chaffee, Fremont, Saguache, Lake","forest":"Pike-San Isabel NF","order":PSICC},
 "021209":{"name":"Pikes Peak Ranger District","stage":"Stage 1","counties":"El Paso, Teller","forest":"Pike-San Isabel NF","order":PSICC},
 "021210":{"name":"South Park Ranger District","stage":"Stage 1","counties":"Park, Jefferson","forest":"Pike-San Isabel NF","order":PSICC},
 "021211":{"name":"South Platte Ranger District","stage":"Stage 1","counties":"Jefferson, Douglas, Teller, Park, Clear Creek","forest":"Pike-San Isabel NF","order":PSICC},
 "021203":{"name":"San Carlos Ranger District","stage":"Stage 1","counties":"Custer, Fremont, Pueblo, Huerfano, Las Animas, Costilla, Saguache","forest":"Pike-San Isabel NF","order":PSICC},
 "021206":{"name":"Comanche National Grassland","stage":"Stage 1","counties":"Baca, Las Animas, Otero","forest":"Pike-San Isabel NF","order":PSICC},
}
USFS_AS_OF="April 2026 (forest order pages)"

# ----- County setup: floor + redFlagAuto + page URL (specific where known). -----
COEMERG="http://www.coemergency.com/p/fire-bans-danger.html"
NONE_BASE={"Bent","Cheyenne","Crowley","Denver","Kiowa","Logan","Morgan","Otero","Phillips","Prowers","Sedgwick","Weld"}
CONDITIONAL_BASE={"Alamosa","Conejos"}
RF_AUTO={"Jefferson","Douglas","Alamosa","Conejos","Costilla","Eagle"}
# Specific county fire-restriction pages the scraper can read (add more over time):
COUNTY_URLS={
 "Jefferson County":"https://www.jeffcosheriffco.gov/safety/wildland-fire/fire-restrictions",
 "Douglas County":"https://dcsheriff.net/sheriffs-office/divisions/emergency-management/fire-restrictions/",
 "Chaffee County":"https://chaffeecounty.org/departments/sheriff/fire_restrictions.php",
 "Summit County":"https://www.summitcountyco.gov/1220/Fire-Restrictions",
}

counties = json.load(open(os.path.join(HERE,"co_counties_all.geojson")))
COUNTY_STATUS={}
for f in counties["features"]:
    nm=f["properties"]["NAME"]; base=nm[:-7] if nm.endswith(" County") else nm
    rf=base in RF_AUTO
    if base in NONE_BASE or base in CONDITIONAL_BASE: stage,conf="None",True
    else: stage,conf="Stage 1",False           # safe floor
    url=COUNTY_URLS.get(nm, COEMERG)
    # try to read the real current stage from the county's own page
    if nm in COUNTY_URLS:
        print("checking", nm)
        s=parse_stage(fetch(COUNTY_URLS[nm]))
        if s is not None: stage,conf=s,True
    COUNTY_STATUS[nm]={"stage":stage,"confirmed":conf,"redFlagAuto":rf,"url":url}

BUILD=datetime.date.today().isoformat()
T=open(os.path.join(HERE,"map_template3.html")).read()
html=(T.replace("__USFS__",json.dumps(USFS_STATUS,indent=2))
       .replace("__COUNTY__",json.dumps(COUNTY_STATUS,indent=1))
       .replace("__COUNTIES__",json.dumps(counties))
       .replace("__META__",json.dumps({"usfs_as_of":USFS_AS_OF,"county_as_of":"auto-checked "+BUILD,"build_date":BUILD})))
open(os.path.join(HERE,"index.html"),"w").write(html)
print("wrote index.html", len(html), "bytes; confirmed counties:", sum(1 for v in COUNTY_STATUS.values() if v["confirmed"]))
