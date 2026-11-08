"""Build similar.json ("More like this") and paths.json (learning paths) from videos.json.

Run after fetch.py, with Python 3.10-3.13 (onnxruntime has no wheels for newer versions yet):
  uv run --python 3.12 --with fastembed --with numpy enrich.py

Video titles are embedded with BAAI/bge-small-en-v1.5. Embeddings are cached in .cache/ by video id,
so re-runs only embed new videos.

similar.json  {"n": video count, "first": first video id, "sim": [[video index, ...] x 8 per video]}
              aligned with the order of videos.json; the page checks n/first before using it
paths.json    [{id, title, blurb, videos: [video id, ...]}] resolved from paths_def.json
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


def embed_titles(videos, channels, model):
    cached = {}
    if CACHE.exists():
        z = np.load(CACHE)
        cached = dict(zip(z["ids"].tolist(), z["vecs"]))
    texts = {v[0]: f"{v[1]} ({channels[v[2]]['topic']})" for v in videos}
    todo = [i for i in texts if i not in cached]
    if todo:
        print(f"embedding {len(todo)} new titles…", flush=True)
        for i, vec in zip(todo, model.embed([texts[i] for i in todo], batch_size=256)):
            cached[i] = vec.astype(np.float32)
    CACHE.parent.mkdir(exist_ok=True)
    ids = [v[0] for v in videos]
    E = np.stack([cached[i] for i in ids])
    np.savez(CACHE, ids=np.array(ids), vecs=E)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


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
