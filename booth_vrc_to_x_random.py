# BOOTH「VRChat」タグからランダム抽選 → テキスト＋リンクでXに自動投稿（Freeプラン）
# 人間味UP：テンプレゆらぎ＋絵文字＋価格/ショップ名補完＋タグローテ
# 依存: pip install tweepy requests beautifulsoup4
import os, re, json, time, logging, random
import requests
from bs4 import BeautifulSoup
import tweepy

# ====== 設定 ======
BASE_URL = "https://booth.pm/ja/search/VRChat?sort=new&in_stock=true"
PAGES_TO_SCRAPE = 5
SAMPLE_SIZE = 1
AVOID_REPEAT_DAYS = 14
SLEEP_BETWEEN_POSTS_SEC = 2
STATE_FILE = "random_seen.json"

# X 認証
API_KEY = os.environ.get("X_API_KEY")
API_SECRET = os.environ.get("X_API_SECRET")
ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

HEADERS = {"User-Agent": "Mozilla/5.0 (+bot contact: youremail@example.com)"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# テンプレ
TEMPLATES = [
    "🎲 ランダム発掘 [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "🆕 いまの気分でコレ [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "👀 ちょい見せピック [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "✨ 今日のおすすめ [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
]
BASE_TAGS = ["#VRChat", "#booth_pm"]
EXTRA_TAGS_POOL = ["#3Dモデル", "#VRoid", "#アバター", "#ワールド", "#衣装", "#小物"]
EMOJI_TAILS = ["！", "‼️", "〜", "♪", "⭐", "💫", " "]

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
        if not m:
            continue
        item_id = int(m.group(1))
        title = a.get_text(strip=True) or "BOOTH item"
        url = "https://booth.pm" + href if href.startswith("/") else href
        items.append({"id": item_id, "title": title, "url": url})
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

def enrich_item_info(item:dict) -> dict:
    """個別ページを開き、価格とショップ名を補完（失敗してもそのまま返す）"""
    try:
        r = requests.get(item["url"], headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # 価格候補（BOOTHは itemprop="price" が多い。fallbackも用意）
        price_tag = soup.find("span", {"itemprop": "price"}) or soup.select_one("[data-item-price], .price")
        price_text = None
        if price_tag:
            price_text = price_tag.get_text(" ", strip=True)
        if not price_text:
            # テキスト全体から拾う保険
            m = re.search(r"¥\s?[\d,]+", soup.get_text(" ", strip=True))
            price_text = m.group(0) if m else None
        if price_text:
            item["price"] = "（" + price_text.replace(" ", "") + "）"

        # ショップ名（og:site_name または作者リンク）
        shop = None
        og = soup.find("meta", {"property": "og:site_name"})
        if og and og.get("content"):
            shop = og["content"].strip()
        if not shop:
            author = soup.select_one("a[href*='/profiles/']")
            if author:
                shop = author.get_text(strip=True)
        if shop:
            item["shop"] = f"by {shop}"
    except Exception as e:
        logging.debug("enrich_item_info failed: %s", e)
    return item

def build_tags():
    tags = BASE_TAGS[:]
    if random.random() < 0.4:
        tags.append(random.choice(EXTRA_TAGS_POOL))
    return " ".join(tags)

def shorten(text:str, n:int):
    return (text[:n] + "…") if len(text) > n else text

def build_text(item):
    title = shorten(item["title"], 80) + random.choice(EMOJI_TAILS)
    price = item.get("price", "")
    shop = " " + item["shop"] if item.get("shop") else ""
    tags = build_tags()
    template = random.choice(TEMPLATES)
    body = template.format(title=title, price=price, shop=shop, url=item["url"], tags=tags)
    if len(body) > 275:
        title2 = shorten(title, 60)
        body = template.format(title=title2, price=price, shop=shop, url=item["url"], tags=tags)
    return body

def get_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
        wait_on_rate_limit=True,
    )

def main():
    # 認証チェック
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
    pool = [it for it in candidates if it["id"] not in seen_ids] or candidates

    random.seed(time.time())
    picks = random.sample(pool, min(SAMPLE_SIZE, len(pool)))

    client = get_client_v2()
    posted = 0
    for it in picks:
        # ★ ここで価格・ショップ名を補完
        it = enrich_item_info(it)

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
