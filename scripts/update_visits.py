#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from dedupe import dedupe_records


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "scripts" / "sources.json"
VISITS_PATH = ROOT / "public" / "data" / "visits.json"
USER_AGENT = "LeaderVisitNewsBot/1.0 (+public-news-daily-static-json)"
REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 1.0
MAX_ITEMS_PER_SOURCE = 30

KEYWORDS = [
    "访问", "出访", "抵达", "启程", "会见", "国事访问", "正式访问", "工作访问", "专机",
    "总统", "总理", "首相", "外交部长", "领导人",
    "visit", "official visit", "state visit", "working visit", "arrives", "departs", "meets",
    "president", "prime minister", "foreign minister", "special flight", "government aircraft",
    "summit", "conference", "bilateral meeting",
]

AIRCRAFT_TERMS = [
    "专机", "政府飞机", "抵达机场", "启程前往", "乘机", "special flight", "government aircraft",
    "aircraft", "arrived at the airport", "departed for", "air force",
]

EVENT_PATTERNS = [
    ("state_visit", re.compile(r"\bstate visit\b|国事访问", re.I)),
    ("official_visit", re.compile(r"\bofficial visit\b|正式访问", re.I)),
    ("working_visit", re.compile(r"\bworking visit\b|工作访问", re.I)),
    ("conference_attendance", re.compile(r"\bsummit\b|\bconference\b|出席.*会议|会议出席", re.I)),
    ("arrival", re.compile(r"\barriv(?:e|es|ed|al)\b|抵达", re.I)),
    ("departure", re.compile(r"\bdepart(?:s|ed|ure)?\b|启程|出访", re.I)),
    ("meeting", re.compile(r"\bmeet(?:s|ing)?\b|会见", re.I)),
]

TITLE_PATTERNS = [
    re.compile(r"(?P<title>President|Prime Minister|Premier|Foreign Minister|Secretary of State|Chancellor|King|Queen)\s+(?P<name>[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})", re.I),
    re.compile(r"(?P<name>[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3}),?\s+(?P<title>President|Prime Minister|Premier|Foreign Minister|Secretary of State|Chancellor)", re.I),
    re.compile(r"(?P<name>[\u4e00-\u9fff]{2,4})(?P<title>总统|总理|首相|外长|外交部长|主席|国家主席)"),
]

LEADER_ALIASES = {
    "donald trump": ("Donald Trump", "United States"),
    "emmanuel macron": ("Emmanuel Macron", "France"),
    "ferdinand marcos": ("Ferdinand Marcos Jr.", "Philippines"),
    "ferdinand bongbong marcos": ("Ferdinand Marcos Jr.", "Philippines"),
    "min aung hlaing": ("Min Aung Hlaing", "Myanmar"),
    "narendra modi": ("Narendra Modi", "India"),
    "to lam": ("To Lam", "Vietnam"),
    "tô lâm": ("Tô Lâm", "Vietnam"),
    "xi jinping": ("Xi Jinping", "China"),
    "习近平": ("习近平", "China"),
}

