#!/usr/bin/env python3
"""gzh-creation-system 外网选题抓取脚本。

抓取外网 RSS 源（苹果向 + 特斯拉/新能源向），输出最近 N 小时的选题清单，
供公众号选题环节使用。只用 Python 标准库，无需安装依赖。

用法：
  python scripts/fetch_topics.py                  # 全部源，最近 48 小时
  python scripts/fetch_topics.py --group apple    # 只看苹果组
  python scripts/fetch_topics.py --group tesla    # 只看特斯拉组
  python scripts/fetch_topics.py --hours 24 --take 20 --json
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    group: str  # apple | tesla


# 外网源（均为英文媒体；Bloomberg 偶发不稳定，抓不到会自动跳过）
APPLE_FEEDS = [
    Feed("MacRumors", "https://feeds.macrumors.com/MacRumors-All", "apple"),
    Feed("9to5Mac", "https://9to5mac.com/feed/", "apple"),
    Feed("AppleInsider", "https://appleinsider.com/rss/news/", "apple"),
    Feed("Cult of Mac", "https://www.cultofmac.com/feed/", "apple"),
    Feed("MacStories", "https://www.macstories.net/feed/", "apple"),
    Feed("AppleTrack", "https://appletrack.com/feed/", "apple"),
    Feed(
        "Mark Gurman / Bloomberg",
        "https://www.bloomberg.com/authors/AS7Hj1mBMGM/mark-gurman.rss",
        "apple",
    ),
]

TESLA_FEEDS = [
    Feed("Electrek", "https://electrek.co/feed/", "tesla"),
    Feed("Teslarati", "https://www.teslarati.com/feed/", "tesla"),
]

# 与公众号调性明显不匹配的标题关键词（周报/促销/评测类），选题时跳过
SKIP_KEYWORDS = [
    "weekly roundup",
    "top stories",
    "weekend deals",
    "deals:",
    "sale:",
    "giveaway",
    "review:",
    "app of the week",
    "our favorite",
]


def strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def child_text(node: ET.Element, names: Iterable[str]) -> str | None:
    wanted = set(names)
    for child in list(node):
        if strip_namespace(child.tag) in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def atom_link(node: ET.Element) -> str | None:
    for child in list(node):
        if strip_namespace(child.tag) != "link":
            continue
        rel = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href")
        if href and rel in {"alternate", ""}:
            return href.strip()
    return None


def clean_text(value: str | None, limit: int = 200) -> str | None:
    if not value:
        return None
    value = html.unescape(value)
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        dt = None
    if dt is None:
        try:
            normalized = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [
        (key, value)
        for key, value in query
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            urllib.parse.urlencode(kept, doseq=True),
            "",
        )
    )


def fetch_feed(feed: Feed, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        feed.url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_feed(feed: Feed, data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    root_kind = strip_namespace(root.tag)

    if root_kind == "rss":
        channel = next(
            (child for child in list(root) if strip_namespace(child.tag) == "channel"),
            root,
        )
        entries = [
            child for child in list(channel) if strip_namespace(child.tag) == "item"
        ]
    elif root_kind == "feed":
        entries = [
            child for child in list(root) if strip_namespace(child.tag) == "entry"
        ]
    else:
        entries = []

    items: list[dict] = []
    for entry in entries:
        title = clean_text(child_text(entry, ["title"]), limit=180)
        if not title:
            continue

        url = child_text(entry, ["link"]) or atom_link(entry) or child_text(entry, ["guid"])
        if not url:
            continue
        url = html.unescape(url).strip()
        if not url.startswith(("http://", "https://")):
            continue

        summary = clean_text(
            child_text(entry, ["description", "summary", "content", "encoded"]),
            limit=280,
        )
        published_raw = child_text(entry, ["pubDate", "published", "updated", "date"])
        published_at = parse_datetime(published_raw)

        items.append(
            {
                "title": title,
                "url": canonical_url(url),
                "source": feed.name,
                "group": feed.group,
                "published_at": published_at.isoformat().replace("+00:00", "Z")
                if published_at
                else None,
                "published_at_raw": published_raw,
                "summary": summary,
            }
        )
    return items


def select_feeds(group: str) -> list[Feed]:
    if group == "apple":
        return APPLE_FEEDS
    if group == "tesla":
        return TESLA_FEEDS
    return APPLE_FEEDS + TESLA_FEEDS


def is_skip(title: str) -> bool:
    lowered = title.lower()
    return any(kw in lowered for kw in SKIP_KEYWORDS)


def build_result(args: argparse.Namespace) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)
    warnings: list[str] = []
    seen_urls: set[str] = set()
    collected: list[dict] = []

    for feed in select_feeds(args.group):
        try:
            data = fetch_feed(feed, timeout=args.timeout)
        except Exception as exc:  # 单个源失败不影响整体
            warnings.append(f"{feed.name} 抓取失败: {exc}")
            continue
        try:
            items = parse_feed(feed, data)
        except ET.ParseError as exc:
            warnings.append(f"{feed.name} 解析失败: {exc}")
            continue
        for item in items:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            if is_skip(item["title"]):
                continue
            published_at = item["published_at"]
            if published_at:
                try:
                    dt = parse_datetime(published_at)
                    if dt is None or dt < cutoff:
                        continue
                except Exception:
                    continue
            collected.append(item)

    # 按时间倒序
    def sort_key(item: dict):
        dt = item["published_at"]
        return parse_datetime(dt).timestamp() if dt else 0

    collected.sort(key=sort_key, reverse=True)
    if args.take and args.take > 0:
        collected = collected[: args.take]

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "hours": args.hours,
        "group": args.group,
        "count": len(collected),
        "warnings": warnings,
        "items": collected,
    }


def print_human(result: dict) -> None:
    print(f"外网选题 · 最近 {result['hours']} 小时 · 共 {result['count']} 条")
    print("=" * 78)
    for i, item in enumerate(result["items"], 1):
        published = (item["published_at"] or "?").replace("T", " ")[:16].replace("+00:00", "Z")
        print(f"{i}. [{item['source']}] {item['title']}")
        print(f"   {published} | {item['url']}")
    print("=" * 78)
    for warning in result["warnings"]:
        print(f"⚠ {warning}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="gzh-creation-system 外网选题抓取")
    parser.add_argument("--hours", type=int, default=48, help="回溯小时数（默认 48）")
    parser.add_argument("--group", choices=["apple", "tesla", "all"], default="all")
    parser.add_argument("--take", type=int, default=0, help="最多输出条数（0 = 不限）")
    parser.add_argument("--timeout", type=int, default=20, help="单源超时秒数")
    parser.add_argument("--json", action="store_true", help="输出 JSON 便于程序处理")
    args = parser.parse_args()

    result = build_result(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
