"""Collect popular articles from the blogs in sources.json and write articles.json.

Usage:
  python3 articles.py            # refresh every source (HN + RSS), fetch new pages, rebuild articles.json
  python3 articles.py --build    # only rebuild articles.json from raw_articles/ and the page cache

Where the articles come from:
  * Hacker News (Algolia search API, free, no key): every story ever posted from the source's site,
    with its points. This finds a blog's all-time popular posts and is the popularity score.
  * The source's RSS/Atom feed: its newest posts, including ones that never made it to HN.

For every picked article the page itself is fetched once (then cached) for its description
(og:description, or the first paragraph), cover image, publish date and word count (reading time).
Only short descriptions are published. The first BODY_LEN characters of the text are kept in the
private page cache (.cache/, never committed or shown) so enrich.py can match articles by what they say.
Pages cached before that was added are refetched, BODY_BACKFILL per run.

Balancing, like the videos: at most 150 sources, each keeping its 100 most-upvoted + 30 newest posts.

Articles found by keyword search (discover.py -> raw_articles/discovered.json) come in as one more
source, "Discovered" (tier D), with all of its posts kept. A post that one of the listed blogs
already has stays with that blog.

articles.json  {"sources": [{n, u, t, topic, total}],
                "articles": [[id, title, source, words, points, ts, url, desc, img, hn_id, comments], ...]}
"""
import hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_articles"
CACHE = ROOT / ".cache" / "pages.json"
UA = "Mozilla/5.0 (compatible; NerdvanaBot/1.0; +https://github.com/GeenccMustafa/nerdvana)"
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "D": 3}
DISCOVERED = {"name": "Discovered", "url": "https://github.com/GeenccMustafa/nerdvana/blob/main/discover.json",
              "tier": "D", "topic": "Programming", "discover": True}
MAX_SOURCES, TOP_BY_POINTS, NEWEST = 150, 100, 30
MIN_POINTS, MIN_ARTICLES = 5, 8
DESC_LEN = 220
BODY_LEN = 2000
BODY_BACKFILL = int(os.environ.get("BODY_BACKFILL", 1500))  # cached pages without body text, refetched per run
PAGE_BUDGET = int(os.environ.get("PAGE_BUDGET", 15 * 60))  # seconds; pages not fetched in time are tried again on the next run


def get(url, timeout=20, limit=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit)
        ctype = r.headers.get("Content-Type", "")
        enc = r.headers.get_content_charset() or "utf-8"
        return data.decode(enc, "replace"), ctype, r.geturl()


def norm_url(u):
    """Comparable form of a URL: no scheme, www., query tracking, fragment or trailing slash."""
    p = urllib.parse.urlsplit(u.strip())
    host = p.netloc.lower().removeprefix("www.")
    q = "&".join(x for x in p.query.split("&") if x and not x.startswith(("utm_", "ref=", "source=", "sk=")))
    path = re.sub(r"/(index\.html?)?$", "", p.path) or ""
    return host + path + ("?" + q if q else "")


def match_key(src):
    return norm_url(src["url"])


def slug(src):
    if src.get("discover"):
        return "discovered"
    return re.sub(r"[^a-z0-9]+", "-", match_key(src)).strip("-")


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp())
    except Exception:
        return None


# ---------------------------------------------------------------- sources: HN + feed

def fetch_hn(src):
    key = match_key(src)
    q = urllib.parse.urlencode({"query": key, "restrictSearchableAttributes": "url", "tags": "story",
                                "hitsPerPage": 1000, "numericFilters": f"points>={MIN_POINTS}"})
    body, _, _ = get(f"https://hn.algolia.com/api/v1/search?{q}", timeout=40)
    out = {}
    for h in json.loads(body).get("hits", []):
        u = h.get("url") or ""
        nu = norm_url(u)
        # same site, and an actual post rather than the homepage
        if not (nu == key or nu.startswith(key + "/") or nu.startswith(key + "?")) or len(nu) <= len(key) + 1:
            continue
        if nu.endswith((".pdf", ".mp4", ".mp3", ".zip")):
            continue
        e = out.get(nu)
        if e is None or (h.get("points") or 0) > e["points"]:
            out[nu] = {"url": u, "title": h.get("title") or "", "points": h.get("points") or 0,
                       "comments": h.get("num_comments") or 0, "hn": int(h["objectID"]), "hn_ts": h.get("created_at_i")}
    return list(out.values())


