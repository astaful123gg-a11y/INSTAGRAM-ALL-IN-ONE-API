# Instagram Download + Search API

Uses Instagram's internal (unofficial) mobile-web endpoints with your logged-in
session cookies. No official public API covers this, so this mimics what the
Instagram app/website itself calls internally.

## Auth
All `/api/*` calls need header:
```
X-API-Key: SHUVO-apis
```

## /download — different from the other APIs
Unlike TikTok/YouTube (which return a raw file), Instagram posts can have
**multiple photos/videos in one post** (carousel). So `/download` returns JSON
with a direct URL per item — send them all as-is (Telegram can fetch by URL
directly, same as we did for Pinterest).

`POST /api/download`
```json
{"url": "https://www.instagram.com/p/POST_SHORTCODE/"}
```
Response:
```json
{
  "shortcode": "...", "owner": "username", "caption": "...",
  "count": 5,
  "media": [
    {"type": "image", "url": "..."},
    {"type": "video", "url": "..."}
  ]
}
```
Works with `/p/`, `/reel/`, and `/reels/` links. If the post has 1 photo, `count` is 1.
If it has 10, `count` is 10 — all of them come back.

## /search — videos/reels only
`POST /api/search`
```json
{"query": "cats", "limit": 10}
```
Response per result: `shortcode, url, channel_name, channel_followers, like_count, view_count, upload_date`.

Note: Instagram doesn't have free-text search across all content — this searches
by **hashtag**, so `query` is treated as a hashtag (spaces/symbols stripped).

## /psearch — photo posts only
Same as `/search` but filters for photo posts instead of video/reels.
`view_count` will usually be `null` here since Instagram doesn't expose view
counts for plain photos.

## Setup
1. `pip install -r requirements.txt`
2. `cookies.json` already included (session cookies).
3. Run: `python main.py`

## Deploy on Render
Push to a **private** repo (cookies.json has your session token).
Build: `pip install -r requirements.txt`
Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Note
This is scraping Instagram's internal API — same caveat as Pinterest/TikTok:
if Instagram changes their internal endpoint shape or the session (`sessionid`)
expires, re-export cookies.json the same way as before. Hashtag search results
can also vary in completeness since Instagram doesn't guarantee full recall here.
