# BOOTH「VRChat」タグからランダム抽選 → テキスト＋リンクでXに自動投稿（Freeプラン対応）
# 投稿末尾に #VRChat #booth_pm を追加
# 依存: pip install tweepy requests beautifulsoup4

import os, re, json, time, logging, random
import requests
from bs4 import BeautifulSoup
import tweepy

# === 設定 ===
BASE_URL = "https://booth.pm/ja/search/VRChat?sort=new&in_stock=true"
PAGES_TO_SCRAPE = 5          # 何ページ分を候補にするか
SAMPLE_SIZE = 2              # 1回の巡回で何件ポストするか
AVOID_REPEAT_DAYS = 14       # この日数以内にツイート済みのIDは避ける
SLEEP_BETWEEN_POSTS_SEC = 2  # 連投防止の間隔

STATE_FILE = "random_seen.json"

# X 認証（v2 ユーザーコンテキスト）
API_KEY = os.environ.get("X_API_KEY")
API_SECRET = os.environ.get("X_API_SECRET")
ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

HEADERS = {"User-Agent": "Mozilla/5.0 (+bot contact: youremail@example.com)"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def prune_state(state, days=AVOID_REPEAT_DAYS):
    cutoff = time.time() - days * 86400
    for k in list(state.keys()):
        if state[k] < cutoff:
            del state[k]

def fetch_items_from_page(page:int):
    url = BASE_URL + f"&page={page}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    items = []
    for a in soup.select("a[href*='/items/']"):
        href = a.get("href") or ""
        m = re.search(r"/items/(\d+)", href)
        if not m: continue
        item_id = int(m.group(1))
        title = a.get_text(strip=True) or "BOOTH item"
        url = "https://booth.pm" + href if href.startswith("/") else href

        # 価格
        price = None
        p = a.parent
        if p:
            txt = p.get_text(" ", strip=True)
            m2 = re.search(r"¥\s?[\d,]+", txt)
            price = m2.group(0) if m2 else None
        items.append({"id": item_id, "title": title, "url": url, "price": price})
    return items

def collect_candidates(pages=PAGES_TO_SCRAPE):
    all_items = []
    for i in range(1, pages+1):
        try:
            all_items.extend(fetch_items_from_page(i))
        except Exception as e:
            logging.warning("page %s fetch failed: %s", i, e)
    uniq = {it["id"]: it for it in all_items}
    return list(uniq.values())

def build_text(item):
    title = item["title"]
    price = f"（{item['price']}）" if item.get("price") else ""
    base = f"🎲 BOOTHランダム [VRChat]\n{title}{price}\n{item['url']}\n#VRChat #booth_pm"
    if len(base) <= 270:
        return base
    short_title = (title[:80] + "…") if len(title) > 80 else title
    return f"🎲 BOOTHランダム [VRChat]\n{short_title}{price}\n{item['url']}\n#VRChat #booth_pm"

def get_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
        wait_on_rate_limit=True,
    )

def main():
    for k, v in {"X_API_KEY": API_KEY, "X_API_SECRET": API_SECRET,
                 "X_ACCESS_TOKEN": ACCESS_TOKEN, "X_ACCESS_SECRET": ACCESS_SECRET}.items():
        if not v:
            raise SystemExit(f"環境変数 {k} を設定してください。")

    candidates = collect_candidates()
    if not candidates:
        logging.info("候補なし")
        return

    state = load_state()
    prune_state(state, AVOID_REPEAT_DAYS)
    seen_ids = set(map(int, state.keys()))
    fresh = [it for it in candidates if it["id"] not in seen_ids]
    pool = fresh if fresh else candidates

    random.seed(time.time())
    k = min(SAMPLE_SIZE, len(pool))
    picks = random.sample(pool, k)

    client = get_client_v2()
    posted = 0
    for it in picks:
        text = build_text(it)
        try:
            resp = client.create_tweet(text=text)
            tid = getattr(resp, "data", {}).get("id")
            logging.info("Post OK: id=%s | %s", tid, it["url"])
            state[str(it["id"])] = time.time()
            posted += 1
            time.sleep(SLEEP_BETWEEN_POSTS_SEC)
        except Exception as e:
            logging.error("Post NG: %s | %s", it["url"], e)

    save_state(state)
    logging.info("done. posted=%d", posted)

if __name__ == "__main__":
    main()
