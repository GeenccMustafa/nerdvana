"""Build similar.json ("More like this") and paths.json (learning paths) from videos.json.

Run after fetch.py, with Python 3.10-3.13 (onnxruntime has no wheels for newer versions yet):
  uv run --python 3.12 --with fastembed --with numpy enrich.py

Video titles are embedded with BAAI/bge-small-en-v1.5. Embeddings are cached in .cache/ by video id,
so re-runs only embed new videos.

similar.json  {"n": video count, "first": first video id, "sim": [[video index, ...] x 8 per video]}
              aligned with the order of videos.json; the page checks n/first before using it
paths.json    [{id, title, blurb, videos: [video id, ...]}] resolved from paths_def.json

If articles.json exists, articles (title + description) are embedded the same way:
similar_articles.json  {"n", "first", "sim": [[article index, ...] x 8]}  aligned with articles.json
links.json             videos <-> articles on the same topic:
                       {"vn", "vfirst", "an", "afirst", "v2a": [[article index, ...]], "a2v": [[video index, ...]]}
"""
import json, math
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "emb.npz"
MODEL = "BAAI/bge-small-en-v1.5"
SIMILAR = 8
MAX_SAME_CHANNEL = 3
LINK_THRESHOLD = 0.8


def embed(texts, model, cache_file):
    """texts: {id: text}. Returns normalized vectors in the order of texts; caches by id."""
    cached = {}
    if cache_file.exists():
        z = np.load(cache_file)
        cached = dict(zip(z["ids"].tolist(), z["vecs"]))
    todo = [i for i in texts if i not in cached]
    if todo:
        print(f"embedding {len(todo)} new texts…", flush=True)
        for i, vec in zip(todo, model.embed([texts[i] for i in todo], batch_size=256)):
            cached[i] = vec.astype(np.float32)
    cache_file.parent.mkdir(exist_ok=True)
    ids = list(texts)
    E = np.stack([cached[i] for i in ids])
    np.savez(cache_file, ids=np.array(ids), vecs=E)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


def embed_titles(videos, channels, model):
    return embed({v[0]: f"{v[1]} ({channels[v[2]]['topic']})" for v in videos}, model, CACHE)


def cross_links(A, B, k, threshold, allowed=None):
    """For each row of A, up to k rows of B that are about the same thing (cosine >= threshold)."""
    out = []
    for start in range(0, len(A), 2048):
        S = A[start:start + 2048] @ B.T
        if allowed is not None:
            S[:, ~allowed] = -1
        top = np.argpartition(-S, k, axis=1)[:, :k]
        for r in range(S.shape[0]):
            cand = top[r][np.argsort(-S[r, top[r]])]
            out.append([int(j) for j in cand if S[r, j] >= threshold])
    return out


def build_similar(E, videos):
    n, ch = len(videos), np.array([v[2] for v in videos])
    titles = [v[1].lower() for v in videos]
    out = []
    for start in range(0, n, 2048):
        S = E[start:start + 2048] @ E.T
        top = np.argpartition(-S, 60, axis=1)[:, :60]
        for r in range(S.shape[0]):
            i = start + r
            cand = top[r][np.argsort(-S[r, top[r]])]
            picked, per = [], {}
            for j in cand:
                j = int(j)
                if j == i or titles[j] == titles[i]:
                    continue
                if per.get(ch[j], 0) >= MAX_SAME_CHANNEL:
                    continue
                per[ch[j]] = per.get(ch[j], 0) + 1
                picked.append(j)
                if len(picked) == SIMILAR:
                    break
            out.append(picked)
    return {"n": n, "first": videos[0][0], "sim": out}


def build_paths(E, videos, channels, model):
    defs = json.loads((ROOT / "paths_def.json").read_text())
    ok = np.array([channels[v[2]]["t"] in ("S", "A") and v[4] >= 50_000 and 120 <= v[3] <= 10800 for v in videos])
    boost = np.array([0.025 * math.log10(max(v[4], 1)) for v in videos])
    out = []
    for p in defs:
        Q = np.stack(list(model.embed([f"Represent this sentence for searching relevant passages: {s}" for s in p["steps"]])))
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        used, per_ch, picked = set(), {}, []
        for q in Q:
            score = E @ q + boost - np.array([0.04 * per_ch.get(v[2], 0) for v in videos])
            score[~ok] = -9
            for j in np.argsort(-score)[:50]:
                j = int(j)
                if j not in used:
                    used.add(j); per_ch[videos[j][2]] = per_ch.get(videos[j][2], 0) + 1
                    picked.append(videos[j][0]); break
        out.append({"id": p["id"], "title": p["title"], "blurb": p["blurb"], "videos": picked})
        print(f"  path {p['title']}: " + " | ".join(videos[[v[0] for v in videos].index(x)][1][:40] for x in picked))
    return out


if __name__ == "__main__":
    data = json.loads((ROOT / "videos.json").read_text())
    videos, channels = data["videos"], data["channels"]
    model = TextEmbedding(MODEL)
    E = embed_titles(videos, channels, model)
    sim = build_similar(E, videos)
    (ROOT / "similar.json").write_text(json.dumps(sim, separators=(",", ":")))
    print(f"similar.json: {len(sim['sim'])} videos, {(ROOT / 'similar.json').stat().st_size / 1e6:.1f} MB")
    paths = build_paths(E, videos, channels, model)
    (ROOT / "paths.json").write_text(json.dumps(paths, ensure_ascii=False, indent=1))
    print(f"paths.json: {len(paths)} paths")

    if (ROOT / "articles.json").exists():
        ad = json.loads((ROOT / "articles.json").read_text())
        arts, srcs = ad["articles"], ad["sources"]
        A = embed({a[0]: f"{a[1]}. {a[7]} ({srcs[a[2]]['topic']})" for a in arts}, model, ROOT / ".cache" / "emb_articles.npz")
        sa = build_similar(A, arts)
        (ROOT / "similar_articles.json").write_text(json.dumps(sa, separators=(",", ":")))
        print(f"similar_articles.json: {len(sa['sim'])} articles")
        # only link to videos worth a detour: Essential/Great channels with some views
        good_v = np.array([channels[v[2]]["t"] in ("S", "A") and v[4] >= 20_000 and v[3] >= 120 for v in videos])
        links = {"vn": len(videos), "vfirst": videos[0][0], "an": len(arts), "afirst": arts[0][0],
                 "v2a": cross_links(E, A, 3, LINK_THRESHOLD), "a2v": cross_links(A, E, 4, LINK_THRESHOLD, good_v)}
        (ROOT / "links.json").write_text(json.dumps(links, separators=(",", ":")))
        print(f"links.json: {sum(map(bool, links['v2a']))} videos with articles, "
              f"{sum(map(bool, links['a2v']))} articles with videos, {(ROOT / 'links.json').stat().st_size / 1e6:.1f} MB")