def find_feed(src):
    body, _, final = get(src["url"])
    for m in re.finditer(r"<link\b[^>]*>", body, re.I):
        tag = m.group(0)
        if re.search(r"application/(rss|atom)\+xml", tag, re.I):
            href = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if href:
                return urllib.parse.urljoin(final, html.unescape(href.group(1)))
    return None


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def fetch_feed(src):
    feed = src.get("feed") or find_feed(src)
    if not feed:
        return []
    body, _, final = get(feed, timeout=40, limit=40_000_000)   # some blogs put every full post in the feed
    root = ET.fromstring(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", body).encode("utf-8"))
    items = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in el}
        link = ""
        if "link" in f:
            link = (f["link"].text or "").strip() or f["link"].get("href", "")
            for c in el:   # Atom: prefer rel="alternate"
                if c.tag.split("}")[-1] == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                    link = c.get("href"); break
        if not link and "guid" in f and (f["guid"].text or "").startswith("http"):
            link = f["guid"].text.strip()
        if not link:
            continue
        date = next((parse_date(f[k].text) for k in ("pubDate", "published", "updated", "date") if k in f and f[k].text), None)
        summ = next((strip_tags(f[k].text) for k in ("description", "summary", "content", "encoded") if k in f and f[k].text), "")
        items.append({"url": urllib.parse.urljoin(final, link.strip()), "title": strip_tags(f["title"].text if "title" in f else ""),
                      "ts": date, "summary": summ[:600]})
    return items


def refresh_source(src):
    out = {"hn": [], "rss": [], "err": []}
    for kind, fn in (("hn", fetch_hn), ("rss", fetch_feed)):
        for attempt in range(3):
            try:
                out[kind] = fn(src); break
            except Exception as e:
                if attempt == 2:
                    out["err"].append(f"{kind}: {type(e).__name__}: {str(e)[:120]}")
                time.sleep(2 * (attempt + 1))
    path = RAW / f"{slug(src)}.json"
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(out, ensure_ascii=False))
    tmp.rename(path)
    return src["name"], len(out["hn"]), len(out["rss"]), out["err"]


# ---------------------------------------------------------------- pages

def meta(body, *names):
    for n in names:
        for pat in (rf'<meta\b[^>]*(?:property|name)=["\']{n}["\'][^>]*content=["\']([^"\']*)',
                    rf'<meta\b[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{n}["\']'):
            m = re.search(pat, body, re.I)
            if m and m.group(1).strip():
                return html.unescape(m.group(1)).strip()
    return ""


def page_info(url):
    body, ctype, final = get(url, timeout=12)
    if "html" not in ctype and "<html" not in body[:2000].lower():
        return {"ok": 1, "body": ""}
    head = body[:200_000]
    info = {"ok": 1, "title": meta(head, "og:title", "twitter:title"),
            "desc": meta(head, "og:description", "twitter:description", "description"),
            "img": meta(head, "og:image", "twitter:image", "twitter:image:src"),
            "date": parse_date(meta(head, "article:published_time", "datePublished", "date", "dc.date"))}
    if not info["date"]:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', body)
        info["date"] = parse_date(m.group(1)) if m else None
    if info["img"]:
        info["img"] = urllib.parse.urljoin(final, info["img"])
    text = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|aside|form)\b.*?</\1>", " ", body)
    arts = re.findall(r"(?is)<article\b.*?</article>", text)
    main = max(arts, key=len) if arts else (re.search(r"(?is)<main\b.*?</main>", text) or re.search(r"(?is)<body\b.*", text) or [text])[0]
    plain = strip_tags(main)
    info["words"] = len(re.findall(r"\w+", plain))
    info["body"] = plain[:BODY_LEN]
    for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", main):
        t = strip_tags(p)
        if len(t) >= 80:
            info["para"] = t[:600]; break
    return info


