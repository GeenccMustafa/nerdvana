# Nerdvana

~30,000 nerdy videos from 100 popular tech YouTube channels — programming, AI, hardware, security, science and engineering — in one fast, searchable page. Plus a **TV mode** for laid-back watching.

**Live:** https://geenccmustafa.github.io/nerdvana/

Inspired by Andrej Karpathy's [TristanTube](https://karpathy.ai/tristan-tube/).

## Features

- **Sidebar** with Home, Top picks and History, plus every channel (with its avatar) grouped by tier: Essential, Great, Worth a look
- **Watch page** with an "Up next" list and autoplay, and a **Surprise me** button for a random unwatched video
- Search across every title, filter by topic and length
- **Mix** sort (default): a channel-balanced shuffle, so no single channel floods the feed
- **TV mode**: full-screen, auto-advancing playback of whatever you have filtered, unwatched first
  - `→` next, `←` previous, `C` subtitles on/off, `Esc` exit
- Watched videos are remembered in your browser; hide them with one click
- Light and dark themes

## How it works

| File | What it is |
|---|---|
| `channels.json` | The channel list: handle, tier and topic. This is the part to edit. |
| `fetch.py` | Pulls every channel's uploads with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no API key) and writes `videos.json`. |
| `videos.json` | The generated dataset the page loads. |
| `index.html` | The whole site: one file, no build step, no dependencies. |

### Balancing rules

So that prolific channels (daily uploaders, conference archives) can't drown out the rest:

- only channels with **≥ 250K subscribers**, at most **100** of them (picked by tier, then subscribers)
- each channel keeps at most its **300 most-viewed + 100 newest** videos
- Shorts (≤ 60 s) are dropped

## Update the data

A GitHub Action ([`refresh.yml`](.github/workflows/refresh.yml)) re-fetches every channel nightly at 03:17 UTC and commits the new `videos.json`, which redeploys the site. It refuses to publish if fewer than 95 channels or less than 90% of the previous videos come back (e.g. if YouTube blocks the runner). You can also start it by hand from the Actions tab.

To update locally instead you need Python 3 and [uv](https://docs.astral.sh/uv/):

```bash
python3 fetch.py           # fetch new channels, rebuild videos.json
python3 fetch.py --force   # re-fetch every channel (picks up new uploads)
python3 fetch.py --build   # rebuild videos.json from the cached raw/ data only
```

Run locally:

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

Tiers are one person's opinion. Fork it and make your own.
