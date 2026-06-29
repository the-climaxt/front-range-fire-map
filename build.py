#!/usr/bin/env python3
"""
Colorado Fire Map — single builder (live site, auto-publisher, and example).

  python build.py              -> index.html (live data; re-scrapes forest/county pages)
  python build.py --no-scrape  -> index.html using the baked current values (no network)
  python build.py --demo       -> Example_calm_day.html (simulated calm day)

Reads map_template3.html + co_counties_all.geojson from this folder.
BLM and Red Flag Warnings are fetched live in the browser, so they never need rebuilding.
"""
import json, os, re, sys, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRAPE = ("--no-scrape" not in sys.argv) and ("--demo" not in sys.argv)
DEMO = "--demo" in sys.argv
UA = {"User-Agent": "ColoradoFireMap/1.0 (+github pages; public-safety info)"}

def fetch(url, timeout=20):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:
        print("  fetch failed:", url, "->", e); return ""

def parse_stage(html):
    """Return a stage only when a current 'in effect' phrase is found; else None."""
    t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", html)).lower()
    inq = r"(in effect|in place|implemented|are in effect|now in effect)"
    if re.search(r"stage\s*(3|iii)\b[^.]{0,80}"+inq, t): return "Stage 3"
    if re.search(r"stage\s*(2|ii)\b[^.]{0,80}"+inq, t): return "Stage 2"
    if re.search(r"stage\s*(1|i)\b[^.]{0,80}"+inq, t): return "Stage 1"
    if re.search(r"no current fire restriction|no fire restrictions are|fire restrictions[^.]{0,20}lifted|no active fire restriction", t): return "None"
    return None

# ---- Forests: slug + whether one forest-wide stage applies + pages to scrape ----
FORESTS = {
 "Arapaho-Roosevelt NF": {"slug":"arp","uniform":False},   # per-district (Sulphur differs) -> not auto-overridden
 "Pike-San Isabel NF":   {"slug":"psicc","uniform":True},
 "White River NF":       {"slug":"whiteriver","uniform":True},
 "GMUG NF":              {"slug":"gmug","uniform":True},
 "Rio Grande NF":        {"slug":"riogrande","uniform":True},
 "San Juan NF":          {"slug":"sanjuan","uniform":True},
 "Medicine Bow-Routt NF":{"slug":"mbrtb","uniform":True},
}
def D(name, stage, counties, forest): return {"name":name,"stage":stage,"counties":counties,"forest":forest}
USFS_STATUS = {
 # Arapaho-Roosevelt
 "021005":D("Canyon Lakes Ranger District","Stage 1","Larimer","Arapaho-Roosevelt NF"),
 "021001":D("Boulder Ranger District","Stage 1","Boulder, Gilpin","Arapaho-Roosevelt NF"),
 "021007":D("Clear Creek Ranger District","Stage 1","Clear Creek, Jefferson, Gilpin","Arapaho-Roosevelt NF"),
 "021008":D("Sulphur Ranger District","None","Grand","Arapaho-Roosevelt NF"),
 "021006":D("Pawnee National Grassland","Stage 1","Weld","Arapaho-Roosevelt NF"),
 # Pike-San Isabel
 "021202":D("Salida Ranger District","Stage 1","Chaffee, Fremont, Saguache, Lake","Pike-San Isabel NF"),
 "021201":D("Leadville Ranger District","Stage 1","Lake, Chaffee, Park, Eagle, Summit","Pike-San Isabel NF"),
 "021209":D("Pikes Peak Ranger District","Stage 1","El Paso, Teller","Pike-San Isabel NF"),
 "021210":D("South Park Ranger District","Stage 1","Park, Jefferson","Pike-San Isabel NF"),
 "021211":D("South Platte Ranger District","Stage 1","Jefferson, Douglas, Teller, Park, Clear Creek","Pike-San Isabel NF"),
 "021203":D("San Carlos Ranger District","Stage 1","Custer, Fremont, Pueblo, Huerfano, Las Animas, Costilla, Saguache","Pike-San Isabel NF"),
 "021206":D("Comanche National Grassland","Stage 1","Baca, Las Animas, Otero","Pike-San Isabel NF"),
 # White River
 "021502":D("Blanco Ranger District","Stage 1","Rio Blanco, Garfield","White River NF"),
 "021501":D("Aspen Ranger District","Stage 1","Pitkin, Gunnison","White River NF"),
 "021510":D("Dillon Ranger District","Stage 1","Summit","White River NF"),
 "021503":D("Sopris Ranger District","Stage 1","Garfield, Pitkin, Eagle","White River NF"),
 "021504":D("Eagle-Holy Cross Ranger District","Stage 1","Eagle","White River NF"),
 "021507":D("Holy Cross Ranger District","Stage 1","Eagle, Lake","White River NF"),
 "021508":D("Rifle Ranger District","Stage 1","Garfield, Rio Blanco","White River NF"),
 # GMUG
 "020402":D("Grand Valley Ranger District","Stage 1","Mesa","GMUG NF"),
 "020405":D("Norwood Ranger District","Stage 1","San Miguel, Montrose","GMUG NF"),
 "020406":D("Ouray Ranger District","Stage 1","Ouray, Montrose","GMUG NF"),
 "020407":D("Gunnison Ranger District","Stage 1","Gunnison, Hinsdale, Saguache","GMUG NF"),
 "020408":D("Paonia Ranger District","Stage 1","Delta, Gunnison","GMUG NF"),
 # Rio Grande
 "020903":D("Conejos Peak Ranger District","Stage 1","Conejos, Archuleta, Rio Grande","Rio Grande NF"),
 "020904":D("Divide Ranger District","Stage 1","Mineral, Rio Grande, Hinsdale","Rio Grande NF"),
 "020907":D("Saguache Ranger District","Stage 1","Saguache","Rio Grande NF"),
 # San Juan
 "021308":D("Columbine Ranger District","Stage 1","La Plata, San Juan, Hinsdale","San Juan NF"),
 "021305":D("Mancos-Dolores Ranger District","Stage 1","Montezuma, Dolores, La Plata","San Juan NF"),
 "021306":D("Pagosa Ranger District","Stage 1","Archuleta, Hinsdale, Mineral","San Juan NF"),
 # Medicine Bow-Routt (Colorado districts)
 "020601":D("Yampa Ranger District","Stage 1","Routt, Garfield, Eagle","Medicine Bow-Routt NF"),
 "020603":D("Hahns Peak-Bears Ears Ranger District","Stage 1","Routt, Moffat, Jackson","Medicine Bow-Routt NF"),
 "020604":D("Parks Ranger District","Stage 1","Jackson, Grand, Larimer","Medicine Bow-Routt NF"),
}
USFS_AS_OF = "June 2026 (forest order pages)"