def fetch_pages(urls, cache):
    """Fetch pages host by host (one request at a time per site, many sites in parallel)."""
    by_host = defaultdict(list)
    for u in urls:
        by_host[urllib.parse.urlsplit(u).netloc].append(u)
    done, deadline = [0], time.time() + PAGE_BUDGET

    def run(host_urls):
        for u in host_urls:
            if time.time() > deadline:
                return
            try:
                cache[u] = page_info(u)
            except Exception as e:
                if (cache.get(u) or {}).get("ok"):   # body backfill failed: keep what we had, don't retry forever
                    cache[u]["body"] = ""
                else:
                    cache[u] = {"ok": 0, "err": type(e).__name__}
            done[0] += 1
            if done[0] % 250 == 0:
                print(f"  pages {done[0]}/{len(urls)}", flush=True)
                save_cache(cache)
            time.sleep(0.3)

    with ThreadPoolExecutor(24) as ex:
        list(ex.map(run, by_host.values()))
    save_cache(cache)


def load_cache():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # articles.json doubles as a cache, so a fresh machine (or CI without its cache) doesn't refetch everything
    prev = ROOT / "articles.json"
    if prev.exists():
        for a in json.loads(prev.read_text())["articles"]:
            cache.setdefault(a[6], {"ok": 1, "title": a[1], "desc": a[7], "img": a[8], "words": a[3], "date": a[5], "kept": 1})
    return cache


def save_cache(cache):
    CACHE.parent.mkdir(exist_ok=True)
    tmp = CACHE.with_suffix(".part")
    tmp.write_text(json.dumps(cache, ensure_ascii=False))
    tmp.rename(CACHE)


# ---------------------------------------------------------------- build

def clean_title(t):
    t = re.sub(r"\s*\[(pdf|video|audio)\]\s*$", "", t, flags=re.I)
    return re.sub(r"\s*\((19|20)\d\d\)\s*$", "", t).strip()


def year_hint(t):
    m = re.search(r"\(((?:19|20)\d\d)\)\s*$", t)
    return int(datetime(int(m.group(1)), 6, 1, tzinfo=timezone.utc).timestamp()) if m else None


