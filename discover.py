"""Find videos and articles by keyword (discover.json), beyond the fixed channel and blog lists.

Usage:
  python3 discover.py        # search every query, write raw/_discovered.json and raw_articles/discovered.json

For every query in discover.json:
  * YouTube search (yt-dlp, no API key): the top results, kept if they have >= min_views views,
    last 3 min to 3 h, and have a mostly-Latin title (English content).
  * Hacker News search (Algolia, no key): stories with >= min_points points, linking to a page.
A result is kept only if its title contains every non-generic word of the query, so "itertools"
needs "itertools" in the title. Each query keeps its per_query best results (by views or points).
Queries in the "python" group are searched as "python <query>", and a result must be about Python:
"python" in the title (or the URL, or a video from a channel in channels.json) and no other language named.

fetch.py and articles.py pick these files up when they build, as the "D" (Discovered) tier:
videos keep their real channel, articles go into one "Discovered" source.
"""
import json, re, subprocess, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
YTDLP = ["uvx", "--from", "yt-dlp@latest", "yt-dlp"]
UA = "Mozilla/5.0 (compatible; NerdvanaBot/1.0; +https://github.com/GeenccMustafa/nerdvana)"
SEARCH_N = 30   # YouTube results read per query
GENERIC = {"python", "tutorial", "tutorials", "explained", "module", "modules", "library", "libraries", "guide",
           "beginners", "beginner", "how", "to", "the", "in", "for", "with", "and", "a", "an", "of", "crash", "course"}


def must_words(q):
    return [w for w in re.findall(r"[a-z0-9_+]+", q.lower()) if w not in GENERIC]


def title_ok(title, words, phrase=False):
    if phrase:   # general queries: the words in this order, next to each other ("code review", "code reviews")
        return bool(re.search(r"(?<![a-z0-9])" + r"\w*\W+".join(map(re.escape, words)) + r"\w*", (title or "").lower()))
    t = re.findall(r"[a-z0-9_+]+", (title or "").lower())
    # "type hints" also matches "type hinting", "decorators" matches "decorator"
    return all(any(x.startswith(w) or w.startswith(x) and len(w) - len(x) <= 1 and len(x) >= 4 for x in t) for w in words)


OTHER_LANG = re.compile(r"(?<![a-z])(c\+\+|c#|java|javascript|typescript|rust|golang|php|ruby|kotlin|swift|"
                        r"lua|julia|clojure|haskell|elixir|hindi|urdu)(?![a-z])", re.I)


def is_python(text, also=False):
    return ("python" in text.lower() or also) and not OTHER_LANG.search(text)


NOT_TALKS = re.compile(r"chillstep|lo-?fi|beats|ambient|music|playlist|asmr", re.I)


def watchable(e):
    """Not members-only, Premium-only or login-only, and not an upcoming premiere."""
    return e.get("availability") not in ("subscriber_only", "premium_only", "needs_auth") and e.get("live_status") != "is_upcoming"


def latin(title):
    letters = [c for c in title if c.isalpha()]
    return not letters or sum(c.isascii() for c in letters) / len(letters) >= 0.9


def search_youtube(q, py, cfg, known):
    query = f"python {q}" if py else q
    r = subprocess.run(YTDLP + ["--flat-playlist", "-J", f"ytsearch{SEARCH_N}:{query}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return q, [], "FAILED: " + (r.stderr.strip().splitlines() or ["?"])[-1][-160:]
    words, out = must_words(q), []
    for e in json.loads(r.stdout).get("entries") or []:
        dur, views, title = e.get("duration") or 0, e.get("view_count") or 0, e.get("title") or ""
        if not e.get("id") or not e.get("channel_id") or "#short" in title.lower() or not watchable(e):
            continue
        if views < cfg["min_views"] or not 180 <= dur <= 3 * 3600 or not latin(title) or NOT_TALKS.search(title) \
                or not title_ok(title, words, phrase=not py):
            continue
        if py and not is_python(title, also=(e.get("uploader_id") or "").lower() in known):
            continue
        out.append({"id": e["id"], "title": title, "duration": dur, "view_count": views,
                    "channel": e.get("channel") or e.get("uploader") or "", "channel_id": e["channel_id"],
                    "uploader_id": e.get("uploader_id") or "", "query": q})
    out.sort(key=lambda v: -v["view_count"])
    return f"{'py ' if py else ''}{q}", out[:cfg["per_query"]], ""


def search_hn(q, py, cfg):
    query = " ".join(must_words(q)) or q
    params = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": 100,
                                     "numericFilters": f"points>={cfg['min_points']}"})
    req = urllib.request.Request(f"https://hn.algolia.com/api/v1/search?{params}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            hits = json.loads(r.read()).get("hits", [])
    except Exception as e:
        return q, [], f"FAILED: {type(e).__name__}: {str(e)[:120]}"
    words, out = must_words(q), []
    for h in hits:
        u, title = h.get("url") or "", h.get("title") or ""
        host = urllib.parse.urlsplit(u).netloc.lower()
        if not u.startswith(("http://", "https://")) or any(x in host for x in ("youtube.com", "youtu.be", "github.com")):
            continue
        if title.lower().startswith(("show hn", "ask hn", "launch hn", "tell hn")) or not title_ok(title, words, phrase=not py):
            continue
        if py and not (is_python(title + " " + u) and not OTHER_LANG.search(title)):
            continue
        out.append({"url": u, "title": title, "points": h.get("points") or 0, "comments": h.get("num_comments") or 0,
                    "hn": int(h["objectID"]), "hn_ts": h.get("created_at_i"), "query": q})
    out.sort(key=lambda a: -a["points"])
    return f"{'py ' if py else ''}{q}", out[:cfg["per_query"]], ""


def write(path, data):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.rename(path)


if __name__ == "__main__":
    cfg = json.loads((ROOT / "discover.json").read_text())
    queries = [(q, True) for q in cfg["python"]] + [(q, False) for q in cfg["general"]]
    known = {"@" + c["handle"].lower() for c in json.loads((ROOT / "channels.json").read_text())}
    videos, articles = {}, {}
    with ThreadPoolExecutor(8) as ex:
        for q, found, err in ex.map(lambda x: search_youtube(*x, cfg, known), queries):
            new = [v for v in found if v["id"] not in videos]
            videos.update((v["id"], v) for v in new)
            print(f"  yt  {q:40} {len(found):2} kept, {len(new):2} new {err}", flush=True)
        for q, found, err in ex.map(lambda x: search_hn(*x, cfg), queries):
            new = [a for a in found if a["url"] not in articles]
            articles.update((a["url"], a) for a in new)
            print(f"  hn  {q:40} {len(found):2} kept, {len(new):2} new {err}", flush=True)
    # a failed run (e.g. YouTube blocking the runner) keeps the previous results instead of emptying them
    if videos or not (ROOT / "raw" / "_discovered.json").exists():
        write(ROOT / "raw" / "_discovered.json", {"entries": list(videos.values())})
    if articles or not (ROOT / "raw_articles" / "discovered.json").exists():
        write(ROOT / "raw_articles" / "discovered.json", {"hn": list(articles.values()), "rss": [], "err": []})
    print(f"discovered: {len(videos)} videos, {len(articles)} articles")
    if not videos and not articles:
        sys.exit(1)
