#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Taichung EMS map JSON from official open data and the fire department website.

Never invent coordinates. If a point cannot be matched to official open-data
coordinates or reliably geocoded from an official name/address, omit lat/lng
and record it under missing_coordinates.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/workspace/taichung-map")
DATA = ROOT / "data"
RAW = Path("/tmp/taichung-raw")
DATA.mkdir(parents=True, exist_ok=True)

RETRIEVED = "2026-11-24"
TIMEZONE = "Asia/Taipei"
UA = "taichung-ems-map/1.0 (public-safety prototype; +https://github.com/westlifeterry-beep)"

TC_BOX = (23.85, 24.45, 120.45, 121.40)  # south, north, west, east

STATION_PAGE = "https://www.fire.taichung.gov.tw/content/index.asp?Parser=7,3,101,21"
STATION_DATASET = "https://data.gov.tw/dataset/99643"
STATION_CSV_API = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=94c9a8b2-ad68-4062-8524-43686fdcadaa"
HOSPITAL_DATASET = "https://data.gov.tw/dataset/83756"
HOSPITAL_CSV_API = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=d254ce32-ef55-464b-92f4-9d0f9f8c14a1"
MOHW_LIST = "https://www.mohw.gov.tw/dl-97025-23d029a4-14c2-4ae9-a057-7a32d3885839.html"
AED_DATASET = "https://data.gov.tw/dataset/12063"
AED_CSV = "https://tw-aed.mohw.gov.tw/openData?t=csv"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def norm_addr(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("台", "臺")
    s = s.replace(" ", "").replace("　", "")
    s = s.replace("－", "-").replace("–", "-")
    s = re.sub(r"[，,。\.]", "", s)
    if s.startswith("臺中市"):
        s = s[3:]
    return s


def addr_key(s: str) -> str:
    """Compare addresses ignoring city prefix and floor suffixes after 號."""
    s = norm_addr(s)
    s = re.sub(r"(\d+)號.*$", r"\1號", s)
    return s


def clean_phone(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    parts = re.findall(r"0\d-\d{8}", s)
    return "、".join(parts) if parts else s


def kind_of(name: str) -> str:
    if "高級救護隊" in name or "專責救護隊" in name:
        return "高級救護隊"
    if "搜救犬" in name:
        return "搜救犬隊"
    if "特搜" in name:
        return "特搜大隊"
    if name.endswith("大隊") or "救災救護大隊" in name:
        return "大隊"
    if "分隊" in name:
        return "分隊"
    if "消防局" in name:
        return "消防局本部"
    return "其他"


def in_box(lat: float, lng: float) -> bool:
    s, n, w, e = TC_BOX
    return s <= lat <= n and w <= lng <= e


def district_of(addr: str) -> str:
    addr = (addr or "").replace("台", "臺")
    m = re.search(r"臺中市([東西南南北中]區|[^\s市]{1,3}區)", addr)
    if m:
        return m.group(1)
    m = re.search(r"([東西南南北中]區|[^\s市]{2,3}區)", addr)
    return m.group(1) if m else ""


def clean_text(html_frag: str) -> str:
    t = re.sub(r"<br\s*/?>", " ", html_frag, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_official_stations(html: str) -> list[dict]:
    items = []
    blocks = re.findall(r'<li class="list_date">([\s\S]*?)</li>', html, flags=re.I)
    for block in blocks:
        def field(label: str) -> str:
            m = re.search(
                rf'data-th="\s*{re.escape(label)}:"[^>]*>([\s\S]*?)</span>',
                block,
                flags=re.I,
            )
            return clean_text(m.group(1)) if m else ""

        name = field("單位")
        phone = clean_phone(field("市內電話"))
        fax = clean_phone(field("傳真電話"))
        address = ""
        m = re.search(r"geocode=&q=([^\"&]+)", block)
        if m:
            address = urllib.parse.unquote(m.group(1)).strip()
        if not address:
            m = re.search(r'<a[^>]*href="[^"]*maps\.google[^"]*"[^>]*>([^<]+)', block)
            if m:
                address = clean_text(m.group(1))
        if not name or not address:
            continue
        if not address.startswith("臺中市") and not address.startswith("台中市"):
            full = f"臺中市{address}"
        else:
            full = address.replace("台中市", "臺中市")
        items.append(
            {
                "name": name,
                "phone": phone,
                "fax": fax,
                "address": full,
                "address_raw": address,
            }
        )
    return items


def load_opendata_stations() -> list[dict]:
    raw = (RAW / "fs-94c9a8b2-ad68-4062-8524-43686fdcadaa.bin").read_bytes()
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        try:
            lat = float(r["緯度"])
            lng = float(r["經度"])
        except (TypeError, ValueError, KeyError):
            continue
        addr = (r.get("地址") or "").strip()
        out.append(
            {
                "name": (r.get("名稱") or "").strip(),
                "address": addr if addr.startswith("臺中市") or addr.startswith("台中市") else f"臺中市{addr}",
                "address_raw": addr,
                "phone": (r.get("電話") or "").strip(),
                "lat": lat,
                "lng": lng,
            }
        )
    return out


def nominatim_search(query: str, limit: int = 5, pause: float = 1.1) -> list[dict]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(limit),
        "countrycodes": "tw",
        "addressdetails": "1",
    }
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    time.sleep(pause)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return [{"error": f"HTTP {e.code}", "query": query}]
    except Exception as e:
        return [{"error": str(e), "query": query}]
    out = []
    for hit in data or []:
        try:
            lat = float(hit["lat"])
            lng = float(hit["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            {
                "lat": lat,
                "lng": lng,
                "display_name": hit.get("display_name"),
                "osm_type": hit.get("osm_type"),
                "osm_id": hit.get("osm_id"),
                "category": hit.get("category") or hit.get("class"),
                "type": hit.get("type"),
                "name": hit.get("name"),
                "query": query,
                "in_box": in_box(lat, lng),
            }
        )
    return out


def pick_same_address(official_name: str, cands: list[dict]) -> dict:
    for c in cands:
        if c["name"] == official_name:
            return c
        if c["name"].replace("救災救護", "") == official_name:
            return c
        if official_name.replace("高級救護隊", "") and official_name in ("葫蘆墩高級救護隊",) and "豐原" in c["name"]:
            return c
    return cands[0]


def match_station_coords(official: list[dict], opendata: list[dict]) -> tuple[list[dict], list[dict]]:
    by_addr: dict[str, list[dict]] = defaultdict(list)
    for r in opendata:
        by_addr[addr_key(r["address_raw"] or r["address"])].append(r)

    results = []
    missing = []
    for o in official:
        rec = {
            "name": o["name"],
            "kind": kind_of(o["name"]),
            "address": o["address"],
            "phone": o["phone"],
            "fax": o["fax"],
            "highlight": o["name"] == "大雅分隊",
            "address_source": "臺中市政府消防局「各大隊、分隊聯絡」網頁",
            "address_source_url": STATION_PAGE,
            "address_page_updated": "2023-06-15 11:28:00",
        }
        key = addr_key(o["address_raw"] or o["address"])
        cands = by_addr.get(key, [])
        if cands:
            pick = pick_same_address(o["name"], cands)
            rec["lat"] = pick["lat"]
            rec["lng"] = pick["lng"]
            rec["coord_source"] = (
                "臺中市政府消防局「107年臺中市各消防分隊分布點位」開放資料，依現行官網地址比對取得（忽略樓層後綴）"
            )
            rec["coord_source_url"] = STATION_DATASET
            rec["coord_match"] = "address"
            rec["opendata_name"] = pick["name"]
            rec["opendata_address"] = pick["address"]
            results.append(rec)
            continue
        rec["missing_reason"] = (
            "官網現行地址與「107年臺中市各消防分隊分布點位」不符；未採用舊址座標，"
            "也未在 OpenStreetMap Nominatim 找到可確認的新址門牌點，故暫不標點，以免標錯位置。"
        )
        missing.append({k: rec[k] for k in ("name", "address", "phone", "missing_reason")})
        results.append(rec)

    official_names = {x["name"] for x in official}
    for r in opendata:
        if "消防局" in r["name"] and "分隊" not in r["name"] and r["name"] not in official_names:
            results.append(
                {
                    "name": r["name"],
                    "kind": "消防局本部",
                    "address": r["address"],
                    "phone": r["phone"],
                    "fax": "",
                    "highlight": False,
                    "lat": r["lat"],
                    "lng": r["lng"],
                    "address_source": "臺中市政府消防局「107年臺中市各消防分隊分布點位」開放資料",
                    "address_source_url": STATION_DATASET,
                    "coord_source": "臺中市政府消防局「107年臺中市各消防分隊分布點位」開放資料",
                    "coord_source_url": STATION_DATASET,
                    "coord_match": "opendata_only",
                    "note": "此筆未出現在「各大隊、分隊聯絡」表，名稱、地址、座標均來自開放資料",
                }
            )
            break
    return results, missing


def load_hospitals() -> list[dict]:
    raw = (RAW / "hospitals.csv").read_bytes()
    text = raw.decode("utf-8-sig").lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        level = (r.get("能力分級") or "").strip()
        out.append(
            {
                "id": (r.get("醫事機構代碼") or "").strip(),
                "name": (r.get("醫院名稱") or "").strip(),
                "zip": (r.get("郵遞區號") or "").strip(),
                "address": (r.get("地址") or "").strip(),
                "level": level,
                "level_group": (
                    "重度級" if level.startswith("重度")
                    else "中度級" if "中度" in level
                    else "一般級" if "一般" in level
                    else level
                ),
            }
        )
    return out


def hospital_queries(name: str, address: str) -> list[str]:
    qs = [name]
    # Drop legal-entity prefix to help Nominatim
    short = re.sub(r"^.*?法人", "", name)
    if short and short != name:
        qs.append(short)
    if "向上院區" in name:
        qs.extend(["光田綜合醫院向上院區", "光田醫院向上院區", "光田綜合醫院 沙鹿"])
    if "大甲院區" in name:
        qs.extend(["光田綜合醫院大甲院區", "光田醫院大甲院區", "光田綜合醫院 大甲"])
    if "中港分院" in name:
        qs.extend(["澄清綜合醫院中港分院", "中港澄清醫院"])
    if name == "澄清綜合醫院":
        qs.extend(["澄清綜合醫院 平等", "平等澄清醫院"])
    if "童綜合" in name:
        qs.extend(["童綜合醫院梧棲院區", "童綜合醫院 梧棲"])
    if "國軍臺中總醫院附設民眾診療服務處" == name:
        qs.extend(["國軍臺中總醫院", "國軍台中總醫院 太平"])
    if "中清分院" in name:
        qs.extend(["國軍臺中總醫院中清分院", "國軍台中總醫院中清分院"])
    if "臺中市立老人復健綜合醫院" in name:
        qs.extend(["臺中市立老人復健綜合醫院", "中國醫藥大學附設醫院老人醫院"])
    if "東勢區農會附設農民醫院" in name:
        qs.append("東勢農民醫院")
    if "大甲李綜合" in name:
        qs.append("大甲李綜合醫院")
    if "大里仁愛" in name:
        qs.append("大里仁愛醫院")
    if "烏日林新" in name:
        qs.append("烏日林新醫院")
    if "林新醫療社團法人林新醫院" == name:
        qs.append("林新醫院")
    if "台中慈濟" in name or "臺中慈濟" in name:
        qs.append("台中慈濟醫院")
    # address as last resort
    qs.append(address)
    # unique preserve order
    seen = set()
    out = []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def is_hospital_hit(hit: dict) -> bool:
    cat = (hit.get("category") or "").lower()
    typ = (hit.get("type") or "").lower()
    name = hit.get("name") or ""
    if typ in {"bus_stop", "platform", "station", "route", "yes"} and cat in {"highway", "public_transport", "railway", "route"}:
        return False
    if typ in {"hospital", "clinic"}:
        return True
    if cat in {"amenity", "healthcare"} and typ in {"hospital", "clinic", "doctors"}:
        return True
    if cat == "building" and typ in {"hospital", "yes"} and ("醫院" in name or "Hospital" in name):
        return True
    return False


def geocode_hospitals(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    missing = []
    results = []
    for r in rows:
        rec = dict(r)
        rec["address_source"] = "臺中市政府衛生局「臺中市急救責任醫院」開放資料（檔名：急救責任醫院1141229.CSV）"
        rec["address_source_url"] = HOSPITAL_DATASET
        rec["classification_source"] = "同上開放資料之「能力分級」欄；衛福部急救責任醫院分區名單可對照"
        rec["classification_source_url"] = MOHW_LIST
        district = district_of(rec["address"])
        chosen = None
        attempts = []
        for q in hospital_queries(rec["name"], rec["address"]):
            hits = nominatim_search(q)
            if hits and hits[0].get("error"):
                attempts.append({"query": q, "error": hits[0]["error"]})
                continue
            attempts.append({"query": q, "hits": [
                {k: h[k] for k in ("lat", "lng", "display_name", "category", "type", "name", "in_box") if k in h}
                for h in hits
            ]})
            for h in hits:
                if not h.get("in_box"):
                    continue
                display = (h.get("display_name") or "").replace("台", "臺")
                if district and district not in display:
                    continue
                if is_hospital_hit(h) or q == rec["address"]:
                    # For raw address hits, still require in-box + district, already checked.
                    if q == rec["address"] and not is_hospital_hit(h):
                        # Accept a geocoded official address only if it is a building/place in the right district.
                        if (h.get("category") or "") in {"highway", "public_transport"}:
                            continue
                    chosen = h
                    break
            if chosen:
                break
        rec["geocode_attempts"] = [
            {"query": a["query"], "error": a.get("error"), "hit_count": len(a.get("hits") or [])}
            for a in attempts
        ]
        if chosen:
            rec["lat"] = chosen["lat"]
            rec["lng"] = chosen["lng"]
            rec["coord_source"] = (
                f"依衛生局開放資料之醫院名稱或地址，於 {RETRIEVED} 以 OpenStreetMap Nominatim 查得，"
                f"並確認落在臺中範圍且行政區與官方地址相符"
            )
            rec["coord_source_url"] = "https://nominatim.openstreetmap.org/"
            rec["coord_match"] = chosen.get("query")
            rec["coord_display_name"] = chosen.get("display_name")
            rec["coord_osm"] = f"{chosen.get('osm_type')}/{chosen.get('osm_id')}"
            results.append(rec)
        else:
            rec["missing_reason"] = "開放資料僅有地址、沒有座標，Nominatim 查詢結果無法確認與官方地址同一行政區的醫院點位"
            missing.append({k: rec[k] for k in ("id", "name", "address", "level_group", "missing_reason")})
            results.append(rec)
        print("HOSP", rec["name"], "OK" if "lat" in rec else "MISS", rec.get("coord_display_name", rec.get("missing_reason")))
    return results, missing


def load_aeds() -> dict:
    text = (RAW / "aed-opendata.csv").read_text("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    items = []
    skipped_no_coord = 0
    skipped_out_of_box = 0
    for r in rows:
        city = (r.get("場所縣市") or "").strip().replace("台", "臺")
        if city != "臺中市":
            continue
        try:
            lat = float(r["地點LAT"])
            lng = float(r["地點LNG"])
        except (TypeError, ValueError, KeyError):
            skipped_no_coord += 1
            continue
        if not in_box(lat, lng):
            skipped_out_of_box += 1
            continue
        items.append(
            {
                "id": (r.get("AEDID") or r.get("場所ID") or "").strip(),
                "place_id": (r.get("場所ID") or "").strip(),
                "name": (r.get("場所名稱") or "").strip(),
                "district": (r.get("場所區域") or "").strip(),
                "address": (r.get("場所地址") or "").strip(),
                "category": (r.get("場所分類") or "").strip(),
                "type": (r.get("場所類型") or "").strip(),
                "location": (r.get("AED放置地點") or "").strip(),
                "location_note": (r.get("AED地點描述") or "").strip(),
                "hours_note": (r.get("開放使用時間備註") or "").strip(),
                "phone": (r.get("開放時間緊急連絡電話") or "").strip(),
                "weekday": f"{(r.get('周一至周五起') or '').strip()}–{(r.get('周一至周五迄') or '').strip()}".strip("–"),
                "lat": lat,
                "lng": lng,
            }
        )
    return {
        "generated_at": RETRIEVED,
        "timezone": TIMEZONE,
        "source": "衛生福利部醫事司「公共場所AED位置資訊」（政府資料開放平臺資料集 12063，每日自動更新）",
        "source_url": AED_DATASET,
        "download_url": AED_CSV,
        "retrieved_at": RETRIEVED,
        "filter": "場所縣市為臺中市或台中市，且座標落在台中概略範圍內",
        "national_row_count": len(rows),
        "count": len(items),
        "skipped_no_coord": skipped_no_coord,
        "skipped_out_of_box": skipped_out_of_box,
        "items": items,
    }


def main() -> None:
    station_html = (RAW / "fire-stations-page.html").read_text("utf-8")
    official = parse_official_stations(station_html)
    opendata = load_opendata_stations()
    if len(official) < 50:
        raise SystemExit(f"failed to parse official station list, got {len(official)}")
    stations, st_missing = match_station_coords(official, opendata)

    hospitals_raw = load_hospitals()
    hospitals, h_missing = geocode_hospitals(hospitals_raw)
    aeds = load_aeds()

    stations_json = {
        "generated_at": RETRIEVED,
        "timezone": TIMEZONE,
        "source": "單位名稱、電話、現行地址：臺中市政府消防局「各大隊、分隊聯絡」網頁（頁面最後異動 2023-06-15 11:28:00，擷取於 2026-11-24）。座標優先依地址（忽略樓層後綴）比對「107年臺中市各消防分隊分布點位」開放資料；地址已變更且無法確認新址座標者，不標點。",
        "source_urls": {
            "official_contact_page": STATION_PAGE,
            "opendata_dataset": STATION_DATASET,
            "opendata_csv": STATION_CSV_API,
        },
        "retrieved_at": RETRIEVED,
        "official_unit_count": len(official),
        "opendata_point_count": len(opendata),
        "count": len(stations),
        "with_coordinates": sum(1 for s in stations if "lat" in s),
        "missing_coordinates": st_missing,
        "notes": [
            "開放資料標題為「107年」，屬較舊的點位，故只在現行官網地址與開放資料地址相符時才沿用該座標。",
            "大里分隊與國光分隊在開放資料與現行官網的地址對調，已改依地址而非依名稱配對。",
            "同一地址可能同時有大隊部與分隊（或高級救護隊），地圖上會重疊，屬真實共址，不會人為偏移座標。",
        ],
        "items": stations,
    }
    hospitals_json = {
        "generated_at": RETRIEVED,
        "timezone": TIMEZONE,
        "source": "臺中市政府衛生局「臺中市急救責任醫院」開放資料（急救責任醫院1141229.CSV）。該檔沒有座標，本頁座標是 2026-11-24 以 Nominatim 依官方醫院名稱或地址查得，並檢查行政區是否相符。能力分級以該檔為準。",
        "source_urls": {
            "opendata_dataset": HOSPITAL_DATASET,
            "opendata_csv": HOSPITAL_CSV_API,
            "mohw_regional_list": MOHW_LIST,
        },
        "retrieved_at": RETRIEVED,
        "count": len(hospitals),
        "with_coordinates": sum(1 for h in hospitals if "lat" in h),
        "by_level": dict(Counter(h["level_group"] for h in hospitals)),
        "missing_coordinates": h_missing,
        "items": hospitals,
    }

    (DATA / "stations.json").write_text(json.dumps(stations_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "hospitals.json").write_text(json.dumps(hospitals_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "aeds.json").write_text(json.dumps(aeds, ensure_ascii=False), encoding="utf-8")
    sources = {
        "generated_at": RETRIEVED,
        "timezone": TIMEZONE,
        "layers": {
            "stations": {
                "file": "data/stations.json",
                "count": stations_json["count"],
                "with_coordinates": stations_json["with_coordinates"],
                "missing_coordinates": st_missing,
                "sources": stations_json["source_urls"],
            },
            "hospitals": {
                "file": "data/hospitals.json",
                "count": hospitals_json["count"],
                "with_coordinates": hospitals_json["with_coordinates"],
                "by_level": hospitals_json["by_level"],
                "missing_coordinates": h_missing,
                "sources": hospitals_json["source_urls"],
            },
            "aeds": {
                "file": "data/aeds.json",
                "count": aeds["count"],
                "national_row_count": aeds["national_row_count"],
                "sources": {"dataset": AED_DATASET, "csv": AED_CSV},
            },
        },
    }
    (DATA / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    print("official stations", len(official))
    print("opendata stations", len(opendata))
    print("written stations", len(stations), "with coord", stations_json["with_coordinates"], "missing", len(st_missing))
    print("hospitals", len(hospitals), "with coord", hospitals_json["with_coordinates"], "missing", len(h_missing))
    print("aeds", aeds["count"], "national", aeds["national_row_count"])
    for s in stations:
        flag = "OK" if "lat" in s else "NO COORD"
        print(f"  [{flag}] {s['name']} | {s.get('address')} | {s.get('coord_match')} | {s.get('lat')},{s.get('lng')}")


if __name__ == "__main__":
    main()
