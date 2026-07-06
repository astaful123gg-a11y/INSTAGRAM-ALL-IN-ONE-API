import os
import re
import json
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

app = FastAPI(title="Instagram Download + Search API")

API_PASSWORD = "SHUVO-apis"
IG_APP_ID = "936619743392459"   # Instagram's public web app id, used by every browser session

_cookies_file = os.path.join(os.path.dirname(__file__), "cookies.json")
with open(_cookies_file) as f:
    COOKIES = json.load(f)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "X-IG-App-ID": IG_APP_ID,
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
}
if "csrftoken" in COOKIES:
    HEADERS["X-CSRFToken"] = COOKIES["csrftoken"]

SESSION = requests.Session()
SESSION.cookies.update(COOKIES)
SESSION.headers.update(HEADERS)

_follower_cache = {}   # username -> follower count (avoid refetching within a run)


def check_auth(x_api_key: str = Header(default=None)):
    if x_api_key != API_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class UrlRequest(BaseModel):
    url: str


@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "Instagram Download + Search API",
        "auth": "Header X-API-Key: SHUVO-apis (required on all /api/* routes)",
        "endpoints": {
            "download": {"method": "POST", "path": "/api/download", "body": {"url": "post/reel link"}, "note": "returns ALL media items in the post as direct urls"},
            "search (/search)": {"method": "POST", "path": "/api/search", "body": {"query": "hashtag/keyword", "limit": 10}, "note": "videos/reels only"},
            "psearch (/psearch)": {"method": "POST", "path": "/api/psearch", "body": {"query": "hashtag/keyword", "limit": 10}, "note": "photo posts only"},
        },
    }


def shortcode_to_media_id(shortcode):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + alphabet.index(char)
    return media_id


def extract_shortcode(url):
    m = re.search(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    return m.group(1)


def get_follower_count(username):
    if username in _follower_cache:
        return _follower_cache[username]
    try:
        r = SESSION.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": username},
            timeout=15,
        )
        data = r.json()
        count = data.get("data", {}).get("user", {}).get("edge_followed_by", {}).get("count")
        _follower_cache[username] = count
        return count
    except Exception:
        return None


def format_date(unix_ts):
    if not unix_ts:
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- /download

@app.post("/api/download", dependencies=[Depends(check_auth)])
def download(req: UrlRequest):
    shortcode = extract_shortcode(req.url)
    if not shortcode:
        raise HTTPException(status_code=400, detail="Could not parse a post/reel shortcode from that link")

    media_id = shortcode_to_media_id(shortcode)

    try:
        r = SESSION.get(f"https://i.instagram.com/api/v1/media/{media_id}/info/", timeout=20)
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Instagram fetch failed: {e}")

    items = data.get("items")
    if not items:
        raise HTTPException(status_code=400, detail=f"Post not found or private: {data.get('message', '')}")

    post = items[0]
    media_list = []

    carousel = post.get("carousel_media")
    slides = carousel if carousel else [post]

    for slide in slides:
        if slide.get("video_versions"):
            best = max(slide["video_versions"], key=lambda v: v.get("width", 0))
            media_list.append({"type": "video", "url": best["url"]})
        elif slide.get("image_versions2", {}).get("candidates"):
            best = max(slide["image_versions2"]["candidates"], key=lambda c: c.get("width", 0))
            media_list.append({"type": "image", "url": best["url"]})

    if not media_list:
        raise HTTPException(status_code=400, detail="No downloadable media found in this post")

    caption = (post.get("caption") or {}).get("text", "") if post.get("caption") else ""

    return {
        "shortcode": shortcode,
        "owner": post.get("user", {}).get("username"),
        "caption": caption,
        "count": len(media_list),
        "media": media_list,
    }


# ---------------------------------------------------------------- /search and /psearch (hashtag-based)

def _hashtag_search(query, limit, want_video):
    tag = re.sub(r"[^a-zA-Z0-9_]", "", query.replace(" ", ""))
    if not tag:
        raise HTTPException(status_code=400, detail="Invalid search query")

    try:
        r = SESSION.get(
            "https://i.instagram.com/api/v1/tags/web_info/",
            params={"tag_name": tag},
            timeout=20,
        )
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Instagram search failed: {e}")

    sections = (
        data.get("data", {}).get("recent", {}).get("sections")
        or data.get("data", {}).get("top", {}).get("sections")
        or []
    )

    results = []
    for section in sections:
        for item in section.get("layout_content", {}).get("medias", []):
            media = item.get("media", {})
            is_video = media.get("media_type") == 2 or bool(media.get("video_versions"))
            if want_video and not is_video:
                continue
            if not want_video and is_video:
                continue

            username = media.get("user", {}).get("username")
            like_count = media.get("like_count")
            view_count = media.get("view_count") or media.get("play_count") if is_video else None
            upload_date = format_date(media.get("taken_at"))
            followers = get_follower_count(username) if username else None

            media_url = None
            if is_video and media.get("video_versions"):
                best = max(media["video_versions"], key=lambda v: v.get("width", 0))
                media_url = best["url"]
            elif media.get("image_versions2", {}).get("candidates"):
                best = max(media["image_versions2"]["candidates"], key=lambda c: c.get("width", 0))
                media_url = best["url"]

            shortcode = media.get("code")
            results.append({
                "shortcode": shortcode,
                "url": f"https://www.instagram.com/p/{shortcode}/" if shortcode else None,
                "media_type": "video" if is_video else "image",
                "media_url": media_url,
                "channel_name": username,
                "channel_followers": followers,
                "like_count": like_count,
                "view_count": view_count,
                "upload_date": upload_date,
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results[:limit]


@app.post("/api/search", dependencies=[Depends(check_auth)])
def search(req: SearchRequest):
    results = _hashtag_search(req.query, req.limit, want_video=True)
    return {"query": req.query, "type": "video", "count": len(results), "results": results}


@app.post("/api/psearch", dependencies=[Depends(check_auth)])
def psearch(req: SearchRequest):
    results = _hashtag_search(req.query, req.limit, want_video=False)
    return {"query": req.query, "type": "photo", "count": len(results), "results": results}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