def shorten(s, n=DESC_LEN):
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"\s*(\[?(…|\.\.\.)\]?\s*)?(Read more|Continue reading|Read the full (post|article))\W*$", "…", s, flags=re.I)
    s = re.sub(r"\s*The post .{0,200} appeared first on .{0,80}$", "", s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + "…"


def pick(srcs, refetch_pages=True):
    """Per source: top posts by HN points + newest from the feed."""
    picked = []   # (src index, record)
    for si, s in enumerate(srcs):
        raw = json.loads((RAW / f"{slug(s)}.json").read_text()) if (RAW / f"{slug(s)}.json").exists() else {"hn": [], "rss": []}
        hn = {norm_url(h["url"]): h for h in raw["hn"]}
        rss = {norm_url(r["url"]): r for r in raw["rss"]}
        top = sorted(hn, key=lambda k: -hn[k]["points"])[:None if s.get("discover") else TOP_BY_POINTS]
        newest = sorted(rss, key=lambda k: -(rss[k]["ts"] or 0))[:NEWEST]
        keys = list(dict.fromkeys(top + newest))
        s["_total"] = len(set(hn) | set(rss))
        for k in keys:
            h, r = hn.get(k, {}), rss.get(k, {})
            picked.append((si, {"key": k, "url": h.get("url") or r.get("url"), "hn": h, "rss": r}))
    return picked


def build(srcs, cache):
    picked = pick(srcs)
    per_src = defaultdict(list)
    for si, rec in picked:
        per_src[si].append(rec)
    # A description shared by several posts of one source is the site's tagline, not the post's
    # ...and an image shared by several posts is the site's logo, not a cover image
    generic, generic_img = defaultdict(Counter), defaultdict(Counter)
    for si, recs in per_src.items():
        for r in recs:
            c = cache.get(r["url"]) or {}
            if c.get("desc"):
                generic[si][c["desc"]] += 1
            if c.get("img"):
                generic_img[si][c["img"]] += 1
    keep = [si for si, recs in per_src.items() if len(recs) >= MIN_ARTICLES]
    keep.sort(key=lambda si: (TIER_ORDER[srcs[si]["tier"]], -sum(r["hn"].get("points", 0) for r in per_src[si])))
    keep = sorted(keep[:MAX_SOURCES])
    remap = {si: i for i, si in enumerate(keep)}
    sources, rows, seen_ids = [], [], set()
    for si in keep:
        s = srcs[si]
        sources.append({"n": s["name"], "u": s["url"], "t": s["tier"], "topic": s["topic"], "total": s["_total"]})
        for r in per_src[si]:
            h, f, p = r["hn"], r["rss"], cache.get(r["url"]) or {}
            title = clean_title(h.get("title") or f.get("title") or p.get("title") or "")
            # only plain web links: a feed could carry javascript: or data: URLs
            if not title or not re.match(r"https?://", r["url"] or ""):
                continue
            desc = p.get("desc") or ""
            if generic[si][desc] > 1 or len(desc) < 40 or desc.lower().startswith(title.lower()[:40]) and len(desc) < len(title) + 20:
                desc = p.get("para") or f.get("summary") or (desc if generic[si][desc] <= 1 else "")
            ts = p.get("date") or f.get("ts") or year_hint(h.get("title") or "") or h.get("hn_ts") or 0
            aid = hashlib.sha1(r["key"].encode()).hexdigest()[:10]
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            words = p.get("words") or 0
            if words and words < 80:      # paywall stubs, link pages, redirects
                words = 0
            rows.append([aid, title, remap[si], words, h.get("points", 0), ts or 0, r["url"], shorten(desc),
                         (p.get("img") or "") if generic_img[si][p.get("img")] <= 2 and re.match(r"https?://", p.get("img") or "") else "", h.get("hn", 0), h.get("comments", 0)])
    disc = [si for si, s in enumerate(srcs) if s.get("discover")]
    found = set()
    if disc and (RAW / "discovered.json").exists():
        found = {hashlib.sha1(norm_url(h["url"]).encode()).hexdigest()[:10]
                 for h in json.loads((RAW / "discovered.json").read_text())["hn"]}
    out = {"sources": sources, "articles": rows, "discovered": [r[0] for r in rows if r[0] in found]}
    (ROOT / "articles.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    n_desc = sum(bool(r[7]) for r in rows)
    print(f"articles.json: {len(sources)} sources, {len(rows)} articles ({n_desc} with a description, "
          f"{sum(bool(r[8]) for r in rows)} with an image), {(ROOT / 'articles.json').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    srcs = json.loads((ROOT / "sources.json").read_text())
    RAW.mkdir(exist_ok=True)
    if not {"--build", "--pages"} & set(sys.argv):
        print(f"refreshing {len(srcs)} sources…", flush=True)
        with ThreadPoolExecutor(8) as ex:
            for name, nh, nr, err in ex.map(refresh_source, srcs):
                print(f"  {name:28} hn={nh:4} rss={nr:3} {' | '.join(err)}", flush=True)
    if (RAW / "discovered.json").exists():   # written by discover.py, not refreshed here
        srcs.append(DISCOVERED)
    cache = load_cache()
    urls = [r["url"] for _, r in pick(srcs)]
    todo = [u for u in urls if u not in cache]
    # pages cached before body text was kept: refetch some of them each run
    backfill = [u for u in urls if u in cache and cache[u].get("ok") and "body" not in cache[u]][:BODY_BACKFILL]
    if (todo or backfill) and "--build" not in sys.argv:   # --pages: skip the source refresh, only fetch pages
        print(f"fetching {len(todo)} new pages, {len(backfill)} for body text…", flush=True)
        fetch_pages(todo + backfill, cache)
    build(srcs, cache)