def scrape_forests():
    """Best-effort: refresh each uniform forest's stage from its official page."""
    cache={}
    for fk,info in FORESTS.items():
        if not info["uniform"]: continue
        sl=info["slug"]; stage=None
        for path in ("fire/fire-restrictions","alerts/fire-restrictions","alerts"):
            stage=parse_stage(fetch("https://www.fs.usda.gov/r02/%s/%s"%(sl,path)))
            if stage: break
        cache[fk]=stage
    for code,d in USFS_STATUS.items():
        st=cache.get(d["forest"])
        if st: d["stage"]=st
    print("  forest scrape:", {k:v for k,v in cache.items() if v})

# ---- Counties ----
COEMERG="http://www.coemergency.com/p/fire-bans-danger.html"
NONE_BASE={"Bent","Cheyenne","Crowley","Denver","Kiowa","Logan","Morgan","Otero","Phillips","Prowers","Sedgwick","Weld"}
CONDITIONAL_BASE={"Alamosa","Conejos"}
RF_AUTO={"Jefferson","Douglas","Alamosa","Conejos","Costilla","Eagle"}
CONFIRMED={  # read from each county's own order page
 "Jefferson County":{"stage":"Stage 1","url":"https://www.jeffcosheriffco.gov/safety/wildland-fire/fire-restrictions"},
 "Douglas County":{"stage":"None","url":"https://dcsheriff.net/sheriffs-office/divisions/emergency-management/fire-restrictions/"},
 "Chaffee County":{"stage":"Stage 2","url":"https://chaffeecounty.org/departments/sheriff/fire_restrictions.php"},
 "Summit County":{"stage":"Stage 2","url":"https://www.summitcountyco.gov/1220/Fire-Restrictions"},
}

def build_counties(counties, demo=False):
    out={}
    s1={"Larimer County","El Paso County","Teller County"}; s2={"Pueblo County"}
    for f in counties["features"]:
        nm=f["properties"]["NAME"]; base=nm[:-7] if nm.endswith(" County") else nm
        if demo:
            stage="Stage 2" if nm in s2 else ("Stage 1" if nm in s1 else "None")
            out[nm]={"stage":stage,"confirmed":True,"redFlagAuto":False,"url":COEMERG}; continue
        rf=base in RF_AUTO
        if nm in CONFIRMED: stage,conf,url=CONFIRMED[nm]["stage"],True,CONFIRMED[nm]["url"]
        elif base in NONE_BASE or base in CONDITIONAL_BASE: stage,conf,url="None",True,COEMERG
        else: stage,conf,url="Stage 1",False,COEMERG
        if SCRAPE and nm in CONFIRMED:
            st=parse_stage(fetch(CONFIRMED[nm]["url"]))
            if st: stage,conf=st,True
        out[nm]={"stage":stage,"confirmed":conf,"redFlagAuto":rf,"url":url}
    return out

def main():
    counties=json.load(open(os.path.join(HERE,"co_counties_all.geojson")))
    usfs=json.loads(json.dumps(USFS_STATUS))  # copy
    if DEMO:
        for code,d in usfs.items(): d["stage"]= "Stage 1" if code in ("021005","021209") else "None"
    elif SCRAPE:
        scrape_forests()
    county=build_counties(counties, demo=DEMO)
    meta={"usfs_as_of": "SIMULATED" if DEMO else USFS_AS_OF,
          "county_as_of": "SIMULATED calm day" if DEMO else ("auto-checked "+datetime.date.today().isoformat()),
          "build_date": datetime.date.today().isoformat()}
    T=open(os.path.join(HERE,"map_template3.html")).read()
    html=(T.replace("__DEMO__","true" if DEMO else "false")
           .replace("__USFS__",json.dumps(usfs,indent=2))
           .replace("__COUNTY__",json.dumps(county,indent=1))
           .replace("__COUNTIES__",json.dumps(counties))
           .replace("__META__",json.dumps(meta)))
    out = "Example_calm_day.html" if DEMO else "index.html"
    open(os.path.join(HERE,out),"w").write(html)
    print("wrote",out,len(html),"bytes | USFS districts:",len(usfs),"| counties:",len(county))

if __name__=="__main__": main()
