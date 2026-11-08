# Nerdvana

~30,000 nerdy videos from 100 popular tech YouTube channels — programming, AI, hardware, security, science and engineering — in one fast, searchable page. Plus a **TV mode** for laid-back watching.

**Live:** https://geenccmustafa.github.io/nerdvana/

Inspired by Andrej Karpathy's [TristanTube](https://karpathy.ai/tristan-tube/).

## Features

**Find something to watch**
- **Sidebar**: Home, Top picks, New this week, Learning paths, I have X minutes, Watch later and History, plus every channel (with its avatar) grouped by tier: Essential, Great, Worth a look
- **Search titles and transcripts**: matches in what is *said* in a video show up with a timestamp and jump straight to that moment (Essential channels)
- **Learning paths**: short, ordered playlists that take one topic from zero to solid (Kubernetes, how computers work, neural networks to LLMs, system design, networking, security)
- **I have X minutes**: pick 5–60 minutes and get unwatched videos that fit, ready to play back to back
- **New this week**: the latest uploads from all channels
- **Mix** sort (default): a channel-balanced shuffle, so no single channel floods the feed

**Watch**
- **Watch page** with **More like this** (videos on the same topic from other channels) and an Up next list with autoplay
- **Continue watching**: picks up where you left off
- **Watch later** list, **Surprise me** button, and **TV mode** (full screen, auto-advancing; `→` next, `←` previous, `C` subtitles, `Esc` exit)
- **Shareable links** for every video (optionally at a timestamp), channel, path and view, e.g. `#v=VIDEO_ID&t=90`, `#c=veritasium`, `#path=kubernetes`

Watched, saved and in-progress videos are stored only in your browser. Light and dark themes.

## How it works

| File | What it is |
|---|---|
| `channels.json` | The channel list: handle, tier and topic. This is the part to edit. |
| `fetch.py` | Pulls every channel's uploads with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no API key) and writes `videos.json`. |
| `enrich.py` | Embeds every title with [bge-small](https://huggingface.co/BAAI/bge-small-en-v1.5) and writes `similar.json` (More like this) and `paths.json` (learning paths from `paths_def.json`). |
| `transcripts.py` | Downloads English subtitles for the Essential channels and writes `search.json`, a compact word index with timestamps. |
| `index.html` | The whole site: one file, no build step, no dependencies. |

### Balancing rules

So that prolific channels (daily uploaders, conference archives) can't drown out the rest:

- only channels with **≥ 250K subscribers**, at most **100** of them (picked by tier, then subscribers)
- each channel keeps at most its **300 most-viewed + 100 newest** videos
- Shorts (≤ 60 s) are dropped

## Update the data

A GitHub Action ([`refresh.yml`](.github/workflows/refresh.yml)) runs nightly at 03:17 UTC: it re-fetches every channel, rebuilds `similar.json` and `paths.json`, and commits the result, which redeploys the site. It refuses to publish if fewer than 95 channels or less than 90% of the previous videos come back (e.g. if YouTube blocks the runner). You can also start it by hand from the Actions tab.

Transcripts are refreshed by hand, because downloading thousands of subtitle files from a CI runner gets rate-limited.

Locally you need Python 3 and [uv](https://docs.astral.sh/uv/):

```bash
python3 fetch.py           # fetch new channels, rebuild videos.json
python3 fetch.py --force   # re-fetch every channel (picks up new uploads)
uv run --python 3.12 --with fastembed --with numpy python enrich.py   # similar.json + paths.json
python3 transcripts.py     # download missing transcripts, rebuild search.json
```

Run locally:

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

## Suggest a channel

Know a great channel that's missing? [Open a suggestion](https://github.com/GeenccMustafa/nerdvana/issues/new?template=suggest-channel.yml).

Tiers are one person's opinion. Fork it and make your own.
