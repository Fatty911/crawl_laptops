"""Shared parsing and HTTP helpers for source crawlers."""

from __future__ import annotations

import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_session(cookie: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }
    )
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        allowed_methods=frozenset({"GET", "HEAD"}),
        status_forcelist=(429, 500, 502, 503, 504),
        backoff_factor=0.5,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def get_html(
    session: requests.Session,
    url: str,
    *,
    encoding: str | None = None,
    delay: float = 0.0,
    timeout: int = 25,
) -> tuple[BeautifulSoup, str]:
    if delay:
        time.sleep(delay + random.uniform(0, min(0.35, delay)))
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    if encoding:
        response.encoding = encoding
    elif response.encoding and response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return BeautifulSoup(response.text, "html.parser"), response.url


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def parse_price(value: Any) -> float | None:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", clean_text(value))
    return float(match.group(1).replace(",", "")) if match else None


def parse_number(value: Any) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", clean_text(value))
    return float(match.group(1)) if match else None


def parse_capacity_gb(value: Any) -> int | None:
    text = clean_text(value).upper()
    values: list[float] = []
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(TB|GB)", text):
        values.append(float(number) * (1024 if unit == "TB" else 1))
    return int(max(values)) if values else None


def parse_battery_wh(value: Any) -> float | None:
    text = clean_text(value)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:Wh|瓦时)", text, re.I)
    return float(match.group(1)) if match else None


def parse_cpu_fields(cpu: str) -> tuple[str, str]:
    text = clean_text(cpu)
    lowered = text.lower()
    if any(value in lowered for value in ("intel", "酷睿", "ultra")):
        brand = "Intel"
    elif any(value in lowered for value in ("amd", "ryzen", "锐龙")):
        brand = "AMD"
    else:
        brand = ""
    family_match = re.search(r"(Ultra\s*[3579]|i[3579]|Ryzen\s*[3579]|锐龙\s*[3579])", text, re.I)
    return brand, clean_text(family_match.group(1)) if family_match else ""


def infer_brand(title: str) -> str:
    aliases = (
        ("ThinkPad", "ThinkPad"),
        ("联想", "联想"),
        ("Lenovo", "联想"),
        ("华硕", "华硕"),
        ("ASUS", "华硕"),
        ("惠普", "惠普"),
        ("HP", "惠普"),
        ("戴尔", "戴尔"),
        ("DELL", "戴尔"),
        ("宏碁", "宏碁"),
        ("Acer", "宏碁"),
        ("华为", "华为"),
        ("HUAWEI", "华为"),
        ("荣耀", "荣耀"),
        ("HONOR", "荣耀"),
        ("小米", "小米"),
        ("机械革命", "机械革命"),
        ("微星", "微星"),
        ("MSI", "微星"),
        ("微软", "微软"),
        ("Microsoft", "微软"),
    )
    for needle, brand in aliases:
        if needle.lower() in title.lower():
            return brand
    return clean_text(title).split(" ", 1)[0][:24]


def keyboard_flags(description: str) -> tuple[bool | None, bool | None]:
    text = clean_text(description)
    numeric: bool | None = None
    backlight: bool | None = None
    if re.search(r"(无|不带|取消).{0,4}(数字小键盘|数字键盘|数字键区)", text):
        numeric = False
    elif re.search(r"(数字小键盘|独立数字键|数字键区|数字键盘)", text):
        numeric = True
    if re.search(r"(无|不带|取消).{0,4}(背光键盘|键盘背光)", text):
        backlight = False
    elif re.search(r"(背光键盘|键盘背光|RGB键盘|RGB背光)", text, re.I):
        backlight = True
    return numeric, backlight


def gpu_fields(gpu_type: str, gpu: str) -> tuple[str, bool | None]:
    text = clean_text(f"{gpu_type} {gpu}")
    if re.search(r"(独立显卡|独显|RTX|GTX|Radeon\s+RX)", text, re.I):
        return "dedicated", True
    if re.search(r"(核芯显卡|核心显卡|集成显卡|集显|Iris|Intel\s+Arc\s+\d{2,3}[TV]?)", text, re.I):
        return "integrated", False
    return "unknown", None


def absolute_url(base: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base, href)


def text_from_spec(specs: dict[str, str], *names: str) -> str:
    for name in names:
        if specs.get(name):
            return specs[name]
    return ""
