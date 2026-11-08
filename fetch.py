"""Fetch videos for every channel in channels.json with yt-dlp, then build videos.json.

Usage:
  python3 fetch.py          # fetch channels not yet in raw/, then build
  python3 fetch.py --build  # only rebuild videos.json from raw/
  python3 fetch.py --force  # re-fetch everything

Balancing rules (so a few prolific channels can't drown out the rest):
  - only channels with >= MIN_SUBS subscribers are kept, at most MAX_CHANNELS of them
    (picked by tier first, then subscriber count)
  - each channel keeps at most TOP_BY_VIEWS most-viewed + NEWEST most-recent videos
  - clips of 60s or shorter (Shorts) are dropped
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
YTDLP = ["uvx", "--from", "yt-dlp@latest", "yt-dlp"]
FETCH_LIMIT = 3000      # newest N uploads read per channel
MIN_SUBS = 250_000
MAX_CHANNELS = 100
TOP_BY_VIEWS = 300
NEWEST = 100
TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}


def fetch(ch, force=False):
    out = RAW / f"{ch['handle']}.json"
    if out.exists() and not force:
        return ch["handle"], "cached"
    cmd = YTDLP + ["--flat-playlist", "-J", "--playlist-end", str(FETCH_LIMIT),
                   "--extractor-args", "youtubetab:approximate_date",
                   ch.get("url") or f"https://www.youtube.com/@{ch['handle']}/videos"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return ch["handle"], "FAILED: " + (r.stderr.strip().splitlines() or ["?"])[-1][-200:]
    tmp = out.with_suffix(".part")
    tmp.write_text(r.stdout)
    tmp.rename(out)  # atomic: a concurrent build never sees half a file
    d = json.loads(r.stdout)
    return ch["handle"], f"{len(d.get('entries') or [])} videos, {d.get('channel_follower_count')} subs"


def pick_videos(entries):
    vids = []
    for e in entries or []:
        if not e.get("id") or e.get("title") in ("[Private video]", "[Deleted video]"):
            continue
        dur = e.get("duration")
        if dur is not None and dur <= 60:
            continue
        vids.append([e["id"], e.get("title", ""), int(dur or 0),
                     int(e.get("view_count") or 0), int(e.get("timestamp") or 0)])
    keep = {v[0]: v for v in sorted(vids, key=lambda v: -v[3])[:TOP_BY_VIEWS]}
    keep.update({v[0]: v for v in sorted(vids, key=lambda v: -v[4])[:NEWEST]})
    return list(keep.values()), len(vids)


def build(channels):
    loaded, skipped = [], []
    for ch in channels:
        f = RAW / f"{ch['handle']}.json"
        if not f.exists():
            skipped.append((ch["handle"], "not fetched")); continue
        d = json.loads(f.read_text())
        subs = d.get("channel_follower_count") or 0
        if subs < MIN_SUBS:
            skipped.append((ch["handle"], f"{subs:,} subs")); continue
        loaded.append((ch, d, subs))
    loaded.sort(key=lambda x: (TIER_RANK.get(x[0]["tier"], 9), -x[2]))
    for ch, _, subs in loaded[MAX_CHANNELS:]:
        skipped.append((ch["handle"], f"over {MAX_CHANNELS} limit ({subs:,} subs)"))
    loaded = sorted(loaded[:MAX_CHANNELS], key=lambda x: -x[2])

    chans, vids = [], []
    for ch, d, subs in loaded:
        picked, total = pick_videos(d.get("entries"))
        avatar = next((t["url"] for t in d.get("thumbnails") or [] if t.get("id") == "avatar_uncropped"), "")
        if avatar:
            avatar = avatar.rsplit("=", 1)[0] + "=s88-c-k-c0x00ffffff-no-rj"  # 88px square
        chans.append({"h": ch["handle"], "n": d.get("channel") or ch["handle"], "t": ch["tier"],
                      "topic": ch["topic"], "subs": subs, "total": total, "a": avatar})
        ci = len(chans) - 1
        vids += [[v[0], v[1], ci, v[2], v[3], v[4]] for v in picked]
    data = {"channels": chans, "videos": vids,
            "fields": ["id", "title", "channel", "duration", "views", "timestamp"]}
    (ROOT / "videos.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    for h, why in skipped:
        print(f"  skipped {h:28} {why}")
    print(f"videos.json: {len(chans)} channels, {len(vids)} videos")


if __name__ == "__main__":
    channels = json.loads((ROOT / "channels.json").read_text())
    if "--build" not in sys.argv:
        RAW.mkdir(exist_ok=True)
        with ThreadPoolExecutor(8) as ex:
            for h, status in ex.map(lambda c: fetch(c, "--force" in sys.argv), channels):
                print(f"{h:28} {status}", flush=True)
    build(channels)
