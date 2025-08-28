# BOOTH「VRChat」タグからランダム抽選 → テキスト＋リンクでXに自動投稿（Freeプラン）
# “人間味”アップ：可変テンプレ、絵文字、価格・ショップ名、軽いハッシュタグローテ
# 依存: pip install tweepy requests beautifulsoup4
import os, re, json, time, logging, random
import requests
from bs4 import BeautifulSoup
import tweepy

# ====== 設定 ======
BASE_URL = "https://booth.pm/ja/search/VRChat?sort=new&in_stock=true"
PAGES_TO_SCRAPE = 5
SAMPLE_SIZE = 1             # 45分に1本など想定なので1件で十分
AVOID_REPEAT_DAYS = 14
SLEEP_BETWEEN_POSTS_SEC = 2
STATE_FILE = "random_seen.json"

# X 認証（v2 ユーザーコンテキスト）
API_KEY = os.environ.get("X_API_KEY")
API_SECRET = os.environ.get("X_API_SECRET")
ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

HEADERS = {"User-Agent": "Mozilla/5.0 (+bot contact: youremail@example.com)"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 文面テンプレ（{title} {price} {shop} {url} を差し込み／shopは取れた時のみ）
TEMPLATES = [
    "🎲 ランダム発掘 [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "🆕 いまの気分でコレ [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "👀 ちょい見せピック [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
    "✨ 今日のおすすめ [VRChat]\n{title}{price} {shop}\n{url}\n{tags}",
]

# タグは固定 + たまに1個だけ追加（入れ替え）
BASE_TAGS = ["#VRChat", "#booth_pm"]
EXTRA_TAGS_POOL = ["#3Dモデル", "#VRoid", "#アバター", "#ワールド", "#衣装", "#小物"]

EMOJI_TAILS = ["！", "‼️", "〜", "♪", "⭐", "💫", " "]  # 語尾ゆらぎ

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

def fetch_shop_name(item_url:str) -> str | None:
    """個別ページを1回だけ叩いてショップ名らしき文字を拾う（失敗してもOK）"""
    try:
        r = requests.get(item_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # ショップ名はパンくずや作者欄に出ることが多い
        # まず meta og:site_name を試す
        og = soup.find("meta", {"property": "og:site_name"})
        if og and og.get("content"):
            txt = og["content"].strip()
            if txt:
                return f"by {txt}"
        # 代替：作者リンク
        author = soup.select_one("a[href*='/profiles/']")
        if author:
            t = author.get_text(strip=True)
            if t:
                return f"by {t}"
    except Exception as e:
        logging.debug("shop fetch fail: %s", e)
    return None

def build_tags():
    tags = BASE_TAGS[:]
    # 40%くらいの確率で1個だけ追加タグ
    if random.random() < 0.4:
        tags.append(random.choice(EXTRA_TAGS_POOL))
    return " ".join(tags)

def shorten(text:str, n:int):
    return (text[:n] + "…") if len(text) > n else text

def build_text(item):
    title = shorten(item["title"], 80)
    price = f"（{item['price']}）" if item.get("price") else ""
    shop = fetch_shop_name(item["url"])
    shop_part = f"{shop}" if shop else ""
    tail = random.choice(EMOJI_TAILS)
    tags = build_tags()
    template = random.choice(TEMPLATES)
    body = template.format(title=title+tail, price=price, shop=(" " + shop_part if shop_part else ""), url=item["url"], tags=tags)
    # 文字数セーフティ
    if len(body) > 275:
        title2 = shorten(title, 60)
        body = template.format(title=title2+tail, price=price, shop=(" " + shop_part if shop_part else ""), url=item["url"], tags=tags)
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
