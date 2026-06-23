import json
import os
import time
import datetime
import hashlib
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

ENDPOINT = os.environ.get("TELEMETRY_ENDPOINT")
BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
SOURCES_RAW = os.environ.get("DATA_SOURCES")
BOT_NAME = os.environ.get("BOT_NAME", "System Monitor")
PING_ROLE = os.environ.get("PING_ROLE", "")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

SOURCES = []
if SOURCES_RAW and BASE_URL:
    slugs = [s.strip() for s in SOURCES_RAW.split(",") if s.strip()]
    for slug in slugs:
        needs_ping = False
        if slug.endswith("*"):
            needs_ping = True
            slug = slug[:-1].strip()
        c_name = slug.replace("-", " ").title()
        c_url = f"{BASE_URL}/{slug}"
        SOURCES.append({"name": c_name, "url": c_url, "ping": needs_ping})

def get_gist_state():
    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    url = f"https://api.github.com/gists/{GIST_ID}"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return json.loads(res.json()["files"]["comicUpdate.json"]["content"])
    except Exception:
        pass
    return {}

def update_gist_state(state):
    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = {"files": {"comicUpdate.json": {"content": json.dumps(state, indent=4)}}}
    try:
        requests.patch(url, headers=headers, json=payload, timeout=15)
    except Exception:
        pass

def process_node(url, page):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(10)
        
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        page_title = soup.title.text.strip() if soup.title else "Tanpa Judul"
        
        if "Just a moment" in page_title or "Cloudflare" in page_title:
            return None, f"Playwright terjegal Cloudflare. (Title: {page_title[:40]})"

        target_link = None
        title = ""
        
        for a in soup.find_all("a", href=True):
            if "/reader/" in a["href"]:
                h3 = a.find("h3")
                title = h3.text.strip() if h3 else a.get_text(separator=' ', strip=True)
                
                if title and any(char.isdigit() for char in title):
                    target_link = a
                    break

        if not target_link:
            body_text = soup.body.text.strip().replace('\n', ' ') if soup.body else "No Body"
            return None, f"Link Node Kosong. T:{page_title[:20]} | B:{body_text[:60]}"
            
        link = target_link["href"]
        if link.startswith('/'):
            parsed = urlparse(url)
            link = f"{parsed.scheme}://{parsed.netloc}{link}"
            
        return (title.strip(), link), None
    except Exception as e:
        return None, str(e)[:150]

def dispatch(comic_name, chapter_title, link, needs_ping):
    content_text = PING_ROLE if needs_ping else ""
    embed = {
        "title": f"📖 {comic_name}",
        "description": f"**{chapter_title}**\n\n[➡️ Baca Chapter Terbaru Disini]({link})",
        "color": 3447003,
        "footer": {"text": BOT_NAME},
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    payload = {"content": content_text, "embeds": [embed], "username": BOT_NAME}
    try:
        requests.post(ENDPOINT, json=payload, timeout=15)
    except Exception:
        pass

def dispatch_error(node_id, error_msg):
    embed = {
        "title": f"⚠️ System Alert: {node_id} Failure",
        "description": f"**Error Detail:**\n`{error_msg}`\n\nSistem gagal melakukan sinkronisasi otomatis pada node ini.",
        "color": 15158332,
        "footer": {"text": BOT_NAME},
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    payload = {"content": "", "embeds": [embed], "username": BOT_NAME}
    try:
        requests.post(ENDPOINT, json=payload, timeout=15)
    except Exception:
        pass

def main():
    if not ENDPOINT or not SOURCES or not GIST_ID or not GIST_TOKEN:
        return

    state = get_gist_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for idx, src in enumerate(SOURCES, 1):
            node_key = f"Checking Update #{idx}"
            c_name = src["name"]
            c_url = src["url"]
            c_ping = src["ping"]
            
            result, error_msg = process_node(c_url, page)
            old_value = state.get(node_key, "")
            
            if error_msg:
                error_hash = hashlib.md5(f"[ERROR] {error_msg}".encode()).hexdigest()
                if old_value != error_hash:
                    dispatch_error(node_key, error_msg)
                    state[node_key] = error_hash
            else:
                title, link = result
                title_hash = hashlib.md5(title.encode()).hexdigest()
                if old_value != title_hash:
                    dispatch(c_name, title, link, c_ping)
                    state[node_key] = title_hash
            
            time.sleep(5)

        browser.close()

    state["_last_run"] = int(time.time())
    update_gist_state(state)

if __name__ == "__main__":
    main()
