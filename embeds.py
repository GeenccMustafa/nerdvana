"""Find the videos in videos.json that play only on YouTube, and write their ids to noembed.json.

Some owners turn off playing their videos on other sites. The site keeps those videos everywhere, tagged
"YouTube ↗", and opens them on YouTube instead of showing YouTube's "Video unavailable" screen in its player.

YouTube's oEmbed endpoint tells them apart without an API key: 200 = plays anywhere, 401 = YouTube only,
404 = removed or private (left untagged). Results are cached in .cache/embeds.json, so each night only new
videos are checked, plus YouTube-only ones older than RECHECK_DAYS (an owner may turn it back on).
noembed.json is committed, so the list survives a lost cache.

Usage:
  python3 embeds.py              # check up to MAX_CHECKS unchecked videos, then write noembed.json
  python3 embeds.py --max 1000   # check at most 1000
"""
import json, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "embeds.json"
OUT = ROOT / "noembed.json"
MAX_CHECKS = 30000      # per run; the first run (about 54,000 videos) finishes over two nights
TIME_LIMIT = 20 * 60    # seconds, so the nightly refresh stays inside its timeout
WORKERS = 16
RECHECK_DAYS = 30
OK, YT_ONLY, GONE = 1, 0, 2


def check(vid):
    """Return OK, YT_ONLY or GONE, or None when YouTube didn't give a clear answer (rate limit, network)."""
    url = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={vid}"
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read()
        return OK
    except urllib.error.HTTPError as e:
        return {401: YT_ONLY, 404: GONE}.get(e.code)
    except Exception:
        return None


def main():
    limit = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else MAX_CHECKS
    ids = [v[0] for v in json.loads((ROOT / "videos.json").read_text())["videos"]]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}   # id -> [status, day checked]
    today = int(time.time() // 86400)
    # a lost cache must not untag anything: last committed list counts as checked today
    if OUT.exists():
        for vid in json.loads(OUT.read_text()):
            cache.setdefault(vid, [YT_ONLY, today])
    todo = [v for v in ids if v not in cache or cache[v][0] == YT_ONLY and today - cache[v][1] >= RECHECK_DAYS][:limit]
    print(f"{len(ids)} videos, {len(todo)} to check")

    start, done, unclear = time.time(), 0, 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for i in range(0, len(todo), 400):
            if time.time() - start > TIME_LIMIT:
                print("Time limit reached; the rest waits for the next run.")
                break
            batch = todo[i:i + 400]
            for vid, status in zip(batch, ex.map(check, batch)):
                if status is None: unclear += 1
                else: cache[vid] = [status, today]; done += 1
            # mostly unclear answers: YouTube is throttling this runner, stop and keep what we have
            if unclear > 200 and unclear > done:
                print("::warning::YouTube oEmbed is mostly failing; stopping early.")
                break
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, separators=(",", ":")))

    known = set(ids)
    only = sorted(v for v, (s, _) in cache.items() if s == YT_ONLY and v in known)
    OUT.write_text(json.dumps(only, separators=(",", ":")) + "\n")
    left = sum(v not in cache for v in ids)
    print(f"Checked {done} ({unclear} unclear) in {time.time() - start:.0f}s; {len(only)} play only on YouTube; {left} not checked yet")


if __name__ == "__main__":
    main()