COUNTRY_PATTERNS = {
    "Canada": ("canada", "ottawa", "加拿大", "渥太华"),
    "China": ("china", "beijing", "中国", "北京"),
    "Czech Republic": ("czech republic", "prague", "捷克", "布拉格"),
    "France": ("france", "paris", "法国", "巴黎"),
    "India": ("india", "new delhi", "印度", "新德里"),
    "Japan": ("japan", "tokyo", "日本", "东京"),
    "Laos": ("laos", "vientiane", "老挝", "万象"),
    "Myanmar": ("myanmar", "naypyidaw", "缅甸", "内比都"),
    "North Korea": ("north korea", "pyongyang", "朝鲜", "平壤"),
    "Philippines": ("philippines", "manila", "菲律宾", "马尼拉"),
    "Saudi Arabia": ("saudi arabia", "riyadh", "沙特阿拉伯", "利雅得"),
    "South Africa": ("south africa", "pretoria", "南非", "比勒陀利亚"),
    "Thailand": ("thailand", "bangkok", "泰国", "曼谷"),
    "United Kingdom": ("united kingdom", "london", "英国", "伦敦"),
    "United States": ("united states", "washington", "美国", "华盛顿"),
    "Uzbekistan": ("uzbekistan", "tashkent", "乌兹别克斯坦", "塔什干"),
    "Vietnam": ("vietnam", "hanoi", "越南", "河内"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def plain_text(value: str) -> str:
    if not value:
        return ""
    if "<" not in value and ">" not in value:
        return normalize_space(value)
    return normalize_space(BeautifulSoup(value, "html.parser").get_text(" "))


def includes_keyword(text: str) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in KEYWORDS)


def parse_date(value: Any) -> str:
    if not value:
        return ""
    try:
        parsed = date_parser.parse(str(value))
    except (ValueError, TypeError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def infer_visit_date(text: str, published_at: str) -> str:
    if published_at:
        return published_at[:10]
    match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def infer_event_type(text: str) -> str:
    for event_type, pattern in EVENT_PATTERNS:
        if pattern.search(text):
            return event_type
    return "other"


def infer_leader(text: str) -> tuple[str, str]:
    lower_text = text.lower()
    for alias, (display_name, _) in LEADER_ALIASES.items():
        if alias in lower_text:
            title_match = re.search(r"\b(President|Prime Minister|Premier|Foreign Minister|Secretary of State|Chancellor|King|Queen)\b|总统|总理|首相|外长|外交部长|主席|国家主席", text, re.I)
            return display_name, normalize_space(title_match.group(0)) if title_match else ""

    for pattern in TITLE_PATTERNS:
        match = pattern.search(text)
        if match:
            name = normalize_space(match.group("name"))
            name = re.split(r"\b(?:and|with|meets|arrives|visits|to|will|during|on|for|in)\b", name, maxsplit=1, flags=re.I)[0].strip(" ,.-")
            return name, normalize_space(match.group("title"))
    return "", ""


def canonical_location(value: str) -> str:
    cleaned = normalize_space(value).strip(" .,-")
    lower = cleaned.lower()
    for country, terms in COUNTRY_PATTERNS.items():
        if any(term in lower for term in terms if term.isascii()):
            return country
        if any(term in cleaned for term in terms if not term.isascii()):
            return country
    return ""


def infer_destination(text: str) -> str:
    patterns = [
        r"\b(?:arrives? in|visits?|visit to|travel(?:s|led)? to|depart(?:s|ed)? for)\s+([A-Z][A-Za-z .'-]{2,24})",
        r"(?:访问|抵达|前往)([\u4e00-\u9fffA-Za-z .'-]{2,10})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_space(match.group(1))
            value = re.split(r"\b(?:for|to|on|and|during|as|from|,)\b|[，。；;:]", value)[0]
            return canonical_location(value)
    return ""


def infer_origin(text: str) -> str:
    patterns = [
        r"\b(?:from|depart(?:s|ed)? from|leaves?)\s+([A-Z][A-Za-z .'-]{2,32})",
        r"(?:从|离开)([\u4e00-\u9fffA-Za-z .'-]{2,16})(?:出发|启程|前往|抵达|访问)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = normalize_space(match.group(1))
            value = re.split(r"\b(?:for|to|on|and|during|as|,)\b|[，。；;:]", value)[0]
            return canonical_location(value)
    return ""


def infer_leader_country(leader_name: str, text: str, source_hint: str) -> str:
    lower_name = normalize_space(leader_name).lower()
    lower_text = text.lower()
    for alias, (_, country) in LEADER_ALIASES.items():
        if alias in lower_name or alias in lower_text:
            return country

    for country, terms in COUNTRY_PATTERNS.items():
        names = [term for term in terms if term.isascii()]
        if any(re.search(rf"\b{re.escape(term)}\b\s+(?:president|prime minister|premier|foreign minister|leader)", lower_text, re.I) for term in names):
            return country
        if any(re.search(rf"{re.escape(term)}(?:总统|总理|首相|外长|领导人|主席)", text) for term in terms if not term.isascii()):
            return country

    return "" if source_hint == "Global" else source_hint


def possibly_special_aircraft(text: str) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in AIRCRAFT_TERMS)


def make_id(source_url: str, leader_name: str, visit_date: str, title: str) -> str:
    basis = "|".join([source_url, leader_name, visit_date, title])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def can_fetch(url: str) -> bool:
    try:
        robots_url = urljoin(url, "/robots.txt")
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.read()
        return parser.can_fetch(USER_AGENT, url) or parser.can_fetch("*", url)
    except Exception:
        return True


def build_record(source: Dict[str, Any], title: str, summary: str, url: str, published: str) -> Optional[Dict[str, Any]]:
    clean_title = plain_text(title)
    clean_summary = plain_text(summary)
    if " - " in clean_title and source.get("name", "").startswith("Google News"):
        clean_title = clean_title.rsplit(" - ", 1)[0].strip()
    text = normalize_space(f"{clean_title}. {clean_summary}")
    if not includes_keyword(text):
        return None

    leader_name, leader_title = infer_leader(text)
    visit_date = infer_visit_date(text, published)
    leader_country = infer_leader_country(leader_name, text, source.get("country_hint", ""))
    origin = infer_origin(text)
    now = utc_now()

    return {
        "id": make_id(url, leader_name, visit_date, clean_title),
        "leader_name": leader_name,
        "leader_title": leader_title,
        "country": leader_country,
        "origin": origin,
        "visit_date": visit_date,
        "event_type": infer_event_type(text),
        "destination": infer_destination(text),
        "summary": clean_summary or clean_title,
        "source_name": source.get("name", ""),
        "source_url": url,
        "published_at": published,
        "language": source.get("language", ""),
        "possibly_special_aircraft": possibly_special_aircraft(text),
        "created_at": now,
        "updated_at": now,
    }


def fetch_rss(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    feed = feedparser.parse(source["url"], request_headers={"User-Agent": USER_AGENT})
    records: List[Dict[str, Any]] = []
    for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
        title = normalize_space(getattr(entry, "title", ""))
        summary = normalize_space(getattr(entry, "summary", ""))
        url = getattr(entry, "link", "")
        published = parse_date(getattr(entry, "published", "") or getattr(entry, "updated", ""))
        record = build_record(source, title, summary, url, published)
        if record:
            records.append(record)
    return records


def fetch_html(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not can_fetch(source["url"]):
        print(f"robots.txt disallows {source['url']}", file=sys.stderr)
        return []

    response = requests.get(source["url"], headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records: List[Dict[str, Any]] = []
    selector = source.get("link_selector", "a")
    base_url = source.get("base_url") or source["url"]
    seen_urls = set()

    for link in soup.select(selector):
        title = normalize_space(link.get_text(" "))
        href = link.get("href")
        if not title or not href:
            continue
        url = urljoin(base_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        record = build_record(source, title, title, url, "")
        if record:
            records.append(record)
        if len(records) >= MAX_ITEMS_PER_SOURCE:
            break
    return records


def fetch_source(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not source.get("enabled", True):
        return []
    source_type = source.get("type")
    if source_type == "rss":
        return fetch_rss(source)
    if source_type == "html":
        return fetch_html(source)
    raise ValueError(f"Unsupported source type: {source_type}")


def main() -> int:
    sources = load_json(SOURCES_PATH, [])
    existing = load_json(VISITS_PATH, [])
    incoming: List[Dict[str, Any]] = []

    for source in sources:
        try:
            records = fetch_source(source)
            incoming.extend(records)
            print(f"{source.get('name')}: {len(records)} candidate records")
        except Exception as exc:
            print(f"{source.get('name')}: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(REQUEST_DELAY_SECONDS)

    merged = dedupe_records(existing, incoming)
    write_json(VISITS_PATH, merged)
    print(f"Wrote {len(merged)} records to {VISITS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
