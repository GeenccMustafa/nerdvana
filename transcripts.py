"""Download English subtitles for the S-tier channels and build search.json (transcript search).

Usage:
  python3 transcripts.py            # download missing transcripts, then build search.json
  python3 transcripts.py --build    # only rebuild search.json from transcripts/

A weekly GitHub Action (transcripts.yml) runs this for new videos; the transcripts/ folder itself is
kept as a release asset, not in git. It is resumable: already-downloaded videos are skipped, and videos
from the last 14 days that had no subtitles yet are tried again (auto-captions can take a while).
If YouTube starts refusing requests ("confirm you're not a bot"), it stops and keeps what it has.

  MAX_NEW=500 python3 transcripts.py   # fetch at most 500 transcripts this run

transcripts/<id>.json  compact transcript: [[start_seconds, "text"], ...] in ~20 s chunks (not committed)
search.json            inverted index: {"docs": [video ids], "terms": {term: [[doc, second], ...]}}
"""
import json, math, os, re, subprocess, sys, tempfile, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "transcripts"
YTDLP = ["uvx", "--from", "yt-dlp@latest", "yt-dlp"]
TOP_BY_VIEWS, NEWEST = 120, 20
WORKERS, BATCH = 4, 40
TERMS_PER_VIDEO = 150

STOP = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each even every few for from further get gets
getting go goes going gonna got had has have having he her here hers him his how i if in into is it its itself just
know let like lot make many may me more most much must my no nor not now of off oh ok okay on once one only or other
our out over own really right said same say says see she should so some something such take than that thats the their
them then there these they thing things think this those through to too uh um under until up us very want was way
we well were what when where which while who why will with would yeah yes you your actually because kind little look
mean need pretty probably quite sort stuff sure basically going gonna wanna gotta also already always another back
come comes doesnt dont didnt isnt wasnt cant wont youre were theyre ive weve youve lets thats heres theres whats
music applause laughter""".split())


RETRY_DAYS = 14
BLOCKED = "confirm you" + "’" + "re not a bot"


def wanted_ids():
    d = json.loads((ROOT / "videos.json").read_text())
    s_chans = {i for i, c in enumerate(d["channels"]) if c["t"] == "S"}
    by_ch = defaultdict(list)
    for v in d["videos"]:
        if v[2] in s_chans:
            by_ch[v[2]].append(v)
    ids = []
    for vids in by_ch.values():
        keep = {v[0] for v in sorted(vids, key=lambda v: -v[4])[:TOP_BY_VIEWS]}
        keep |= {v[0] for v in sorted(vids, key=lambda v: -v[5])[:NEWEST]}
        ids += sorted(keep)
    return ids


def compact(json3_path):
    """json3 subtitle events -> [[sec, text], ...] merged into ~20 s chunks."""
    ev = json.loads(Path(json3_path).read_text()).get("events", [])
    chunks, cur_t, cur = [], None, []
    for e in ev:
        txt = "".join(s.get("utf8", "") for s in e.get("segs") or []).replace("\n", " ").strip()
        if not txt:
            continue
        t = int(e.get("tStartMs", 0) / 1000)
        if cur_t is None:
            cur_t = t
        cur.append(txt)
        if t - cur_t >= 20:
            chunks.append([cur_t, re.sub(r"\s+", " ", " ".join(cur))]); cur_t, cur = None, []
    if cur:
        chunks.append([cur_t, re.sub(r"\s+", " ", " ".join(cur))])
    return chunks


def fetch_batch(ids):
    with tempfile.TemporaryDirectory() as tmp:
        cmd = YTDLP + ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en,en-orig",
                       "--sub-format", "json3", "--sleep-requests", "0.5", "--ignore-errors",
                       "-o", f"{tmp}/%(id)s.%(ext)s"] + [f"https://www.youtube.com/watch?v={i}" for i in ids]
        res = subprocess.run(cmd, capture_output=True, text=True)
        blocked = BLOCKED in res.stderr or "confirm you're not a bot" in res.stderr
        got = 0
        for i in ids:
            f = next((Path(tmp) / f"{i}.{lang}.json3" for lang in ("en", "en-orig") if (Path(tmp) / f"{i}.{lang}.json3").exists()), None)
            data = compact(f) if f else []
            if not data and blocked:
                continue          # don't record "no subtitles" for a video we were refused
            (OUT / f"{i}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            got += bool(data)
        return got, len(ids), blocked


def download():
    OUT.mkdir(exist_ok=True)
    ts = {v[0]: v[5] for v in json.loads((ROOT / "videos.json").read_text())["videos"]}
    recent = time.time() - RETRY_DAYS * 86400

    def needed(i):
        f = OUT / f"{i}.json"
        return not f.exists() or (f.stat().st_size <= 2 and (ts.get(i) or 0) > recent)

    todo = [i for i in wanted_ids() if needed(i)]
    todo.sort(key=lambda i: -(ts.get(i) or 0))       # newest first
    todo = todo[:int(os.environ.get("MAX_NEW", len(todo)))]
    print(f"{len(todo)} transcripts to fetch", flush=True)
    batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
    done, got_all = 0, 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for got, n, blocked in ex.map(fetch_batch, batches):
            done += n; got_all += got
            print(f"  {done}/{len(todo)} (+{got} with subtitles){'  BLOCKED by YouTube' if blocked else ''}", flush=True)
    print(f"downloaded {got_all} new transcripts", flush=True)


def build():
    docs, per_doc = [], []
    for f in sorted(OUT.glob("*.json")):
        chunks = json.loads(f.read_text())
        if not chunks:
            continue
        first, tf = {}, Counter()
        for sec, text in chunks:
            for w in re.findall(r"[a-z][a-z0-9+#.-]*[a-z0-9+#]|[a-z]", text.lower()):
                if len(w) < 3 or w in STOP:
                    continue
                tf[w] += 1
                first.setdefault(w, sec)
        docs.append(f.stem); per_doc.append((tf, first))
    n = len(docs)
    df = Counter(w for tf, _ in per_doc for w in tf)
    terms = defaultdict(list)
    for di, (tf, first) in enumerate(per_doc):
        # keep each video's most distinctive words (tf-idf), skipping words that appear almost everywhere
        scored = sorted(((c * math.log(n / df[w]), w) for w, c in tf.items() if df[w] < 0.5 * n), reverse=True)
        for _, w in scored[:TERMS_PER_VIDEO]:
            terms[w].append([di, first[w]])
    out = {"docs": docs, "terms": dict(sorted(terms.items()))}
    (ROOT / "search.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"search.json: {n} transcripts, {len(terms)} terms, "
          f"{sum(len(p) for p in terms.values())} postings, {(ROOT / 'search.json').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    if "--build" not in sys.argv:
        download()
    build()
