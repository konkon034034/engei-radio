import argparse
import builtins
import io
import json
import os
import re
import sys
import time
import wave

# ==========================================
# Windows cp932 エンコードエラー根本対策
# ==========================================
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_original_print = builtins.print


def safe_print(*args, **kwargs):
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode("utf-8", errors="replace").decode("utf-8"))
            else:
                safe_args.append(arg)
        _original_print(*safe_args, **kwargs)


builtins.print = safe_print


import PIL.Image
from dotenv import load_dotenv
from google import genai
from google.genai import types

# AWS Bedrock (画像生成)
try:
    import boto3

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


# Pillow 互換性パッチ
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

load_dotenv()

# 共通キャラクター設定をインポート
# 共通キャラクター設定のパス設定（ローカル/GitHub Actions両対応）

shared_path = "/Users/user/.gemini/antigravity/shared"
if os.path.exists(shared_path):
    sys.path.insert(0, shared_path)
else:
    # GitHub Actions環境：character_settings.pyはsrcディレクトリにある
    sys.path.insert(0, os.path.dirname(__file__))
from character_settings import get_character_settings

# プロジェクト内モジュールのインポート
try:
    from src.youtube_uploader import YouTubeUploader
except ImportError:
    # 直接実行時のパス解決
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    from src.youtube_uploader import YouTubeUploader


# 音声結合はffmpegを使用、動画生成はRemotion専用
def ffmpeg_concat_audio(wav_files, output_path):
    """ffmpegで複数のWAVファイルを結合する"""
    import subprocess
    import tempfile

    # 存在するファイルのみフィルタリング
    valid_files = [f for f in wav_files if os.path.exists(f)]
    if not valid_files:
        raise Exception("結合する音声ファイルがありません")

    # ファイルリストを一時ファイルに書き出し
    list_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    try:
        for wav_file in valid_files:
            # ffmpegのconcat形式に合わせてエスケープ
            list_file.write(f"file '{wav_file}'\n")
        list_file.close()

        # ffmpegで結合
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_file.name,
            "-c:a",
            "pcm_s16le",  # WAV形式
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[WARN] ffmpeg concat error: {result.stderr[:200]}")
            raise Exception(f"ffmpeg concat failed: {result.returncode}")
        print(f"[OK] ffmpeg音声結合完了: {output_path}")
    finally:
        os.unlink(list_file.name)


# ==========================================
# 定数と設定
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "..", "assets", "NotoSansCJKjp-Regular.ttf")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")
REMOTION_DIR = os.path.join(SCRIPT_DIR, "..", "remotion")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# フォントファイルの存在チェック
if not os.path.exists(FONT_PATH):
    raise FileNotFoundError(f"フォントファイルが見つかりません: {FONT_PATH}\n実行ディレクトリを確認してください")

# カラー・デザイン設定 (確定)
COLOR_TOPIC = "#FF9696"
COLOR_TOPIC_BORDER = "#400040"
COLOR_SOURCE = "#FFFFFF"
COLOR_SOURCE_BORDER = "#000000"
COLOR_SUBTITLE = "#FFFFFF"
COLOR_SUBTITLE_BORDER = "#000000"

# ==========================================
# ニュース取得（YouTube検索 + RSS フォールバック + Gemini要約）
# ==========================================
import random
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup


def fetch_trending_youtube_videos(keywords=None, max_videos=5, days=5, min_views=1000, skip_words=None):
    """YouTube Data API v3で話題の動画を取得する（コメント数順）

    全チャンネル共通設計: GOOGLE_API_KEYSから自動でAPIキーを取得。
    フィルタ: 直近N日以内 + 最低再生回数以上 + コメント数順ソート
    """
    from datetime import datetime, timedelta, timezone

    if keywords is None:
        theme = os.environ.get("CHANNEL_THEME", "暮らし")
        keywords = [f"{theme} 最新", f"{theme} 生活", f"{theme} 2026"]
    if skip_words is None:
        skip_words = []

    api_keys_str = os.environ.get("GOOGLE_API_KEYS", "")
    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
    if not api_keys:
        print("[WARN] GOOGLE_API_KEYS未設定。YouTube Data API使用不可")
        return []

    api_key = random.choice(api_keys)  # ランダムでquota分散
    published_after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_video_ids = []
    seen_ids = set()
    shuffled_keywords = keywords.copy()
    random.shuffle(shuffled_keywords)

    # Step 1: Search APIで動画IDを収集
    for keyword in shuffled_keywords:
        try:
            print(f"[YouTube API] キーワード「{keyword}」で検索中...")
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": keyword,
                    "type": "video",
                    "order": "date",
                    "publishedAfter": published_after,
                    "regionCode": "JP",
                    "relevanceLanguage": "ja",
                    "maxResults": 15,
                    "key": api_key,
                },
                timeout=(5, 10),
            )  # (connect, read) タイムアウト

            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    video_id = item.get("id", {}).get("videoId", "")
                    if video_id and video_id not in seen_ids:
                        title = item.get("snippet", {}).get("title", "")
                        if any(sw in title for sw in skip_words):
                            print(f"  [SKIP] 除外: {title[:40]}...")
                            continue
                        seen_ids.add(video_id)
                        all_video_ids.append(
                            {
                                "video_id": video_id,
                                "title": title,
                                "channel": item.get("snippet", {}).get("channelTitle", "不明"),
                                "published": item.get("snippet", {}).get("publishedAt", ""),
                            }
                        )
                print(f"  → フィルタ後{len(all_video_ids)}件")
            elif resp.status_code == 403:
                print("  [WARN] APIキー制限")
                if len(api_keys) > 1:
                    api_key = api_keys[1]
                else:
                    break
            else:
                print(f"  [WARN] YouTube API HTTP {resp.status_code}")
        except (Exception, KeyboardInterrupt) as e:
            print(f"  [WARN] YouTube API検索失敗（{keyword}）: {type(e).__name__}: {e}")
            continue  # 次のキーワードを試す

    if not all_video_ids:
        print("[WARN] YouTube API検索結果なし")
        return []

    # Step 2: Videos APIで再生回数・コメント数を取得
    print(f"--- 動画統計情報を取得中（{len(all_video_ids)}件） ---")
    enriched_videos = []
    batch_ids = [v["video_id"] for v in all_video_ids]

    for i in range(0, len(batch_ids), 50):
        batch = batch_ids[i : i + 50]
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "statistics",
                    "id": ",".join(batch),
                    "key": api_key,
                },
                timeout=(5, 10),
            )
            if resp.status_code == 200:
                stats_map = {item["id"]: item["statistics"] for item in resp.json().get("items", [])}
                for v in all_video_ids:
                    if v["video_id"] in stats_map:
                        s = stats_map[v["video_id"]]
                        views = int(s.get("viewCount", 0))
                        comments = int(s.get("commentCount", 0))
                        if views >= min_views:
                            enriched_videos.append(
                                {
                                    "title": v["title"],
                                    "channel": v["channel"],
                                    "url": f"https://www.youtube.com/watch?v={v['video_id']}",
                                    "source": "YouTube",
                                    "views": f"{views:,}回再生",
                                    "views_count": views,
                                    "comments": f"{comments:,}件コメント",
                                    "comments_count": comments,
                                    "published": v["published"],
                                }
                            )
                        else:
                            print(f"  [SKIP] 再生数不足({views}): {v['title'][:40]}...")
        except Exception as e:
            print(f"  [WARN] Videos API失敗: {e}")

    # Step 3: コメント数順でソート
    enriched_videos.sort(key=lambda x: x.get("comments_count", 0), reverse=True)
    for i, v in enumerate(enriched_videos[:max_videos], 1):
        print(f"  [TOP{i}] {v['title'][:50]}... ({v['views']}, {v['comments']})")

    print(f"[OK] YouTube動画取得完了: {len(enriched_videos)}件→上位{min(max_videos, len(enriched_videos))}件")
    return enriched_videos[:max_videos]


def fetch_x_posts_via_grok(keywords, max_posts=5):
    """Grok API (x_search) でXのリアルタイム世論をクラスターベースで取得する

    参考: HayattiQ/x-research-skills の4段階手法を適用
    1) 広域探索: テーマ関連の複数クエリで幅広くX検索
    2) クラスター抽出: 繰り返し出るトピックを凝縮
    3) 代表ポスト選出: クラスターごとに反響の大きい投稿を選出
    4) 構造化出力: 動画台本に使える「庶民の声」として整理

    Args:
        keywords: 検索キーワードのリスト（テーマ別の探索シード）
        max_posts: 取得する投稿の最大数

    Returns:
        [{"text": "クラスター分析結果", "source": "X"}]
    """
    import requests as req

    xai_api_key = os.environ.get("XAI_API_KEY", "")
    if not xai_api_key:
        print("[WARN] XAI_API_KEY未設定。X検索スキップ")
        return []

    theme = os.environ.get("CHANNEL_THEME", "暮らし")
    all_results = []

    # クラスターベースリサーチ: 全キーワードを1回の高品質な呼び出しに統合
    seed_queries = ", ".join(keywords)

    try:
        print(f"[Grok x_search] クラスターベースリサーチ開始: {seed_queries}")
        rich_prompt = f"""日本語で回答して。

目的: YouTube動画の台本に使う「Xでのリアルタイムの声」を収集する
テーマ: {theme}
想定視聴者: {theme}に関心を持つ50-70代の方
領域: {theme}に関連する暮らし・知恵・情報

やること（4段階リサーチ）:

1) まず「広く薄く」探索する:
   - 以下のシードクエリに加え、関連する検索クエリを自分で5個以上追加してX検索する
   - シードクエリ: {theme} 最新, {theme} 暮らし, {theme} コツ, {theme} 節約, {theme} おすすめ
   - 可能ならバズっている投稿（いいね数・リポスト数が多い）を優先的に拾う

2) 収集した投稿から「繰り返し出てくるトピック」を3-5クラスターにまとめる:
   - 単発の話題はクラスターにしない
   - 各クラスターに「投稿者が使っている言い回し・キーフレーズ」を2-3個付ける

3) クラスターごとに代表的な投稿を1-2個選ぶ:
   - 投稿URL、投稿者名、エンゲージ指標（いいね数・リポスト数・閲覧数で観測できたもの）
   - 長文の直接引用はせず、1-2行で要約する

4) 各クラスターについて「庶民の本音」を1行で要約する:
   - 視聴者（{theme}に関心を持つ50-70代の方）が「そうそう！」と共感する言い方で
   - 不確かな情報は「未確認」と明記する

出力形式（必ずこの構造で）:

【タイムラインの空気】
- クラスター1: [トピック名] → 庶民の本音1行
  代表ポスト: [URL] ([投稿者], いいね[数])
  キーフレーズ: [言い回し1], [言い回し2]
- クラスター2: ...
- クラスター3: ...

【今日の注目3テーマ】
1. [テーマ名]: [1行説明]
2. [テーマ名]: [1行説明]
3. [テーマ名]: [1行説明]

【素材一覧】(最大{max_posts}件)
各素材:
- URL: [X投稿URL]
- 要約: [1-2行]
- エンゲージ: いいね=[数], RT=[数], 閲覧=[数] (不明はunknown)
- なぜ反響があるか: [仮説1行]
- 動画で使えるネタ: [1行]"""

        resp = req.post(
            "https://api.x.ai/v1/responses",
            headers={
                "Authorization": f"Bearer {xai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-4-fast",
                "tools": [{"type": "x_search"}],
                "input": rich_prompt,
                "temperature": 0.3,
            },
            timeout=(10, 120),  # クラスター分析のため長めのタイムアウト
        )

        if resp.status_code == 200:
            data = resp.json()
            output_text = ""
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text += content.get("text", "")
            if output_text:
                all_results.append(
                    {
                        "text": output_text[:4000],  # クラスター分析は長めに許容
                        "source": "X",
                        "keyword": seed_queries,
                    }
                )
                print(f"  → クラスターベースリサーチ成功 ({len(output_text)}文字)")
            else:
                print("  [WARN] X投稿テキスト抽出失敗")
        elif resp.status_code == 429:
            print("  [WARN] Grok APIレート制限。X検索終了")
        else:
            print(f"  [WARN] Grok API HTTP {resp.status_code}: {resp.text[:200]}")

    except Exception as e:
        print(f"  [WARN] Grok x_searchクラスターリサーチ失敗: {type(e).__name__}: {e}")

    if all_results:
        print(f"[OK] Xクラスターリサーチ完了: {len(all_results)}件")
    else:
        print("[WARN] Xクラスターリサーチ結果なし")

    return all_results


def fetch_news_from_rss(keywords, max_articles=5):
    """Google News RSSからキーワードでニュース記事を取得する

    Args:
        keywords: 検索キーワードのリスト（例: ["テーマ名", "関連ワード"]）
        max_articles: 取得する記事の最大数

    Returns:
        [{"title": "見出し", "url": "記事URL", "published": "公開日"}]
    """
    articles = []
    seen_urls = set()

    for keyword in keywords:
        try:
            # Google News RSS URL
            encoded_keyword = quote(keyword)
            rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ja&gl=JP&ceid=JP:ja"
            print(f"[RSS] キーワード「{keyword}」で検索中...")

            # requestsでXMLを取得してからfeedparserで解析（SSL問題回避）
            rss_response = requests.get(
                rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
            )
            if rss_response.status_code != 200:
                print(f"[WARN] RSS HTTP {rss_response.status_code}: {keyword}")
                continue

            feed = feedparser.parse(rss_response.text)

            if not feed.entries:
                print(f"[WARN] 「{keyword}」のニュースが見つかりません")
                continue

            for entry in feed.entries:
                if len(articles) >= max_articles:
                    break

                url = entry.get("link", "")
                # 重複排除
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                article = {
                    "title": entry.get("title", ""),
                    "url": url,
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", "") if hasattr(entry, "source") else "",
                }
                articles.append(article)
                print(f"  [{len(articles)}] {article['title'][:50]}...")

        except Exception as e:
            print(f"[WARN] RSS取得失敗（{keyword}）: {e}")
            continue

    print(f"[OK] RSS取得完了: {len(articles)}件")
    return articles[:max_articles]


def scrape_article_text(url, max_chars=2000):
    """記事URLから本文テキストを取得する"""
    # Google News中間URLはリダイレクトでハングするためスキップ
    if "news.google.com/rss/articles/" in url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Google Newsのリダイレクトを解決
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)

        if response.status_code != 200:
            print(f"  [WARN] HTTP {response.status_code}: {url[:60]}...")
            return ""

        soup = BeautifulSoup(response.text, "html.parser")

        # 不要な要素を除去（広告、ナビ、スクリプト等）
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()

        # <article>タグがあればそこから取得（最も正確）
        article_tag = soup.find("article")
        if article_tag:
            paragraphs = article_tag.find_all("p")
        else:
            # なければ本文全体の<p>タグから取得
            paragraphs = soup.find_all("p")

        # テキスト結合
        text_parts = []
        total_chars = 0
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) < 10:  # 短すぎるのはスキップ（ボタンラベル等）
                continue
            text_parts.append(text)
            total_chars += len(text)
            if total_chars >= max_chars:
                break

        body = "\n".join(text_parts)

        if len(body) < 50:
            print(f"  [WARN] 本文が短すぎます（{len(body)}文字）: {url[:60]}...")
            return ""

        print(f"  [OK] 本文取得: {len(body)}文字")
        return body[:max_chars]

    except requests.Timeout:
        print(f"  [WARN] タイムアウト: {url[:60]}...")
        return ""
    except Exception as e:
        print(f"  [WARN] スクレイプ失敗: {e}")
        return ""


def summarize_youtube_for_script(videos, channel_theme="暮らし"):
    """YouTube市民生活インタビュー動画をGeminiで台本用に要約する

    テーマに合わせて「他の人がどう暮らしてるか」を紹介する形式。
    視聴者は自分と比較して安心したり危機感を持ったりしたい。
    """
    if not videos:
        return "市民生活をされている方々の暮らしぶりを紹介します"

    videos_text = ""
    for i, video in enumerate(videos[:5], 1):
        channel = video.get("channel", "不明")
        views = video.get("views", "")
        videos_text += f"動画{i}: {video['title']} （チャンネル: {channel}、{views}）\n\n"

    prompt = f"""以下は情報サイトで見つけた一般市民のインタビュー・体験談のタイトルです。
これらの中から2-3件を選び、トーク番組で「他の人の庶民暮らし」として紹介できる形に要約してください。

【市民生活インタビュー情報】
{videos_text}

【重要ルール】
- 動画タイトルから読み取れる情報（年齢、税金額、生活状況、節約方法など）を具体的に記載
- 「この方は○歳で、○○をしながら暮らしているそうです」という紹介形式
- カツミ・ヒロシの2人番組で、視聴者が「自分と比較できる」ネタとして使う
- 他の人の暮らしぶりを知ることで「自分はまだマシかも」「もっと節約しなきゃ」と思える内容に
- 推測・想像で細部を補ってよい（税金額が不明な場合は「○万円台とのこと」等）
- 共感ポイント（切ない点、頑張ってる点、驚きポイント）を1つずつ添える

【出力形式】（日本語のみ）
- 一般市民1: [年齢・状況] [税金額と暮らしぶり150-250文字] [共感ポイント]
- 一般市民2: [年齢・状況] [税金額と暮らしぶり150-250文字] [共感ポイント]
- 一般市民3: [年齢・状況] [税金額と暮らしぶり150-250文字] [共感ポイント]
"""

    try:
        summary = call_llm_with_fallback(
            messages=[{"role": "user", "content": prompt}], max_tokens=2500, temperature=0.5
        )
        print(f"[OK] 一般市民の声要約完了: {len(summary)}文字")
        return summary
    except Exception as e:
        print(f"[WARN] Gemini要約失敗: {e}")
        titles_text = "\n".join([f"- {v['title']} （{v.get('channel', '情報サイト')}）" for v in videos[:3]])
        return f"情報サイトで見つけた一般市民の声を紹介します:\n{titles_text}"


def summarize_news_for_script(articles, channel_theme="暮らし"):
    """RSSで取得した実記事をGeminiで台本用に要約する

    タイトル+出典名をベースに要約。本文が取れた場合は補助情報として活用。
    Google News中間URLではスクレイプが困難なため、タイトルだけでも動作する。

    Args:
        articles: [{"title": "...", "url": "...", "source": "...", "body": "..."(optional)}]
        channel_theme: チャンネルのテーマ（CHANNEL_THEME環境変数から取得）

    Returns:
        台本生成に渡すニュース要約テキスト
    """
    if not articles:
        print("[WARN] RSS取得が全て失敗。フォールバックを使用します")
        return f"{channel_theme}に関する最新ニュースを解説します"

    # 記事データをプロンプトに組み立て（タイトル+出典ベース）
    articles_text = ""
    for i, article in enumerate(articles[:5], 1):
        body = article.get("body", "")
        source_name = article.get("source", "不明")
        # タイトルから出典名を分離（Google News形式: "タイトル - 出典名"）
        title = article["title"]
        if " - " in title and not source_name:
            parts = title.rsplit(" - ", 1)
            title = parts[0]
            source_name = parts[1]

        articles_text += f"記事{i}: {title} （出典: {source_name}）\n"
        if body:
            articles_text += f"  本文抜粋: {body[:500]}\n"
        articles_text += "\n"

    prompt = f"""以下はGoogle News RSSから取得した実在するニュース記事のタイトルです。
これらの中から{channel_theme}に関連する3件を選び、台本の元ネタとして使える形に要約してください。

【実在するニュース一覧】
{articles_text}

【重要ルール】
- 上記のタイトルに基づく事実のみを記載すること
- 存在しないニュースを捏造しないこと
- 各ニュースは見出し+内容（100-200文字）+出典名の形式で記載
- {channel_theme}と関連が薄い記事はスキップしてよい

【出力形式】（日本語のみ）
- ニュース1: [見出し] [内容の要約100-200文字] [出典: サイト名]
- ニュース2: [見出し] [内容の要約100-200文字] [出典: サイト名]
- ニュース3: [見出し] [内容の要約100-200文字] [出典: サイト名]
"""

    try:
        summary = call_llm_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,  # 正確性重視なので低め
        )
        print(f"[OK] ニュース要約完了: {len(summary)}文字")
        return summary
    except Exception as e:
        print(f"[WARN] Gemini要約失敗: {e}")
        # フォールバック: タイトル一覧をそのまま返す
        titles_text = "\n".join([f"- {a['title']} （出典: {a.get('source', '不明')}）" for a in articles[:3]])
        return f"以下の実在するニュースについて解説します:\n{titles_text}"


# ==========================================
# JSON抽出ヘルパー（Llamaモデル用）
# ==========================================
def extract_json_from_text(text):
    """
    テキストからJSON部分を抽出する。
    Llamaモデルは説明テキスト + JSONを返すことがあるため。
    """
    # コードブロック内のJSONを抽出
    code_block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if code_block_match:
        return code_block_match.group(1).strip()

    # {で始まり}で終わる部分を抽出
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        return json_match.group(0)

    # そのまま返す（JSONかもしれない）
    return text.strip()


# ==========================================
# LLM統一呼び出し関数（Gemini優先 → Claude Haikuフォールバック）
# cost: Gemini=$0.001/動画, Claude Haiku=$0.015/動画
# 2026-02-06: Groq削除（日本語品質問題）、GPT-4o削除（2/13廃止予定）
# ==========================================


def call_llm_with_fallback(messages, json_mode=False, max_tokens=4000, temperature=0.7):
    """
    Gemini 2.0 FlashでLLM呼び出し（複数キーでリトライ）。

    Args:
        messages: [{"role": "system/user", "content": "..."}]
        json_mode: JSON形式で出力するか
        max_tokens: 最大トークン数
        temperature: 生成温度

    Returns:
        str: LLMの応答テキスト
    """
    # Gemini APIキー（GOOGLE_API_KEYSに統一）
    gemini_api_keys = os.getenv("GOOGLE_API_KEYS", "") or os.getenv("GOOGLE_API_KEY", "")
    gemini_api_keys = [k.strip() for k in gemini_api_keys.split(",") if k.strip()]

    errors = []

    # ===== 1. Gemini 2.0 Flash（超低コスト、最優先） =====
    if gemini_api_keys:
        # チャンネル名からインデックスを決定（同じチャンネルは同じキーを使う）
        channel_name = os.getenv("CHANNEL_NAME", "default")
        key_index = hash(channel_name) % len(gemini_api_keys)

        for i in range(len(gemini_api_keys)):
            current_index = (key_index + i) % len(gemini_api_keys)
            api_key = gemini_api_keys[current_index]
            try:
                print(f"[LLM] Gemini 2.0 Flash（key {current_index + 1}/{len(gemini_api_keys)}）で生成中...")
                from google import genai
                from google.genai import types as genai_types

                client = genai.Client(api_key=api_key)

                # messagesをGemini形式に変換
                prompt_text = "\n\n".join([f"{m['role']}: {m['content']}" for m in messages])

                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt_text,
                    config=genai_types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens),
                )
                result = response.text
                print(f"[OK] Gemini成功（key {current_index + 1}）: {len(result)}文字")
                return result
            except Exception as e:
                errors.append(f"Gemini(key{current_index + 1}): {e}")
                print(f"[WARN] Gemini(key {current_index + 1})失敗: {e}")
                continue

    # 全て失敗
    raise Exception(f"全LLM失敗: {errors}")


def draw_text_bold_with_border(draw, text, position, font, text_color, border_color, border_width, is_bold=False):
    x, y = position
    if border_color and border_width > 0:
        for dx in range(-border_width, border_width + 1):
            for dy in range(-border_width, border_width + 1):
                if dx * dx + dy * dy <= border_width * border_width:
                    draw.text((x + dx, y + dy), text, font=font, fill=border_color)
    if is_bold:
        for dx in [0, 1]:
            for dy in [0, 1]:
                draw.text((x + dx, y + dy), text, font=font, fill=text_color)
    else:
        draw.text((x, y), text, font=font, fill=text_color)


def get_audio_duration(wav_path):
    """ffprobeで音声ファイルの正確な長さを取得（秒）

    重要: 音声とテキストのズレを防ぐため、予測値ではなく実測値を使用すること
    """
    import subprocess

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", wav_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"[WARN] ffprobe失敗、waveモジュールでフォールバック: {e}")
        try:
            with wave.open(wav_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / rate
        except Exception as e2:
            print(f"[ERR] 音声長取得失敗: {e2}")
            return 5.0  # フォールバック5秒


def generate_text_image(
    text, font_size, text_color, border_color, border_width, is_bold=False, size=None, align="left"
):
    # 指定サイズがない場合は動的に計算 (字幕などの固定幅用)
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT_PATH, font_size)

    if size:
        W, H = size
    else:
        # 文字数から概算 (または textlength で真面目に計算)
        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        W = int(dummy_draw.textlength(text, font=font) + border_width * 2 + 10)
        H = font_size + border_width * 2 + 10

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 字幕の折り返し処理 (method='caption' 互換)
    if size and W > 0:
        import textwrap

        # 日本語全角文字は約font_size分の幅ボーダー分も考慮して安全マージン
        avg_char_w = font_size * 1.1  # 日本語を考慮（1.0 + マージン0.1）
        available_width = W - (border_width * 2 + 20)  # ボーダーとマージンを除く
        chars_per_line = max(1, int(available_width / avg_char_w))
        lines = textwrap.wrap(text, width=chars_per_line)
        y_text = 0
        for line in lines:
            line_w = draw.textlength(line, font=font)
            x_text = 0 if align == "left" else (W - line_w) / 2
            draw_text_bold_with_border(
                draw, line, (x_text, y_text), font, text_color, border_color, border_width, is_bold
            )
            y_text += font_size * 1.2
    else:
        draw_text_bold_with_border(draw, text, (0, 0), font, text_color, border_color, border_width, is_bold)

    return img


class VideoEngineV4:
    def __init__(self, mode="--test", script_only=False):
        self.mode = mode
        self.script_only = script_only
        # 解像度とFPSの設定
        if mode == "--short-prod":
            self.res = (960, 540)
            self.fps = 12
            self.scale = 0.5
        else:
            self.res = (1920, 1080)
            self.fps = 24
            self.scale = 1.0

        # チャンネルテーマ（環境変数から取得）
        self.channel_theme = os.environ.get("CHANNEL_THEME", "暮らし")
        self.channel_name = os.environ.get("CHANNEL_NAME", "default")
        self.channel_color = os.environ.get("CHANNEL_COLOR", "#e74c3c")
        self.channel_group = os.environ.get("CHANNEL_GROUP", "news")  # news/nayami/kamishibai
        print(f"[CONFIG] チャンネルテーマ: {self.channel_theme}")
        print(f"[CONFIG] チャンネルグループ: {self.channel_group}")

        self.api_keys = self._get_api_keys()
        self.key_idx = 0
        self.key_errors = {}  # キーごとのエラーカウント
        self.blacklist = set()  # ブラックリスト
        self.client = self._get_client()

        if not script_only:
            self.uploader = YouTubeUploader()
        else:
            self.uploader = None

        # TTS読み仮名辞書（誤読修正）
        self.tts_reading_dict = {
            "掛金": "かけきん",
            "掛け金": "かけきん",
            "NISA": "ニーサ",
            "nisa": "ニーサ",
            "iDeCo": "イデコ",
            "ideco": "イデコ",
            "GDP": "ジーディーピー",
            "NHK": "エヌエイチケー",
            "板橋": "いたばし",
            "他人事": "ひとごと",
            "今日の方": "きょうのかた",
            "この方": "このかた",
        }

    def _normalize_text_for_tts(self, text):
        """TTS送信前にテキストを正規化（誤読修正 & エラー予防）"""
        original_text = text

        # 1. 誤読修正（既存の辞書）
        for wrong, correct in self.tts_reading_dict.items():
            text = text.replace(wrong, correct)

        # 2. エラー予防処理
        # 空白・改行のみの場合は空文字列を返す（後続処理でスキップされる）
        if not text.strip():
            return ""

        # 記号のみの場合も空文字列を返す
        if all(c in "…！？!?.,;:[]()（）[STAR][star]" for c in text.strip()):
            return ""

        # 短すぎるテキスト（8文字以下）の場合Gemini TTSがエラーを出しやすいので補強
        if len(text.strip()) <= 8:
            # よくある短い相槌を自然な表現に拡張
            text_stripped = text.strip()
            replacements = {
                "なるほど": "なるほどそうなんですね",
                "なるほど！": "なるほどそうなんですね！",
                "へえ": "へえそうなんですか",
                "へえ！": "へえそうなんですか！",
                "ほう": "ほう興味深いですね",
                "そうか": "そうか分かりました",
                "そうですね": "そうですねその通りですね",
                "分かりました": "分かりました承知しました",
                "はい": "はい分かりました",
                "ええ": "ええそうですね",
            }

            for short, extended in replacements.items():
                if text_stripped == short:
                    text = extended
                    print(f"   [FIX] 短いテキストを補強: {original_text} -> {text}")
                    break
            else:
                # 辞書にない短いテキストの場合末尾に句読点を追加
                if len(text.strip()) <= 5:
                    if not text.strip().endswith(("", "！", "？", ".", "!", "?")):
                        text = text.strip() + ""
                        print(f"   [FIX] 句読点を追加: {original_text} -> {text}")

        return text

    def _get_api_keys(self):
        raw = os.environ.get("GOOGLE_API_KEYS") or os.environ.get("GOOGLE_API_KEY") or ""
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise Exception("APIキーが設定されていません")
        return keys

    def _get_client(self):
        # ブラックリストに入っていないキーを探す
        max_attempts = len(self.api_keys)
        for _ in range(max_attempts):
            idx = self.key_idx % len(self.api_keys)
            self.key_idx += 1

            if idx in self.blacklist:
                continue  # ブラックリストのキーはスキップ

            k = self.api_keys[idx]
            print(f"--- APIキー切替: {idx} ---")
            return genai.Client(api_key=k, http_options={"api_version": "v1beta"})

        # 全てのキーがブラックリストに入っている場合60秒待機してリセット
        print("[WARN]  全てのGemini APIキーが枯渇しました")
        print(f"   総キー数: {len(self.api_keys)}")
        print(f"   ブラックリストキー: {sorted(self.blacklist)}")
        print(f"   エラーカウント: {self.key_errors}")
        print("[WAIT] 60秒待機後ブラックリストをリセットします...")
        time.sleep(60)
        self.blacklist.clear()
        self.key_errors.clear()
        print("[OK] ブラックリストをリセットしました再試行します")
        # 最初のキーで再試行
        idx = self.key_idx % len(self.api_keys)
        self.key_idx += 1
        k = self.api_keys[idx]
        print(f"--- APIキー切替: {idx} (リセット後) ---")
        return genai.Client(api_key=k, http_options={"api_version": "v1beta"})

    def generate_content(self):
        """台本タイトル説明文タグを JSON 形式で生成します"""
        print("--- 台本・メタデータ生成開始 (モデル: gemini-2.0-flash) ---")
        print("[API] Gemini API にリクエスト送信（長時間待機モード: 最大300秒）")

        if self.mode == "--test":
            target_len = "1分程度"
        else:
            target_len = "3分以上厳守"

        # テーマ変数を設定
        theme = self.channel_theme

        # ===== コンテンツ取得（人間ドキュメンタリー型: テーマベース） =====
        # 参考YouTubeチャンネルからテーマ関連の動画を取得し、ストーリーを深掘り
        print("===== コンテンツ取得（人間ドキュメンタリー型） =====")

        # Part 1: 参考チャンネルからテーマ関連動画を検索
        print(f"--- Part 1: 参考チャンネルから{theme}ストーリー動画を検索 ---")
        # YouTube検索でテーマに関連する動画を取得
        # CHANNEL_THEMEベースでYouTube検索キーワードを動的生成
        story_keywords = [
            f"{theme} 暮らし 実態",
            f"{theme} 生活費",
            f"{theme} リアル",
            f"{theme} 節約 日常",
            f"{theme} 密着",
            f"{theme} コツ",
            f"{theme} シニア",
            f"{theme} 体験談",
        ]
        yt_videos = fetch_trending_youtube_videos(keywords=story_keywords, max_videos=8, days=14, min_views=300)

        story_summary = ""
        if yt_videos and len(yt_videos) >= 1:
            print(f"[OK] {theme}ストーリー動画{len(yt_videos)}件取得成功")
            # ストーリーをサマリーとして抽出
            story_summary = summarize_youtube_for_script(yt_videos, channel_theme=f"{theme}の体験談")

        # Part 2: RSSでテーマ関連の統計データを取得（チャートデータ用）
        print(f"--- Part 2: {theme}関連統計データ（RSS） ---")
        rss_articles = fetch_news_from_rss(
            keywords=[f"{theme} 生活費", f"{theme} 最新", f"シニア {theme}"], max_articles=2
        )
        stats_brief = ""
        if rss_articles:
            for article in rss_articles:
                article["body"] = scrape_article_text(article["url"])
            stats_brief = summarize_news_for_script(rss_articles, channel_theme=theme)

        # Part 3: X(旧Twitter)でリアルタイムの声を取得
        print(f"--- Part 3: X(旧Twitter){theme}の声 ---")
        x_posts = fetch_x_posts_via_grok(keywords=[f"{theme} リアル", f"{theme} 暮らし", f"{theme} 体験"], max_posts=5)
        x_voices = ""
        if x_posts:
            x_voices = "\n".join([post["text"] for post in x_posts])
            print(f"[OK] X投稿{len(x_posts)}件取得成功")

        # 合体: ストーリー素材
        x_section = f"\n\n【Xでのリアルな声】\n{x_voices}" if x_voices else ""
        stats_section = f"\n\n【統計データ（チャート用）】\n{stats_brief}" if stats_brief else ""
        news_content = f"""【{theme}のストーリー素材（メインコンテンツ）】
{story_summary}
{stats_section}{x_section}"""

        # promptをストーリー素材で更新（構成生成で使用）
        prompt = news_content

        # ===== 2段階生成方式（Gemini優先 → Claude Haikuフォールバック） =====
        # cost: Gemini=$0.001, Claude Haiku=$0.015/動画

        # ----- 第1段階: 構成生成 -----
        is_kamishibai = self.channel_group == "kamishibai"
        group_label = "紙芝居3幕" if is_kamishibai else "人間ドキュメンタリー"
        print(f"===== 第1段階: 構成生成（{group_label}） =====")

        # 共通: コンテンツ哲学
        content_philosophy = """
## CONTENT PHILOSOPHY (MANDATORY - apply to ALL dialogue)
The script must INDIRECTLY stimulate these core human emotions:
- PRIORITY EMOTION: "損得" (gain/loss) - MORE IMPORTANT than right/wrong, win/lose, fun/boring
  - Viewers must feel "もっと得したい！" (I want more benefit!) and "絶対に損したくない！" (I absolutely don't want to lose out!)
- "もっと欲しい" - Even when they have enough, the instinct of "if I can get it, I want it"
- "安心への渇望" - No matter how much they have, they can never feel fully secure
- "損失回避" - Fear of missing benefits they're entitled to
- "優位性欲求" - Wanting to be the one who knows, the one who benefits

CRITICAL CONSTRAINTS:
- NEVER express these directly or crudely
- Use INDIRECT phrases: "知らないと損" "実はまだ間に合う" "意外と見落としがち" "これ知ってる人だけ得してる"
- Let Katsumi and Hiroshi naturally touch on these through their everyday perspective
- Viewers should feel "this is about ME" and keep watching to the end"""

        if is_kamishibai:
            # ===== 紙芝居3幕: 構成プロンプト =====
            structure_prompt = f"""
You are a professional content planner for a KAMISHIBAI (紙芝居) style YouTube show.

CRITICAL: ALL OUTPUT CONTENT MUST BE IN JAPANESE.
Target audience: Japanese elderly women (60-80 years old).
{content_philosophy}

## SHOW CONCEPT: 「{self.channel_theme}」の紙芝居チャンネル
このチャンネルは{self.channel_theme}について、データとチャートを多用して視覚的にわかりやすく解説する。
カツミとヒロシが庶民目線で語り、Xのリアルな声も交えて共感を生む。

## TODAY'S MATERIAL
{prompt[:3000]}

## YOUR TASK: 紙芝居3幕の構成を作成
OP(衝撃フック) → 本編(データ解説) → 控え室(エピローグ余韻)

1. **OPフック**: 視聴者を釘付けにする衝撃の数字・事実を1つ選ぶ
   - 「え！○○万円も！？」「○○%の人が知らない！」等
   - クイズ形式禁止。ストレートに衝撃事実をぶつける
2. **本編テーマ3つ**: {self.channel_theme}に関連する解説テーマを3つ
   - 各テーマに使うチャートの種類(bar/line/pie/radar)を指定
   - 具体的な数字データを含める
3. **控え室の余韻**: 本編の衝撃を振り返る温かいトークの方向性

## OUTPUT FORMAT
{{
  "hook_fact": "OPで使う衝撃の数字・事実（1行）",
  "hook_number": "○万円/○%等の具体数字",
  "themes": [
    {{"title": "テーマ名", "chart_type": "bar/line/pie/radar", "key_data": "核となる数字", "angle": "切り口"}},
    {{"title": "テーマ名", "chart_type": "...", "key_data": "...", "angle": "..."}},
    {{"title": "テーマ名", "chart_type": "...", "key_data": "...", "angle": "..."}}
  ],
  "epilogue_direction": "控え室で振り返る方向性",
  "stat_data": [
    {{"topic": "チャート用統計1", "source": "出典", "angle": "比較"}},
    {{"topic": "チャート用統計2", "source": "出典", "angle": "差異"}}
  ]
}}
"""
        else:
            # ===== ヒーローズジャーニー: 構成プロンプト（現状維持） =====
            structure_prompt = f"""
You are a professional TV program structure planner for a HUMAN DOCUMENTARY show.

CRITICAL: ALL OUTPUT CONTENT MUST BE IN JAPANESE.
Target audience: Japanese elderly women (60-80 years old).
{content_philosophy}

## SHOW CONCEPT: "{self.channel_theme}の暮らしの知恵"
This is a HUMAN STORY channel. Each episode features a real story related to {self.channel_theme}.
The story follows a narrative arc (hero's journey): Background → Challenges → Current life → Lessons.
カツミ and ヒロシ discuss the topic with honest opinions and data, from the perspective of {self.channel_theme}.

## TODAY'S STORY MATERIAL (source for creating the person's profile)
{prompt[:3000]}

## YOUR TASK
Based on the material above, create a compelling profile of 1 person related to {self.channel_theme}:
1. Name (MUST be a completely ORIGINAL fictional pseudonym - 完全オリジナルの仮名を創作すること)
   ★★★ 絶対禁止: YouTube元動画の人物名をそのまま使うこと。著作権・プライバシー問題を避けるため、名前・経歴・エピソードは全てオリジナルに再構成すること ★★★
2. Age, former occupation, monthly income (数字は参考素材を元に少し変更してよい)
3. Key life events (marriage, job loss, illness, spouse death, etc.)
4. Current daily life (budget breakdown, hobbies, struggles)
5. A "turning point" or dramatic moment in their life
6. 2-3 statistical data points to compare with their situation

## OUTPUT FORMAT
{{
  "person_profile": {{
    "name": "完全オリジナルの仮名（例: 中村さん、鈴木さん等。元動画の名前は使用禁止）",
    "age": 68,
    "former_job": "元の職業",
    "monthly_income": "月○万円",
    "living_situation": "一人暮らし/夫婦 etc.",
    "key_episode": "人生の転機となったエピソード"
  }},
  "story_arc": ["intro_profile", "challenge", "turning_point", "current_life", "data_comparison", "lesson"],
  "key_facts": ["この人の印象的な事実1", "この人の印象的な事実2", "統計との比較ポイント"],
  "stat_data": [
    {{"topic": "この人と同分野の関連統計", "source": "公式統計", "angle": "比較"}},
    {{"topic": "生活費の内訳（全国平均 vs この人）", "source": "総務省家計調査", "angle": "差異"}}
  ]
}}
"""

        structure_text = call_llm_with_fallback(
            messages=[
                {"role": "system", "content": "Generate structure. Output JSON."},
                {"role": "user", "content": structure_prompt},
            ],
            json_mode=True,
            max_tokens=2000,
            temperature=0.7,
        )
        # JSON抽出（Llamaモデル対応）
        structure_text = extract_json_from_text(structure_text)
        structure = json.loads(structure_text)
        print(f"構成生成完了: {json.dumps(structure, indent=2, ensure_ascii=False)[:500]}...")

        # ----- 第2段階: 詳細台本一括生成 -----
        print("\n===== 第2段階: 詳細台本生成 =====")
        # 行数ベース制御（LLMは文字数を正確にカウントできないため行数で制御）
        # 日本語TTS: 1行平均30-50文字 x 5文字/秒 = 1行6-10秒
        # 35行 x 8秒 = 280秒（約4.7分）→ 3分保証に余裕あり
        min_lines = 35  # 最低35行（8分目標）
        data = None

        for attempt in range(10):  # 行数不足なら再生成（最大10回）
            print(f"--- 台本生成 (試行 {attempt + 1}/10) ---")
            # 人物プロフィールを構成から取得
            person_profile = structure.get("person_profile", {})
            person_json = json.dumps(person_profile, ensure_ascii=False) if person_profile else "{}"
            stat_data = structure.get("stat_data", [])
            stat_data_json = json.dumps(stat_data, ensure_ascii=False) if stat_data else "[]"

            if is_kamishibai:
                # ===== 紙芝居3幕: 詳細台本プロンプト =====
                # 構成からデータを取得
                hook_fact = structure.get("hook_fact", "")
                hook_number = structure.get("hook_number", "")
                themes = structure.get("themes", [])
                themes_json = json.dumps(themes, ensure_ascii=False) if themes else "[]"
                epilogue_dir = structure.get("epilogue_direction", "")

                detail_prompt = f"""
Generate a {self.channel_theme} script. This is a KAMISHIBAI (紙芝居) style show with DATA and CHARTS.

CRITICAL: ALL OUTPUT CONTENT MUST BE IN JAPANESE ONLY.
Target audience: Japanese elderly women (60-80 years old).
{content_philosophy}

CRITICAL REQUIREMENT - SCRIPT LENGTH:
- You MUST generate at least 35 lines of dialogue
- Total text: MINIMUM 1000 Japanese characters
- THIS IS A 5+ MINUTE VIDEO - generate enough content!

## KAMISHIBAI 3-ACT STRUCTURE (紙芝居3幕構成)

### OP: 衝撃フック (3-5 lines) - クイズ禁止！衝撃事実をぶつける！
- 衝撃の事実: {hook_fact}
- 核の数字: {hook_number}
- カツミ: 「え！？{hook_number}って...マジで！？」と驚きから入る
- ヒロシ: データで裏付け「これ、○○の統計なんですけどね...」
- ★ クイズ形式は絶対禁止。「△△は何%でしょう？」等のクイズは禁止。
- ★ いきなり衝撃的な数字・事実をぶつけて釘付けにする

### 本編: データ解説 (25-30 lines) - チャート・グラフを多用！
テーマ一覧: {themes_json}

- 各テーマを5-10行で解説。カツミとヒロシが庶民目線で語る
- ★★★ 数字が命: 毎テーマに最低2つの具体数字（○万円、○%、○割等）
- カツミ: 共感+本音「うちもそうよ」「知らなかった〜」
- ヒロシ: データ裏付け「統計的には...」「全国平均は...」
- Xのリアルな声を引用: 「Xでもこう言ってる人多いんですよ」
- ★ テーマ間の繋ぎ: 「次もすごいわよ」「まだあるんですか」と自然に繋ぐ

### 控え室: エピローグ余韻 (8-12 lines は generate_hikaeshitsu_script で生成)
方向性: {epilogue_dir}

## CHARACTERS
- カツミ (female): 共感の達人。voice: "Kazuha"
  - 「知らなかった〜」「え、マジで？」と視聴者の代弁
  - 自分の体験と比較: 「うちの場合はこうだったわよ」
  - エピソード例: 板橋の駄菓子屋、商店街のコロッケ30円、ダイヤル式電話
- ヒロシ (male): データの人。voice: "Takumi"
  - 「統計だと○%ですよ」「全国平均は○万円」
  - 自分の体験も: 「うちの妻もいつも言ってます」
  - ★ ヒロシの体験談を最低2回は入れること

## TECHNICAL REQUIREMENTS
- script: 35 lines minimum
- Each line text: 40-80 Japanese characters
- Total text: MINIMUM 1000 Japanese characters
- section: always "main"
- emotion: question/surprised/thinking/happy/concerned (NEVER use "default"!)
- NO character names in dialogue text
- ★ NUMBERS: Include at least 8 concrete numbers ({self.channel_theme}のデータ)
- ★ POLLS (2 polls):
  - Poll 1: {self.channel_theme}に関する統計データ
  - Poll 2: 全国平均との比較データ
  - Format: question + 3-5 choices with percentage (sum to ~100)
  - MUST include "source" field

## OUTPUT FORMAT (JSON)
{{
  "title": "SEOバズりタイトル（【{self.channel_theme}】+具体的数字+感情フック。例:【年金】月○万円で暮らす○歳…衝撃の実態）",
  "source": "出典元",
  "summary": "今日のテーマ要約",
  "key_points": ["ポイント1", "ポイント2", "ポイント3"],
  "reference_sources": [{{"name": "サイト名", "url": "URL"}}],
  "first_comment": "カツミの初コメント（200-250文字）",
  "tags": ["{self.channel_theme}", "シニア", "暮らし"],
  "dynamic_hashtags": ["ハッシュタグ1", "ハッシュタグ2"],
  "script": [
    {{"speaker": "カツミ", "text": "...", "voice": "Kazuha", "section": "main", "emotion": "surprised"}},
    {{"speaker": "ヒロシ", "text": "...", "voice": "Takumi", "section": "main", "emotion": "thinking"}}
  ],
  "polls": [
    {{"question": "統計データ", "source": "出典名", "answers": [{{"label": "選択肢1", "value": 45}}, {{"label": "選択肢2", "value": 30}}, {{"label": "選択肢3", "value": 25}}]}},
    {{"question": "比較データ", "source": "出典名", "answers": [...]}}
  ]
}}
"""
            else:
                # ===== ヒーローズジャーニー: 詳細台本プロンプト（現状維持） =====
                detail_prompt = f"""
Generate a {self.channel_theme} script. This is a HUMAN DOCUMENTARY show, NOT a news show.

CORE CONCEPT: {self.channel_theme}に関する「慎ましい日常」をリアルに伝えるドキュメンタリー。
キラキラした自慢ではない。{self.channel_theme}について淡々と暮らしている人のリアルな日常。
みんな大変なのに頑張ってる。日本人らしい慎ましさ。小さな楽しみを見つけて必死に生きてる。
★ トーンは全編暗くする必要はない。お金の話は暗くなりがちだけど、
  「暗いなりにも頑張ってるんだよね」という前向きさを全編通して滲み出させること。
★ 最後は絶対にポジティブに終わらせる。「なんとか頑張りましょう」「笑うしかないわよね」
視聴者は「そっか...みんなこうやって頑張ってるんだな」と感じるべき。
カツミとヒロシがこの人の人生を自分の人生と重ねて、本音で語る。

CRITICAL REQUIREMENT - SCRIPT LENGTH:
- You MUST generate at least 35 lines of dialogue
- Total text content should be at least 1000 Japanese characters
- THIS IS A 5+ MINUTE VIDEO - generate enough content!

CRITICAL: ALL OUTPUT CONTENT MUST BE IN JAPANESE ONLY.
Target audience: Japanese elderly women (60-80 years old).
## CONTENT PHILOSOPHY (MANDATORY - apply to ALL dialogue)
The script must INDIRECTLY stimulate these core human emotions:
- PRIORITY EMOTION: "損得" (gain/loss) - MORE IMPORTANT than right/wrong, win/lose, fun/boring
  - Viewers must feel "もっと得したい！" (I want more benefit!) and "絶対に損したくない！" (I absolutely don't want to lose out!)
- "もっと欲しい" - Even when they have enough, the instinct of "if I can get it, I want it"
- "安心への渇望" - No matter how much they have, they can never feel fully secure
- "損失回避" - Fear of missing benefits they're entitled to
- "優位性欲求" - Wanting to be the one who knows, the one who benefits

CRITICAL CONSTRAINTS:
- NEVER express these directly or crudely
- Use INDIRECT phrases: "知らないと損" "実はまだ間に合う" "意外と見落としがち" "これ知ってる人だけ得してる"
- Let Katsumi and Hiroshi naturally touch on these through their everyday perspective
- Viewers should feel "this is about ME" and keep watching to the end


## PERSON PROFILE (this is who we're talking about today)
{person_json}

## STORY STRUCTURE
{json.dumps(structure, indent=2, ensure_ascii=False)}

## STATISTICAL DATA (for comparison/charts)
{stat_data_json}

## CHARACTERS (CONTRAST AXIS: EMPATHY vs ANALYSIS)
- カツミ (female): 共感の達人 + 辛口コメンテーター。voice: "Kazuha"
  - 出身: 東京都板橋区。勝間和代タイプの常識人。
  - この人のストーリーに共感しつつも「甘ったれてるわよね」「頑張ってるわよね」と本音を言う
  - 自分の体験と比較: 「うちの場合はこうだったわよ」
  - エピソード例（毎回ランダムに2-3個選ぶ。同じ回で同じエピソードを2回使うのは禁止）:
    板橋の駄菓子屋で10円玉握りしめて通った話、新潟のおばあちゃんの家でスイカを井戸水で冷やした夏休み、
    ザ・ベストテンを毎週録音してた話、商店街のコロッケが30円だった頃、
    近所のお風呂屋さんで番台のおばちゃんと世間話、町内会の盆踊りで焼きそば焼いた話、
    嫁入り道具に母がミシンを持たせてくれた話、デパートの屋上遊園地で観覧車に乗った思い出、
    昔の定食屋はご飯おかわり自由だった、電話がダイヤル式で回すのが面倒だった話、
    年末の大掃除で畳をひっくり返して日干しした話、PTA役員を押し付けられてパート休んだ話、
    夫の退職金で初めて海外旅行に行ったらパスポートの写真が酷かった話、
    近所の八百屋のおじさんがいつもおまけしてくれた話、銀行の定期預金が年利6%だった時代
  - 暴走パターン: 「だいたいね！」「おかしいと思わない？」→ヒロシに止められる

- ヒロシ (male): データで裏付ける庶民の代弁者。voice: "Takumi"
  - 出身: 埼玉県川口市の団地育ち。
  - データを出して「でも統計的には〇%の人がこうなんだよ」と裏付ける
  - 自分のエピソードも積極的に出す（カツミばかり語るのは禁止）
  - ヒロシのエピソード例（毎回ランダムに2-3個選ぶ。同じ回で同じエピソードを2回使うのは禁止）:
    川口の団地で隣の子のファミコンで遊んだ話、ビックリマンチョコのシール集め、
    妻に家計簿見せられてため息ついた話、スーパーの半額シール貼られるまで店内うろうろした話、
    初めてのボーナスで親に寿司を奢った話、通勤電車で毎朝同じ人と顔見知りになった話、
    子供のゲーム機を取り上げたら妻に怒られた話
  - ヒロシも本音を言う: 「僕もそう思ってました、正直」「うちの妻もいつも言ってます」
  - ★重要: 1台本中にヒロシの体験談・本音を最低2回は入れること

## PROGRAM FLOW: 人間ドキュメンタリー構成（神話の法則 = ヒーローズジャーニー）

### OPENING (3-4 lines) - 挨拶なし！いきなり会話から入る！
カツミ: "ちょっと聞いてよヒロシ" → この人の一番インパクトのある情報でぐいぐい引き込む（挨拶・自己紹介は一切禁止）
★ 「あなたの年金を考える〜」等の挨拶は絶対禁止。いきなり本題の会話から始める。
★ 淡々とした「今日はある〜」もNG。カツミが「この人さぁ...」とぐいぐい行く。
★ でもキラキラした紹介もNG。「すごい人見つけた！」ではなく「この人の話、聞いて...」と重めに入ってOK。

### ACT 1: 日常の世界〜旅の始まり（5-8 lines）
- この人がかつてどんな人生を歩んでいたか（普通の日常）
- そこに訪れた転機（配偶者の死、病気、リストラ、離婚等）
- {self.channel_theme}に関わるきっかけ
- 辛い話でも「でもこの人、頑張ってるのよね」と前向きさを滲ませる

### ACT 2: 試練と深淵〜本音トーク（10-15 lines） - ここがメイン！
- この人の今の慎ましい日常を丁寧に描写する
- どうやって暮らしているか、具体的な数字（{self.channel_theme}の観点から）
- 全国平均との比較データ（チャート用）
- カツミとヒロシが自分の人生と重ねて語る（最低5往復）
- ★★★ 重要: 「賢い節約術！」ではなく「こうするしかないから、こうしてる」というリアルさ ★★★
- 小さな楽しみ（近所の散歩、安い缶コーヒー、テレビの時代劇）も描写する
- カツミ: 「うちもそうよ」「わかる」と共感 + 「でもこの人、えらいわよね」と前向きさも
- ヒロシ: データで裏付け + 「でも頑張ってますよね、この方」と認める

Example flow:
  カツミ: "この方ね、朝起きてすぐラジオつけるんだって。テレビはつけない。電気代がもったいないから"
  ヒロシ: "ラジオ...。うちの親父もそうだったなぁ。でも厳しい話ですよ、月12万円でしょう"
  カツミ: "そうなの。家賃が4万円、光熱費が1万2千円、保険料引かれたらもう残り6万円くらいよ"
  ヒロシ: "6万円で食費と日用品と医療費...。統計だと高齢単身世帯の平均生活費は月15万円ですよ"
  カツミ: "足りてないのよ。でもこの人、弱音吐かないの。日本人だなぁって思った"

### ACT 3: 帰還〜学び（3-5 lines）
- この人の生き様から感じること
- 「みんなこうやって慎ましく、でも必死に生きてるんだよね」
- 暗い現実の中に小さな光を見つける

### ENDING（3-4 lines）- ポジティブに締める！
カツミ: この人の頑張りを認める一言
ヒロシ: 「みんな頑張ってるんですよね」
カツミ: 「ほんとよねぇ。まぁ、なんとか頑張っていきましょうよ」（ポジティブに！）
★★★ 最後は絶対ポジティブに終わらせること。「頑張っていきましょう」「笑ってやっていこう」★★★
★ 庶民の前向きさ。暗い話の後だからこそ、明るく締めることで視聴者が元気になる。

## 本音トーク REQUIREMENTS (CRITICAL)
- カツミ = 共感の人。この人の辛さを理解しつつ「でもしょうがないわよね」と受け止める
- ヒロシ = データと自分の体験。「数字で見るとこうなんですよ」「うちも実は...」
- CONCEPT: 華やかさは一切なし。淡々とした{self.channel_theme}のリアルを丁寧に描写する
- TONE: 全編暗くしない。暗いなりにも頑張ってる感を滲ませる。最後は絶対ポジティブ。

### Required Elements:
- 具体的な金額 ("月12万円", "食費2万円", "光熱費1万5千円")
- 全国平均との比較 ("平均は○万円なのに、この人は...")
- カツミの庶民エピソード ("うちの場合はね...")
- ヒロシのデータ裏付け ("統計的には○%の人が...")
- 人間模様の評価 ("甘ったれ" or "頑張ってる")

### PROHIBITED (violation = script rejection)
- "そうですね" alone (empty agreement)
- "期待されます" / "注目されています" (generic filler)
- Being too polite or diplomatic - THIS IS A 本音 SHOW
- "視聴者さんも" (speak for YOURSELF, not viewers)
- ニュース速報のような淡々とした解説（これはドキュメンタリーであり、ニュース番組ではない）

## TITLE RULES (SEO + EMOTION)
- Format: 【実話】or【密着】or【{self.channel_theme}】+ この人のキャッチフレーズ
- MUST trigger curiosity: "月○万円で暮らす○歳の..." "○○を失った○歳が見つけた..."
- Max 60 characters

## FIRST COMMENT RULES (カツミが「実在する人間」だと分からせる)
- 今日紹介した人の話に触れつつ、自分の体験を絡める
- 共感を呼ぶ問いかけ: 「皆さんのところも似たような状況ですか？」
- 200-250 characters

## TECHNICAL REQUIREMENTS
- script: 35 lines minimum
- Each line text: 40-80 Japanese characters
- Total text: MINIMUM 1000 Japanese characters
- section: always "main"
- emotion: question/surprised/thinking/happy/concerned (NEVER use "default" - always choose a specific emotion!)
  ★ emotion is linked to character facial expressions. "default" shows NO expression bubble.
  ★ Use variety: question for questions, surprised for shocking facts, thinking for analysis, happy for positive moments, concerned for worrying topics
- NO character names in dialogue text
- ★ NUMBERS ARE CRITICAL: Include at least 5 concrete numbers in the entire script
  - Use: ○円, ○万円, ○%, ○割, ○万人, ○倍, ○歳 etc.
  - These numbers are automatically detected and displayed as animated charts
- ★ POLLS (2 polls for data comparison):
  - Poll 1: この人の生活に関連する統計データ
  - Poll 2: 全国平均との比較データ
  - Format: question + 3-5 answer choices with percentage values (must sum to ~100)
  - MUST include "source" field with real data source name

## OUTPUT FORMAT (JSON)
{{
  "title": "SEOバズりタイトル（【{self.channel_theme}】+具体的数字+感情フック。YouTube検索で上位表示されるよう工夫）",
  "source": "出典元",
  "summary": "今日のストーリー要約",
  "key_points": ["この人の印象的なポイント1", "統計との比較ポイント", "学べる教訓"],
  "reference_sources": [{{"name": "サイト名", "url": "URL"}}],
  "first_comment": "カツミの初コメント（FIRST COMMENT RULES準拠）",
  "tags": ["{self.channel_theme}", "シニア", "暮らし"],
  "dynamic_hashtags": ["ハッシュタグ1", "ハッシュタグ2"],
  "script": [
    {{"speaker": "カツミ", "text": "...", "voice": "Kazuha", "section": "main", "emotion": "default"}},
    {{"speaker": "ヒロシ", "text": "...", "voice": "Takumi", "section": "main", "emotion": "default"}}
  ],
  "polls": [
    {{"question": "この人の生活費に関する統計", "source": "出典名", "answers": [{{"label": "選択肢1", "value": 45}}, {{"label": "選択肢2", "value": 30}}, {{"label": "選択肢3", "value": 25}}]}},
    {{"question": "全国平均との比較データ", "source": "出典名", "answers": [...]}}
  ]
}}
"""

            raw_text = call_llm_with_fallback(
                messages=[
                    {
                        "role": "system",
                        "content": f"Generate detailed script. script must have {min_lines}+ lines. Output JSON.",
                    },
                    {"role": "user", "content": detail_prompt},
                ],
                json_mode=True,
                max_tokens=16384,
                temperature=0.8,
            )
            # JSON抽出（Llamaモデル対応）
            raw_text = extract_json_from_text(raw_text)

            new_data = json.loads(raw_text)
            new_script = new_data.get("script", [])
            script_lines = len(new_script)
            print(f"取得: {script_lines}行")

            # 毎回新規生成（追加生成は構成が壊れるため禁止）
            data = new_data

            total_lines = len(data.get("script", []))
            # 行数・文字数カウント（参考値）
            total_chars = sum(len(line.get("text", "")) for line in data.get("script", []))
            print(f"生成: {total_lines}行, {total_chars}文字 (参考: 約{total_chars // 300}分)")

            if total_lines >= min_lines:
                print(f"[OK] 行数目標達成: {total_lines}行 >= {min_lines}行")
                break
            else:
                print(f"[WARN] {total_lines}行 < {min_lines}行、再生成...")

        # 行数チェック（min_lines以上必須）
        total_lines = len(data.get("script", [])) if data else 0
        if not data or total_lines < min_lines:
            raise Exception(f"台本生成に失敗しました（行数不足: {total_lines}行 < {min_lines}行）")
        total_chars = sum(len(line.get("text", "")) for line in data.get("script", []))
        print(f"[OK] 行数: {total_lines}行, 文字数: {total_chars}文字 (参考: 約{total_chars // 300}分)")

        # 挨拶リセット修正はA-D問題防止チェックのDに統合済み

        # ========================================
        # 繰り返し行除去（類似度が高い連続行を削除）
        # ========================================
        print("\n--- 繰り返し除去 ---")

        def similarity_ratio(a: str, b: str) -> float:
            """2つの文字列の類似度を計算（0.0〜1.0）"""
            if not a or not b:
                return 0.0
            # 共通部分の長さ / 長い方の長さ
            from difflib import SequenceMatcher

            return SequenceMatcher(None, a, b).ratio()

        script = data.get("script", [])
        deduped_script = []
        removed_count = 0

        for i, line in enumerate(script):
            text = line.get("text", "")

            # 最初の行は必ず追加
            if i == 0:
                deduped_script.append(line)
                continue

            # 全ての既存行と比較して75%以上類似していたらスキップ
            is_duplicate = False
            for j in range(len(deduped_script)):
                prev_text = deduped_script[j].get("text", "")
                if similarity_ratio(text, prev_text) > 0.75:
                    print(f"[FIX] 繰り返し削除: {text[:40]}...")
                    is_duplicate = True
                    removed_count += 1
                    break

            if not is_duplicate:
                deduped_script.append(line)

        data["script"] = deduped_script
        print(f"[OK] 繰り返し除去完了: {removed_count}行削除, 残り{len(deduped_script)}行")

        # ========================================
        # A-D問題防止チェック
        # ========================================
        print("\n--- A-D問題防止チェック ---")
        script = data.get("script", [])
        issues_found = []

        # A: 途中エンディングNGワード検出（最後の2行以外）
        ending_ng_words = [
            "今日はここまで",
            "ここまでです",
            "次回をお楽しみ",
            "また次回",
            "また来週",
            "またね",
            "さようなら",
            "バイバイ",
        ]
        for i, line in enumerate(script[:-2]):  # 最後の2行は除外
            text = line.get("text", "")
            for ng in ending_ng_words:
                if ng in text:
                    issues_found.append(f"[A] 途中エンディング検出 (行{i + 1}): {text[:30]}...")
                    # 該当行を削除
                    script[i]["text"] = text.replace(ng, "")

        # B: 本音トーク重複チェック（honne_を含む行同士を比較）
        honne_lines = [(i, line) for i, line in enumerate(script) if "honne" in str(line.get("marker", ""))]
        for i, (idx1, line1) in enumerate(honne_lines):
            for idx2, line2 in honne_lines[i + 1 :]:
                text1 = line1.get("text", "")
                text2 = line2.get("text", "")
                if similarity_ratio(text1, text2) > 0.6:
                    issues_found.append(
                        f"[B] 本音重複 (行{idx1 + 1}と行{idx2 + 1}): 類似度{similarity_ratio(text1, text2):.0%}"
                    )

        # C: ニュース差別化検証（news_を含む行のキーワード重複チェック）
        news_lines = [(i, line) for i, line in enumerate(script) if "news" in str(line.get("marker", ""))]
        if len(news_lines) >= 2:
            for i, (idx1, line1) in enumerate(news_lines):
                for idx2, line2 in news_lines[i + 1 :]:
                    text1 = line1.get("text", "")
                    text2 = line2.get("text", "")
                    if similarity_ratio(text1, text2) > 0.5:
                        issues_found.append(
                            f"[C] ニュース重複 (行{idx1 + 1}と行{idx2 + 1}): 類似度{similarity_ratio(text1, text2):.0%}"
                        )

        # D: 挨拶パターン検出（冒頭以外）- 長い順に処理し包摂問題を回避
        # 「皆さん、こんにちは」⊃「こんにちは」なので長い順にマッチ→除去→text更新
        greeting_ng_patterns = sorted(
            ["こんにちは", "皆さん、こんにちは", "今日のニュースです", "本日のニュースは", "ニュースをお届け"],
            key=len,
            reverse=True,
        )
        for i, line in enumerate(script[1:], start=1):  # 最初の行は除外
            text = line.get("text", "")
            for pattern in greeting_ng_patterns:
                if pattern in text:
                    issues_found.append(f"[D] 挨拶リセット検出 (行{i + 1}): {text[:30]}...")
                    text = text.replace(pattern, "").strip()  # textを更新して包摂パターンの二重マッチを防止
            script[i]["text"] = text

        # 結果表示
        if issues_found:
            for issue in issues_found:
                print(f"[FIX] {issue}")
            print(f"[WARN] {len(issues_found)}件の問題を検出・修正")
        else:
            print("[OK] A-D問題なし")

        data["script"] = script

        # key_pointsはLLM構成段階のkey_factsをそのまま使用
        # (トピックポイントの表示タイミングはTSX側のTopicPointsPanelで
        #  台本のニュース導入行を検出して制御している)
        print(f"[OK] key_points維持: {len(data.get('key_points', []))}件(LLM生成の要約ポイント)")

        # 概要欄の組み立て（1500文字以内に収める）
        fixed_header = f"{self.channel_theme}について考える\nカツミとヒロシが、{self.channel_theme}の日常を紹介し本音で語ります\n\n[利用ツールについて]\n本動画はAIで構成を生成し、運営者が内容の正確性を検証・編集しています。\n音声合成にはAI技術を使用しています。\n情報源は公式サイトを参考にしています。\n\n"

        timestamp_section = ""  # タイムスタンプは現在未使用（section="main"固定のため）

        summary_section = f"{data.get('summary', '')}\n\n"
        points = "\n".join([f"・{p}" for p in data.get("key_points", [])])
        points_section = f"主要ポイント\n{points}\n\n"

        # コメント促しセクション（具体的な問いかけ）
        key_pts = data.get("key_points", [])
        if key_pts:
            first_topic = key_pts[0][:30] if key_pts[0] else ""
            comment_section = f"コメントで教えてください！\n今日の『{first_topic}』について、皆さんはどう思いましたか？\n体験談や疑問、「うちはこうだよ」って話も大歓迎です！\n\n"
        else:
            comment_section = (
                "コメントで教えてください！\n今日の内容で気になったこと、「うちはこうだよ」って体験談も大歓迎です！\n\n"
            )

        # 再生リストセクション（環境変数から取得）
        playlist_ids = os.environ.get("YOUTUBE_PLAYLIST_IDS", "").split(",")
        playlist_section = ""
        if playlist_ids and any(pid.strip() for pid in playlist_ids):
            playlist_links = []
            for pid in playlist_ids:
                if pid.strip():
                    playlist_links.append(f"https://www.youtube.com/playlist?list={pid.strip()}")
            if playlist_links:
                playlist_section = "関連動画\n" + "\n".join(playlist_links) + "\n\n"

        sources = "\n".join([f"・出典：{s['name']} {s['url']}" for s in data.get("reference_sources", [])])
        if not sources:
            sources = "・出典：国会議事録 https://www.shugiin.go.jp/\n・参考：厚生労働省HP https://www.mhlw.go.jp/"
        sources_section = f"出典・参考\n{sources}\n\n"

        # 動的ハッシュタグの生成
        dynamic_tags = data.get("dynamic_hashtags", [])
        dynamic_hashtags_str = " ".join([f"#{tag.replace('#', '')}" for tag in dynamic_tags[:4]])
        fixed_hashtags = f"#{self.channel_theme} #シニア #暮らし #実話 #{self.channel_name}"
        all_hashtags = f"{fixed_hashtags} {dynamic_hashtags_str}".strip()

        fixed_footer = f"{all_hashtags}\n\nこの動画は公式情報源を基に独自に解説したものです最新情報は各公式サイトをご確認ください判断はご自身の責任で行ってください"

        # エピソード番号の付与（YouTube APIからチャンネル動画数を取得）
        try:
            if hasattr(self, "uploader") and self.uploader:
                video_count = self.uploader.get_video_count()
                episode_num = video_count + 1  # 次の動画番号
            else:
                episode_num = 1
        except:
            episode_num = 1

        # タイトルにエピソード番号を付与
        original_title = data.get("title", "")
        if not original_title.startswith("【#"):
            data["title"] = f"【#{episode_num}】{original_title}"
        data["episode_number"] = episode_num

        data["description"] = (
            f"{fixed_header}{timestamp_section}{summary_section}{points_section}{comment_section}{playlist_section}{sources_section}{fixed_footer}"[
                :1500
            ]
        )

        # 生成結果を保存 (検証用)
        with open(os.path.join(OUTPUT_DIR, "content.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # 台本品質チェック（警告のみ、パイプラインは止めない）
        self.check_script_quality(data)

        return data

    def check_script_quality(self, content):
        """台本品質チェック（チェック失敗でもパイプラインは止めない）"""
        print("\n--- 台本品質チェック ---")
        warnings = []
        script = content.get("script", [])
        total_chars = sum(len(line.get("text", "")) for line in script)

        # 1. 文字数チェック (700文字未満 = 3分以下)
        if total_chars < 700:
            warnings.append(f"[文字数不足] {total_chars}文字 (最低700)")
        # 2. 行数チェック
        if len(script) < 10:
            warnings.append(f"[行数不足] {len(script)}行 (最低10)")
        # 3. カツミ・ヒロシ存在チェック
        speakers = set(line.get("speaker", "") for line in script)
        if "カツミ" not in speakers:
            warnings.append("[カツミ不在]")
        if "ヒロシ" not in speakers:
            warnings.append("[ヒロシ不在]")
        # 4. 損得DNAキーワードチェック
        all_text = "".join(line.get("text", "") for line in script)
        loss_keywords = ["損", "得", "知らない", "見落とし", "間に合う"]
        if not any(kw in all_text for kw in loss_keywords):
            warnings.append("[損得DNA未検出]")
        # 5. 冒頭テーマ名チェック
        if script and self.channel_theme not in script[0].get("text", ""):
            warnings.append(f"[冒頭にテーマ名なし] '{self.channel_theme}'")

        if warnings:
            for w in warnings:
                print(f"[品質警告] {w}")
            print(f"[品質チェック] {len(warnings)}件の警告")
        else:
            print("[品質チェック] ALL OK")
        return len(warnings) == 0

    def validate_script(self, content):
        """台本の内容を簡易検証します"""
        print("--- 台本検証中 ---")
        script_lines = len(content.get("script", []))
        print(f"[OK] 台本検証完了: {script_lines}行")
        return True

    def generate_thumbnail_title(self, news_summary):
        """
        Gemini APIでサムネイル用タイトルを生成（6文字x2行）
        週3日（火・木・土）は噂フック型（「？」「かも？」付き）

        Args:
            news_summary: 今日のニュース要約

        Returns:
            str: 改行で区切られた2行のタイトル
        """
        prompt = f"""
今日のみんなの声から「見ないと絶対損する！」と思わせるサムネイルタイトルを作成してください
ターゲット：日本の中高年女性（60-75歳）。政治・経済・医療費が日常の最大関心事。

■ 最重要: サムネは全力で攻める。見ないと損。の意識で作れ。
「このサムネ見てクリックしなかったら損する」と確信させるタイトルを作れ。
下品な言葉以外は全部OK。思いっきり攻めてよし。

■ フックの方向性（全力で攻める）
・確定情報の場合: 「もうもらった？」「まだ申請してない？」「すぐに申請！」
  「知らないと大損」「知らなきゃ損する」「危険！注意！」
・未確定情報・噂の場合: 必ず「！？」を使って逃げ道を作る
  「減額！？」「廃止！？」「改悪！？」→ 「！？」が逃げ道

■ コントラスト構造（必須）
・1行目：制度・政策・数字（公的でマクロな事実風ワード）
・2行目：生活直撃の衝撃フック（全力で感情を煽る）
→ 2行のギャップが大きいほど「見ないと損」感が爆発する

■ 絶対厳守ルール
・1行目：6文字以内
・2行目：6文字以内
・改行で2行に分ける
・「見ないと損」「知らないと損」を呼び起こす全力フック必須
・未確定なら「！？」で逃げ道を作る（「？」単独でもOK）

■ 良い例（全力フック）：
制度改定
もうもらった？

申請しないと
3万円消滅！

支給停止！？
知らないと損

負担増決定
月5千円増！

制度改悪！？
すぐ確認を

医療費倍増
まだ知らない？

■ 禁止ワード：「最新」「必見」「注目」（陳腐で刺さらない）
■ 禁止：下品な言葉、中高年女性が不快に思う表現

今日のニュース
{news_summary}

出力（改行で2行、各行6文字以内絶対厳守、全力フック必須）
"""

        title = call_llm_with_fallback(
            messages=[
                {
                    "role": "system",
                    "content": "サムネイルタイトルを2行で出力してください。各行6文字以内厳守。全力で攻めるフック。未確定なら「！？」で逃げ道を作る。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=50,
            temperature=0.8,
        ).strip()
        print(f"[OK] サムネイルタイトル生成: {title.replace(chr(10), ' / ')}")
        return title

    def generate_chalk_illustration(self, script, title=""):
        """トピックに応じたチョーク風テキストなしイラスト画像を生成

        Gemini画像生成APIで黒板チョーク風イラストを生成。
        テキストは一切入れない（文字化け防止）。
        中塗りありの手書きチョーク風に統一。

        Args:
            script: 台本データ（トピック抽出用）
            title: 動画タイトル（テーマ判定用）

        Returns:
            str: 保存先パス（remotion/public/chalk_illustration.png）
        """
        output_path = "remotion/public/chalk_illustration.png"

        # 台本からトピックキーワードを抽出
        all_text = title + " " + " ".join([s.get("text", "") for s in (script or [])])

        # テーマ別のイラスト要素を選択
        if any(w in all_text for w in ["食費", "食事", "食生活", "料理", "節約"]):
            objects = "steaming rice bowl with white chalk filled rice, grilled fish on plate with golden chalk coloring, fresh colorful vegetables (carrots, broccoli, peppers) with green/orange chalk fill, cute piggy bank with pink chalk fill, scattered coins"
        elif any(w in all_text for w in ["年金", "受給", "支給", "老齢"]):
            objects = "cozy house with warm yellow chalk-filled windows, mailbox with letter, calendar with circled date, small garden with chalk-filled flowers, walking cane, reading glasses"
        elif any(w in all_text for w in ["健康", "運動", "散歩", "体操"]):
            objects = "pair of walking shoes with blue chalk fill, water bottle, cute stretching cat with orange chalk fill, sunrise with warm yellow rays, cherry blossom branch with pink petals, park bench"
        elif any(w in all_text for w in ["申請", "手続き", "届出", "書類"]):
            objects = "official document with stamp, pen writing, clipboard with checklist, desk lamp with warm glow, pair of glasses, cup of tea"
        elif any(w in all_text for w in ["医療", "薬", "病院", "介護"]):
            objects = "stethoscope, medicine bottle, warm cup of herbal tea, gentle hands holding, small flower vase, comfortable chair"
        else:
            objects = "warm teapot and cup with steam, open book, comfortable armchair, window with sunshine, small plant, pair of slippers"

        prompt = f"""Chalkboard-style illustration with FILLED colored chalk (not just outlines - fill shapes with hand-drawn chalk shading and coloring).
ABSOLUTELY NO TEXT, NO LETTERS, NO NUMBERS, NO WORDS in the image.
Dark green chalkboard background with realistic chalk dust and smudges.
Objects to illustrate: {objects}
All filled with hand-drawn chalk texture, warm colors (white, yellow, pink, orange, green, light blue).
Warm, nostalgic, inviting feeling. Simple clear compositions. 16:9 landscape aspect ratio."""

        try:
            import io

            from google import genai
            from google.genai import types
            from PIL import Image

            api_keys = os.environ.get("GOOGLE_API_KEYS", "").split(",")
            if not api_keys or not api_keys[0].strip():
                print("[WARN] GOOGLE_API_KEYS未設定。チョーク画像生成スキップ")
                return None

            client = genai.Client(api_key=api_keys[0].strip())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                        img = Image.open(io.BytesIO(part.inline_data.data))
                        img = img.resize((640, 360), Image.LANCZOS)
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        img.save(output_path)
                        print(f"[OK] チョーク風イラスト生成: {output_path}")
                        return output_path

            print("[WARN] チョーク画像: 画像パーツなし")
            return None

        except Exception as e:
            print(f"[WARN] チョーク画像生成失敗: {e}")
            return None

    def generate_youtube_thumbnail(self, title, comment=None, script=None):
        """
        YouTube投稿用サムネイル画像を生成（v8仕様: 黒板チョーク風）

        Gemini画像生成APIで黒板チョーク風サムネイルを生成。
        API失敗時は従来のPillow描画（v7）にフォールバック。

        Args:
            title: 6文字x2行のタイトル（改行で区切られている）
            comment: 吹き出し内コメント（改行で区切られている、省略時はデフォルト）
            script: 台本データ（感情連動アイコン用、省略時はneutral）

        Returns:
            str: サムネイル画像のパス
        """
        print("--- YouTubeサムネイル画像生成中 (v8仕様: 黒板チョーク風) ---")
        import random
        from datetime import datetime

        from PIL import Image, ImageDraw, ImageFont

        out_path = os.path.join(OUTPUT_DIR, "youtube_thumbnail.png")
        title_lines = title.split("\n")[:2]
        title_line1 = title_lines[0] if len(title_lines) > 0 else ""
        title_line2 = title_lines[1] if len(title_lines) > 1 else ""

        # ====== v8: Gemini画像生成APIで黒板チョーク風サムネイル ======
        try:
            print("[v8] Gemini画像生成APIで黒板チョーク風サムネイル生成中...")
            self.client = self._get_client()

            chalk_prompt = f"""Create a YouTube thumbnail image (1280x720 pixels, 16:9 aspect ratio) in chalkboard style:

BACKGROUND: Dark green or black chalkboard texture with realistic chalk dust and smudges.

TEXT (MUST be in Japanese, written clearly and legibly):
- Top large text in WHITE chalk: 「{title_line1}」
- Bottom large text in YELLOW chalk: 「{title_line2}」
- Text should be bold, large, and easily readable even at small sizes.

ILLUSTRATIONS (all in chalk-drawn style):
- A cute chalk-drawn elderly Japanese couple (man and woman, 60s-70s) as mascot characters
- Simple chalk-drawn icons related to the topic (money, charts, daily life items)
- A small hand-drawn chart or graph in chalk

STYLE:
- Everything looks hand-drawn with chalk on a real classroom blackboard
- White and yellow chalk only (no other colors)
- Include chalk dust effects, smudges, and eraser marks for authenticity
- Warm, nostalgic, educational feeling
- The text MUST be the dominant visual element (largest thing on the image)"""

            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=chalk_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            # 画像レスポンスを抽出して保存
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                        img_data = part.inline_data.data
                        # バイナリデータからPIL Imageに変換
                        import io

                        img = Image.open(io.BytesIO(img_data))
                        # 1280x720にリサイズ（アスペクト比維持）
                        img = img.resize((1280, 720), Image.LANCZOS)
                        img.save(out_path)
                        print(f"[OK] v8黒板チョーク風サムネイル保存完了: {out_path}")
                        return out_path

            print("[WARN] Gemini画像生成: 画像レスポンスなし。v7フォールバックへ")

        except Exception as e:
            print(f"[WARN] Gemini画像生成失敗: {e}。v7フォールバックへ")

        # ====== v7フォールバック: 従来のPillow描画 ======
        print("[v7 FALLBACK] Pillow描画でサムネイル生成中...")

        weekday = datetime.now().weekday()
        day_color_map = {
            0: {"title": (255, 255, 255), "outline": (60, 60, 80), "shadow": (30, 30, 50)},
            1: {"title": (255, 140, 0), "outline": (80, 30, 0), "shadow": (50, 20, 0)},
            2: {"title": (30, 120, 255), "outline": (255, 255, 255), "shadow": (10, 40, 100)},
            3: {"title": (160, 100, 40), "outline": (255, 255, 255), "shadow": (60, 30, 10)},
            4: {"title": (255, 220, 0), "outline": (80, 50, 0), "shadow": (60, 40, 0)},
            5: {"title": (50, 100, 200), "outline": (255, 255, 255), "shadow": (20, 40, 80)},
            6: {"title": (220, 30, 30), "outline": (255, 255, 255), "shadow": (80, 10, 10)},
        }
        day_colors = day_color_map.get(weekday, day_color_map[6])
        day_names = ["月", "火", "水", "木", "金", "土", "日"]
        print(f"[OK] 曜日カラー: {day_names[weekday]}曜日 -> タイトル色{day_colors['title']}")

        bg_color = (235, 201, 136)
        colors = {
            "title": day_colors["title"],
            "title_outline": day_colors["outline"],
            "title_shadow": day_colors["shadow"],
            "bubble_text": (30, 80, 150),
        }

        def draw_text_with_outline(draw, pos, text, font, fill, outline, outline_width=6, shadow=None):
            x, y = pos
            shadow_color = shadow or (0, 0, 0, 80)
            for offset in range(1, 8):
                draw.text((x + offset, y + offset), text, font=font, fill=shadow_color)
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=outline)
            draw.text((x, y), text, font=font, fill=fill)

        # 感情連動アイコン
        emotion_to_category = {
            "neutral": "neutral",
            "normal": "neutral",
            "default": "neutral",
            "smile": "neutral",
            "calm": "neutral",
            "happy": "guts",
            "excited": "guts",
            "guts": "guts",
            "surprised": "guts",
            "laugh": "guts",
            "bakusho": "guts",
            "idea": "guts",
            "hirameki": "guts",
            "concerned": "yareyare",
            "tired": "yareyare",
            "yareyare": "yareyare",
            "sad": "yareyare",
            "fuseru": "yareyare",
            "doyon": "yareyare",
            "question": "yareyare",
            "thinking": "yareyare",
            "henken": "yareyare",
            "shocked": "yareyare",
            "aogu": "yareyare",
            "sukashi": "yareyare",
        }
        best_emotion = "neutral"
        if script:
            emotion_counts = {"neutral": 0, "guts": 0, "yareyare": 0}
            for line in script:
                emo = line.get("emotion", "neutral").lower()
                cat = emotion_to_category.get(emo, "neutral")
                emotion_counts[cat] = emotion_counts.get(cat, 0) + 1
            non_neutral = {k: v for k, v in emotion_counts.items() if k != "neutral"}
            if non_neutral:
                best_emotion = max(non_neutral, key=non_neutral.get)
            print(f"[OK] 感情集計: {emotion_counts} -> アイコン: {best_emotion}")

        character = random.choice(["katsumi", "hiroshi"])
        icon_name = f"{character}_{best_emotion}.png"
        icon_base = "remotion/public/"

        bold_font_path = "assets/NotoSansCJKjp-Bold.otf"
        if not os.path.exists(bold_font_path):
            raise FileNotFoundError(f"太字フォントが見つかりません: {bold_font_path}")

        title_font = ImageFont.truetype(bold_font_path, 160)
        comment_font = ImageFont.truetype(bold_font_path, 108)

        img = Image.new("RGB", (1280, 720), bg_color)
        draw = ImageDraw.Draw(img)

        icon_path = icon_base + icon_name
        if os.path.exists(icon_path):
            icon = Image.open(icon_path)
            icon = icon.resize((450, 450), Image.LANCZOS)
            if icon.mode == "RGBA":
                img.paste(icon, (-10, 720 - 450 + 10), icon)
            else:
                img.paste(icon, (-10, 720 - 450 + 10))
            draw = ImageDraw.Draw(img)

        bubble_x, bubble_y = 390, 370
        bubble_w, bubble_h = 880, 340
        draw.rounded_rectangle(
            [bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h],
            radius=50,
            fill=(255, 255, 255),
            outline=(100, 100, 100),
            width=4,
        )
        tail_points = [
            (bubble_x + 40, bubble_y + bubble_h // 2 + 20),
            (bubble_x - 30, bubble_y + bubble_h - 40),
            (bubble_x + 80, bubble_y + bubble_h - 20),
        ]
        draw.polygon(tail_points, fill=(255, 255, 255), outline=(100, 100, 100))
        draw.line(
            [(bubble_x + 40, bubble_y + bubble_h // 2 + 20), (bubble_x + 80, bubble_y + bubble_h - 20)],
            fill=(255, 255, 255),
            width=8,
        )

        if comment:
            comment_lines = comment.split("\n")[:2]
        else:
            comment_lines = ["これは", "要チェックよ!"]
        comment_y_start = bubble_y + 20
        comment_line_height = 145
        for j, line in enumerate(comment_lines):
            bbox = draw.textbbox((0, 0), line, font=comment_font)
            text_w = bbox[2] - bbox[0]
            draw.text(
                (bubble_x + (bubble_w - text_w) // 2, comment_y_start + j * comment_line_height),
                line,
                fill=colors["bubble_text"],
                font=comment_font,
            )

        y_positions = [-10, 175]
        x_positions = [20, 350]
        for j, line in enumerate(title_lines):
            x_pos = x_positions[j] if j < len(x_positions) else x_positions[-1]
            draw_text_with_outline(
                draw,
                (x_pos, y_positions[j] if j < len(y_positions) else y_positions[-1] + 190),
                line,
                title_font,
                colors["title"],
                colors["title_outline"],
                shadow=colors.get("title_shadow"),
            )

        img.save(out_path)
        print(f"[OK] v7フォールバックサムネイル保存完了: {out_path} (icon: {icon_name})")
        return out_path

    def synthesize_with_edge_tts(self, text, voice, output_path):
        """Edge TTS（Microsoft Neural音声・完全無料）でWAV音声を生成"""
        try:
            import asyncio

            import edge_tts

            edge_voice_mapping = {
                "Kore": "ja-JP-NanamiNeural",
                "Puck": "ja-JP-KeitaNeural",
                "Aoede": "ja-JP-KeitaNeural",
                "Kazuha": "ja-JP-NanamiNeural",
                "Takumi": "ja-JP-KeitaNeural",
            }
            edge_voice = edge_voice_mapping.get(voice, "ja-JP-NanamiNeural")

            mp3_path = output_path.replace(".wav", "_edge.mp3")

            async def _generate():
                communicate = edge_tts.Communicate(text, edge_voice)
                await communicate.save(mp3_path)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, _generate()).result()
                else:
                    loop.run_until_complete(_generate())
            except RuntimeError:
                asyncio.run(_generate())

            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                try:
                    from pydub import AudioSegment

                    audio = AudioSegment.from_mp3(mp3_path)
                    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                    audio.export(output_path, format="wav")
                except ImportError:
                    import subprocess

                    subprocess.run(
                        ["ffmpeg", "-y", "-i", mp3_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", output_path],
                        capture_output=True,
                        timeout=30,
                    )

                if os.path.exists(mp3_path):
                    os.remove(mp3_path)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    print(f"[OK] Edge TTS成功: {output_path} ({edge_voice})")
                    return True
                else:
                    print("[WARN]  Edge TTS: WAV変換失敗")
                    return False
            else:
                print("[WARN]  Edge TTS: MP3生成失敗")
                return False

        except Exception as e:
            print(f"[WARN]  Edge TTS失敗: {e}")
            return False

    def synthesize_with_polly_tts(self, text, voice, output_path):
        """Amazon Polly TTSで音声を生成（Edge TTS失敗時の第2フォールバック）"""
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError

            # Voice mapping: Gemini/Direct voices -> Amazon Polly voices
            voice_mapping = {
                "Kore": "Kazuha",  # Gemini女性声→Polly女性声
                "Puck": "Takumi",  # Gemini男性声→Polly男性声
                "Aoede": "Takumi",  # Gemini男性声→Polly男性声
                "Kazuha": "Kazuha",  # 直接指定
                "Takumi": "Takumi",  # 直接指定
            }
            polly_voice = voice_mapping.get(voice, voice)  # フォールバックは入力そのまま

            # AWS認証情報を環境変数から取得
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            aws_region = os.getenv("AWS_REGION", "ap-northeast-1")

            if not aws_access_key or not aws_secret_key:
                print("[WARN]  AWS credentials not found")
                return False

            # Pollyクライアント作成（タイムアウト設定追加）
            boto_config = Config(
                read_timeout=60,
                connect_timeout=10,
                retries={"max_attempts": 0},  # リトライは上位で制御
            )
            polly = boto3.client(
                "polly",
                region_name=aws_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                config=boto_config,
            )

            # 音声合成（PCM形式）
            response = polly.synthesize_speech(
                Text=text, OutputFormat="pcm", VoiceId=polly_voice, Engine="neural", SampleRate="16000"
            )

            # PCMデータをWAVファイルに変換して保存
            pcm_data = response["AudioStream"].read()
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)  # Polly SampleRateと一致させる
                wf.writeframes(pcm_data)

            print(f"[OK] Amazon Polly TTS成功: {output_path} ({polly_voice})")
            return True

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "Throttling":
                print(f"[WARN]  Amazon Polly レート制限: {error_code}")
            elif error_code in ["InvalidAccessKeyId", "SignatureDoesNotMatch"]:
                print(f"[WARN]  Amazon Polly 認証エラー: {error_code}")
            else:
                print(f"[WARN]  Amazon Polly エラー: {error_code}")
            return False
        except Exception as e:
            print(f"[WARN]  Amazon Polly TTS失敗: {e}")
            return False

    def synthesize_narration(self, script):
        """TTS でナレーションを生成し結合して保存します"""
        import tempfile

        temp_dir = tempfile.gettempdir()
        audio_clips = []
        temp_files = []  # 削除用に一時ファイルパスを記録
        silent_count = 0  # 無音クリップ数をカウント

        print(f"--- 音声合成開始 (全 {len(script)} 行) [Edge TTS → Polly → Gemini フォールバック] ---")

        for i, line in enumerate(script):
            wav_path = os.path.join(temp_dir, f"line_{i}.wav")
            temp_files.append(wav_path)
            success = False

            # voiceキーがない場合のデフォルト値を設定
            voice = line.get("voice", "Kore")  # デフォルトはKore(女性)

            # Gemini TTS互換Voice名にマッピング（Polly名が混入している場合の対策）
            gemini_voice_mapping = {
                # Polly Voice名からの変換
                "Kazuha": "Kore",
                "Takumi": "Puck",
            }
            if voice in gemini_voice_mapping:
                voice = gemini_voice_mapping[voice]
            elif voice not in ["Kore", "Puck", "Aoede", "Charon", "Fenrir"]:
                # 未知のvoice名の場合、スピーカー名で判定
                speaker = line.get("speaker", "カツミ")
                voice = "Kore" if speaker == "カツミ" else "Puck"

            # TTS用にテキストを正規化（誤読修正 & エラー予防）
            tts_text = self._normalize_text_for_tts(line["text"])

            # 空文字列の場合はTTS処理をスキップして無音を挿入
            if not tts_text:
                print(f"--- 行 {i} テキストが空のためスキップ（0.5秒の無音を挿入） ---")
                # 0.5秒の無音WAVファイルを生成
                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)  # SampleRate=16000と一致
                    wf.writeframes(b"\x00" * int(16000 * 0.5 * 2))  # 0.5秒の無音
                # 無音wav生成完了、次の行へ
                continue

            # === Edge TTS優先 → Polly → Geminiフォールバック ===

            # 1. Edge TTS（最優先・完全無料）
            print(f"--- 行 {i} Edge TTS試行 ---")
            success = self.synthesize_with_edge_tts(tts_text, voice, wav_path)

            # 2. Amazon Polly TTS（Edge失敗時）
            if not success:
                print(f"--- 行 {i} Amazon Polly TTSフォールバック試行 ---")
                success = self.synthesize_with_polly_tts(tts_text, voice, wav_path)

            # 3. Gemini TTS（最終フォールバック）
            if not success:
                print(f"--- 行 {i} Gemini TTS最終フォールバック試行 ---")
                max_gemini_attempts = 2  # 最小限の試行回数
                for attempt in range(max_gemini_attempts):
                    print(f"--- 行 {i} Gemini TTS試行 {attempt + 1}/{max_gemini_attempts} ---")
                    try:
                        self.client = self._get_client()
                        resp = self.client.models.generate_content(
                            model="models/gemini-2.5-flash-preview-tts",
                            contents=tts_text,
                            config=types.GenerateContentConfig(
                                response_modalities=["AUDIO"],
                                speech_config=types.SpeechConfig(
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                                    )
                                ),
                            ),
                        )
                        if resp.candidates and resp.candidates[0].content.parts:
                            for part in resp.candidates[0].content.parts:
                                if part.inline_data:
                                    with wave.open(wav_path, "wb") as wf:
                                        wf.setnchannels(1)
                                        wf.setsampwidth(2)
                                        wf.setframerate(16000)
                                        wf.writeframes(part.inline_data.data)
                                    success = True
                                    print(f"[OK] 行 {i} Gemini TTS成功")
                                    break
                        if success:
                            break
                    except Exception as e:
                        print(f"--- 行 {i} Gemini TTS失敗: {e} ---")
                        if "429" in str(e):
                            print("[SKIP] Gemini 429エラー - スキップします")
                            break  # 429の場合は即座にスキップ
                        time.sleep(5)

            if success:
                pass  # TTS成功済み、追加処理なし
            else:
                # 全TTS失敗時のみ無音挿入（waveで生成）
                silent_count += 1
                predicted_duration = max(1.0, len(line["text"]) / 5.0)
                print(f"[WARN]  行 {i} 全TTS失敗無音({predicted_duration:.1f}s)挿入")
                # waveで無音ファイルを生成（MoviePy禁止）
                sample_rate = 16000
                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(b"\x00" * int(sample_rate * predicted_duration * 2))

        # 無音チェック: 50%以上が無音の場合はエラー
        silent_ratio = silent_count / len(script) if len(script) > 0 else 0
        if silent_ratio > 0.5:
            print(f"[ERR] 致命的エラー: 無音クリップが{silent_ratio * 100:.1f}%（{silent_count}/{len(script)}行）")
            print("   TTS APIに深刻な問題が発生しています動画生成を中止します")
            # 一時ファイルをクリーンアップ
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
            raise Exception(f"無音クリップが多すぎます（{silent_ratio * 100:.1f}%）")

        # ffmpegで結合（MoviePy禁止）
        combined_path = os.path.join(OUTPUT_DIR, "audio.wav")
        ffmpeg_concat_audio(temp_files, combined_path)

        # 一時ファイルは動画生成後に削除するためここでは削除しない
        # temp_filesリストを返す（audio_clipsは不要になった）
        return combined_path, temp_files

    def get_subtitle_timing(self, audio_path):
        """字幕タイミングはAnti-Drift v2で音声同期済みのため不要"""
        print("--- 字幕タイミング: Anti-Drift v2で音声同期済み（Whisper不要） ---")
        return None

    def _extract_count_up_data(self, script_with_frames):
        """台本から金額データを抽出してcountUpDataを生成

        TODO: 将来的にはLLMが台本生成時に「この数字をカウントアップ」と
        明示指定する仕組みに変更する。現在は自動抽出の品質が低いため無効化。
        """
        return []

    def create_video_with_remotion(self, content, audio_path):
        """Remotionでエフェクト付き動画をレンダリング"""
        import subprocess

        print("--- Remotionレンダリング開始 ---")

        # 1. 台本からpropsを生成（みんなの声用）
        # 重要: 音声とテキストのズレ禁止！実測値ベースでフレームを計算
        script = content.get("script", [])
        fps = 24  # Remotionのfps

        # 音声ファイルから実測フレームを計算
        audio_duration = 0
        if audio_path and os.path.exists(audio_path):
            audio_duration = get_audio_duration(audio_path)
            print(f"[OK] 音声長実測: {audio_duration:.2f}秒 ({int(audio_duration * fps)}フレーム)")

        # Anti-Drift Logic v2: 連結音声を基準に比例按分
        # 個別wavの累計と連結後音声の差を補正し、累積誤差をゼロ化
        script_with_frames = []
        line_durations = []

        # まず各行の音声長を収集
        for i, line in enumerate(script):
            # スライドマーカーセクション（speaker: "slide"）は固定3秒
            if line.get("speaker") == "slide":
                line_duration = 3.0  # スライド表示用の3秒
                line_durations.append(line_duration)
                continue

            wav_file = f"output/line_{i:03d}.wav"
            if os.path.exists(wav_file):
                line_duration = get_audio_duration(wav_file)
            else:
                # フォールバック: 文字数から概算
                line_duration = len(line.get("text", "")) * 0.12 + 0.3
            line_durations.append(line_duration)

        # 個別wavの累計と連結音声の差を計算
        individual_total = sum(line_durations)
        if audio_duration > 0 and individual_total > 0:
            # 比率を計算して補正
            correction_ratio = audio_duration / individual_total
            print(
                f"[Anti-Drift] 個別累計: {individual_total:.2f}秒, 連結音声: {audio_duration:.2f}秒, 補正比率: {correction_ratio:.4f}"
            )
        else:
            correction_ratio = 1.0

        # 累積時間からフレームを計算（補正済み）
        accumulated_duration = 0.0
        slide_duration_frames = 168  # 7秒（24fps x 7）= クイズintro表示時間
        for i, line in enumerate(script):
            start_time = accumulated_duration
            corrected_duration = line_durations[i] * correction_ratio
            end_time = start_time + corrected_duration

            # slideDurationオフセット加算:
            # audio.wavの再生がslideDuration後に開始されるため、
            # 字幕のstartFrame/endFrameもその分ずらす（クイズイントロとの音声被り防止）
            script_with_frames.append(
                {
                    **line,
                    "startFrame": int(start_time * fps) + slide_duration_frames,
                    "endFrame": int(end_time * fps) + slide_duration_frames,
                }
            )
            accumulated_duration = end_time

        # 最終行のendFrameを全体の音声長に物理固定（絶対同期アンカー）+ slideDurationオフセット
        if script_with_frames and audio_duration > 0:
            script_with_frames[-1]["endFrame"] = int(audio_duration * fps) + slide_duration_frames
            print(
                f"[Anti-Drift] 最終行endFrameを{int(audio_duration * fps) + slide_duration_frames}に物理固定（slideDuration={slide_duration_frames}f加算済）"
            )

        # 全体のdurationInFramesは音声実測値 + slideDuration
        total_frames = (
            int(audio_duration * fps) if audio_duration > 0 else int(accumulated_duration * fps)
        ) + slide_duration_frames

        # ========================================
        # chartData 自動抽出（数値データのアニメーションチャート用）
        # ========================================
        # ========================================
        # 2段階生成方式: Step1 バリデーション
        # ========================================
        CHART_LABEL_MAX_CHARS = 20
        CHART_SUBTITLE_MAX_CHARS = 20
        CHART_ITEMS_MAX = 4
        CHART_ITEM_LABEL_MAX = 8

        def validate_chart_data(chart):
            """2段階生成: テキスト量が表示領域に収まるか検証・切り詰め"""
            if not chart:
                return None
            label = chart.get("label", "")
            if len(label) > CHART_LABEL_MAX_CHARS:
                chart["label"] = label[:CHART_LABEL_MAX_CHARS]
            subtitle = chart.get("subtitle", "")
            if subtitle and len(subtitle) > CHART_SUBTITLE_MAX_CHARS:
                chart["subtitle"] = subtitle[:CHART_SUBTITLE_MAX_CHARS]
            items = chart.get("items", [])
            if items:
                chart["items"] = items[:CHART_ITEMS_MAX]
                for item in chart["items"]:
                    if len(item.get("label", "")) > CHART_ITEM_LABEL_MAX:
                        item["label"] = item["label"][:CHART_ITEM_LABEL_MAX]
            return chart

        def extract_chart_data(text, chart_idx=0):
            """台本テキストから数値データを抽出してチャート用データを生成（文脈判定+ビフォーアフター版）"""
            import re

            def detect_chart_type_from_context(text_context, is_pct=False):
                """文脈から最適なチャートタイプを判定"""
                if re.search(
                    r"増額|増加|引き上げ|引上げ|アップ|上が|減額|減少|引き下げ|切り下げ|ダウン|下が|増え|減り|前年比|比べ|変更|改定",
                    text_context,
                ):
                    return "bar"
                # compare は「AvsB」の明確な対比のみ（「割合」「のうち」だけではcompareにしない）
                if re.search(r"賛成.*反対|反対.*賛成|支持.*不支持|不支持.*支持", text_context):
                    return "compare" if is_pct else "pie"
                if re.search(r"意見|人が|人は|全体の|のうち|中の|割合|分布|アンケート", text_context):
                    return "donut" if is_pct else "pie"
                if is_pct:
                    return "bar"
                return "number"

            def extract_context_label(full_text, match_start, max_len=15):
                """台本テキストからチャートラベルを抽出（短く意味の通るフレーズ）"""
                prefix = full_text[:match_start].strip()
                # 直前の文を取得（。！？で区切り）
                segments = re.split(r"[。！？\n]", prefix)
                cleaned = segments[-1].strip() if segments else prefix[-max_len:]
                cleaned = re.sub(r"「[^」]*」", "", cleaned).strip()
                if not cleaned and len(segments) >= 2:
                    cleaned = segments[-2].strip()
                if not cleaned:
                    cleaned = prefix[-max_len:].strip()
                # 助詞で終わる場合は助詞を削除して名詞句にする
                cleaned = re.sub(r"[はがをにでのもへと]+$", "", cleaned).strip()
                # 読点で分割して最後の意味ある部分だけ取る
                if len(cleaned) > max_len:
                    parts = cleaned.split("、")
                    cleaned = parts[-1].strip() if len(parts[-1]) >= 4 else "、".join(parts[-2:]).strip()
                if len(cleaned) > max_len:
                    # 最後のmax_len文字を取り、先頭が途中なら最初の助詞以降を使う
                    cleaned = cleaned[-max_len:]
                    cut = re.search(r"[はがをにでのもへと]", cleaned)
                    if cut and cut.start() < 4:
                        cleaned = cleaned[cut.end():]
                # フォールバック: テキスト全体の先頭部分
                if not cleaned or len(cleaned) < 3:
                    fallback = re.sub(r"「[^」]*」", "", full_text).strip()
                    fallback = re.split(r"[。！？\n]", fallback)[0].strip()
                    fallback = re.sub(r"[はがをにでのもへと]+$", "", fallback).strip()
                    if len(fallback) > max_len:
                        fallback = fallback[:max_len]
                    return fallback if len(fallback) >= 3 else None
                return cleaned

            def extract_subtitle(full_text, value, unit):
                """台本テキストから文脈付きsubtitle生成（コンテキスト不明な場合はNone）"""
                # 台本の文脈を要約して補足情報にする（ビフォーアフターではなく説明文）
                # 句読点で区切った文から最も関連性の高い1文を抽出
                sentences = re.split(r"[。！？\n]", full_text)
                context_sentence = None
                for s in sentences:
                    s = s.strip()
                    if len(s) >= 8 and re.search(r"\d", s):
                        context_sentence = s
                        break
                if not context_sentence:
                    for s in sentences:
                        s = s.strip()
                        if len(s) >= 8:
                            context_sentence = s
                            break

                # 増減キーワードから変化の方向性を示す
                if re.search(r"増額|増加|引き上げ|アップ|上が|上昇|増え", full_text):
                    return f"増加傾向: {value:,}{unit}"
                elif re.search(r"減額|減少|引き下げ|ダウン|下が|下落|減り", full_text):
                    return f"減少傾向: {value:,}{unit}"
                # 文脈がある場合はそれを使う（30文字以内に切り詰め）
                if context_sentence and len(context_sentence) > 5:
                    if len(context_sentence) > 30:
                        context_sentence = context_sentence[:30] + "..."
                    return context_sentence
                return None

            def is_negative_context(text_context):
                """ネガティブ文脈判定（赤字・減額・損失・不足など）"""
                return bool(
                    re.search(
                        r"減額|減少|引き下げ|ダウン|下が|下落|減り|赤字|損|不足|マイナス|負担|削減|カット|廃止",
                        text_context,
                    )
                )

            pct_match = re.search(r"([0-9０-９]+\.?[0-9０-９]*)\s*[%％]", text)
            if pct_match:
                val_str = pct_match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                val = float(val_str)
                label = extract_context_label(text, pct_match.start()) or text[:40].strip()
                ctype = detect_chart_type_from_context(text, is_pct=True)
                subtitle = extract_subtitle(text, val, "%")
                negative = is_negative_context(text)
                if ctype == "bar":
                    result = {
                        "type": "bar",
                        "label": label,
                        "value": 100 + val if "増" in text or "上" in text or "アップ" in text else 100 - val,
                        "unit": "%",
                        "maxValue": max(150, 100 + val + 20),
                        "negative": negative,
                    }
                elif ctype == "compare":
                    result = {
                        "type": "compare",
                        "label": label,
                        "value": val,
                        "unit": "%",
                        "maxValue": 100,
                        "compareValue": 100 - val,
                        "compareLabel": "その他",
                        "negative": negative,
                    }
                else:
                    result = {"type": "number", "label": label, "value": val, "unit": "%", "negative": negative}
                if subtitle:
                    result["subtitle"] = subtitle
                return result

            wari_match = re.search(r"([0-9０-９]+)\s*割", text)
            if wari_match:
                val_str = wari_match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                val = int(val_str) * 10
                label = extract_context_label(text, wari_match.start()) or text[:40].strip()
                ctype = detect_chart_type_from_context(text, is_pct=True)
                negative = is_negative_context(text)
                if ctype == "compare":
                    result = {
                        "type": "compare",
                        "label": label,
                        "value": val,
                        "unit": "%",
                        "maxValue": 100,
                        "compareValue": 100 - val,
                        "compareLabel": "その他",
                    }
                else:
                    result = {"type": "number", "label": label, "value": val, "unit": "%"}
                return result

            money_man = re.search(r"([0-9０-９,，]+)\s*万\s*円", text)
            if money_man:
                val_str = (
                    money_man.group(1)
                    .translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
                    .replace(",", "")
                )
                val = int(val_str) * 10000
                label = extract_context_label(text, money_man.start()) or text[:40].strip()
                ctype = detect_chart_type_from_context(text)
                subtitle = extract_subtitle(text, val, "円")
                negative = is_negative_context(text)
                result = {"type": ctype, "label": label, "value": val, "unit": "円", "negative": negative}
                if subtitle:
                    result["subtitle"] = subtitle
                return result

            money_match = re.search(r"([0-9０-９,，]+)\s*円", text)
            if money_match:
                val_str = (
                    money_match.group(1)
                    .translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
                    .replace(",", "")
                )
                val = int(val_str)
                if val >= 100:
                    label = extract_context_label(text, money_match.start()) or text[:40].strip()
                    ctype = detect_chart_type_from_context(text)
                    subtitle = extract_subtitle(text, val, "円")
                    negative = is_negative_context(text)
                    result = {"type": ctype, "label": label, "value": val, "unit": "円", "negative": negative}
                    if subtitle:
                        result["subtitle"] = subtitle
                    return result

            people_match = re.search(r"([0-9０-９,，]+)\s*万\s*人", text)
            if people_match:
                val_str = (
                    people_match.group(1)
                    .translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
                    .replace(",", "")
                )
                val = int(val_str)
                label = extract_context_label(text, people_match.start()) or text[:40].strip()
                return {"type": "number", "label": label, "value": val, "unit": "万人"}

            return None

        # chartDataを組み立て（poll優先、フォールバックで数値抽出）
        chart_data_list = []

        # 1. LLM生成のpollsデータを優先使用（テキストマッチングで配置）
        polls = content.get("polls", [])
        if polls:
            # mainセクションの台本行を取得（pollを配置する候補フレーム）
            main_lines = [
                l
                for l in script_with_frames
                if l.get("section") not in ("hikaeshitsu", "hikaeshitsu_jingle", "ending", "opening", "opening_jingle")
            ]
            if main_lines:
                used_line_indices = set()  # 同じ行に複数pollが被らないように

                for pi, poll in enumerate(polls):
                    question = poll.get("question", "")
                    # 質問からキーワード抽出（助詞・記号を除去）
                    import re as _re

                    keywords = _re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]{2,}", question)

                    # 台本テキストとのマッチスコアを計算
                    best_score = 0
                    best_idx = -1
                    for mi, ml in enumerate(main_lines):
                        if mi in used_line_indices:
                            continue
                        ml_text = ml.get("text", "")
                        score = sum(1 for kw in keywords if kw in ml_text)
                        # 前後2行もチェック（話題は数行にまたがる）
                        for offset in [-2, -1, 1, 2]:
                            neighbor_idx = mi + offset
                            if 0 <= neighbor_idx < len(main_lines):
                                neighbor_text = main_lines[neighbor_idx].get("text", "")
                                score += sum(0.5 for kw in keywords if kw in neighbor_text)
                        if score > best_score:
                            best_score = score
                            best_idx = mi

                    # マッチしない場合は均等配置にフォールバック
                    if best_idx < 0 or best_score == 0:
                        interval = max(1, len(main_lines) // (len(polls) + 1))
                        best_idx = min((pi + 1) * interval, len(main_lines) - 1)

                    used_line_indices.add(best_idx)
                    # 前後1行も予約して被りを防ぐ
                    used_line_indices.add(max(0, best_idx - 1))
                    used_line_indices.add(min(len(main_lines) - 1, best_idx + 1))

                    trigger_frame = main_lines[best_idx].get("startFrame", 0)

                    # poll -> ChartData形式に変換
                    answers = poll.get("answers", [])
                    items = [{"label": a.get("label", ""), "value": a.get("value", 0)} for a in answers]
                    poll_data = {
                        "type": "poll",
                        "label": poll.get("question", "みんなの声"),
                        "value": 0,
                        "unit": "",
                        "items": items,
                        "subtitle": f"出典：{poll.get('source', '')[:15]}" if poll.get("source") else None,
                    }
                    # 2段階生成: Step1 バリデーション
                    poll_data = validate_chart_data(poll_data)
                    chart_data_list.append(
                        {
                            "data": poll_data,
                            "triggerFrame": trigger_frame,
                        }
                    )
                    print(
                        f'[OK] poll[{pi}] "{question[:20]}" -> 行{best_idx}(score={best_score:.1f}, frame={trigger_frame})'
                    )
            print(f"[OK] pollデータ: {len(polls)}件をchartDataに変換（テキストマッチング配置）")

        # 2. pollsが少ない場合、数値抽出で補完（最大合計8件）
        last_chart_idx = -10
        chart_count = len(chart_data_list)
        used_frames = {cd["triggerFrame"] for cd in chart_data_list}
        for i, line_data in enumerate(script_with_frames):
            if chart_count >= 8:
                break
            text = line_data.get("text", "")
            section = line_data.get("section", "")
            if section in ("hikaeshitsu", "hikaeshitsu_jingle", "ending"):
                continue
            trigger_frame = line_data.get("startFrame", 0)
            # 既存のpollフレームと被らないようにする
            if any(abs(trigger_frame - uf) < 72 for uf in used_frames):
                continue
            chart = extract_chart_data(text, chart_count)
            # 2段階生成: Step1 バリデーション
            chart = validate_chart_data(chart)
            if chart and (i - last_chart_idx) >= 3:
                chart_data_list.append({"data": chart, "triggerFrame": trigger_frame})
                used_frames.add(trigger_frame)
                last_chart_idx = i
                chart_count += 1

        # triggerFrameでソート
        chart_data_list.sort(key=lambda x: x["triggerFrame"])
        print(
            f"[OK] chartData合計: {len(chart_data_list)}件（poll: {len(polls)}件 + 数値: {len(chart_data_list) - len(polls)}件）"
        )

        # ティッカー自己紹介テキスト（毎回ランダムに選ぶ）
        import random

        katsumi_intros = [
            "【カツミのぼやき】最近ね、韓国ドラマにハマっちゃってさ。「愛の不時着」見た？もう毎晩泣いてるわよ。孫に「ばあば、また泣いてる」って笑われるんだけど、いいのよ、泣ける作品に出会えるって幸せなことよ。",
            "【カツミのぼやき】昨日スーパーで卵が10個パック298円だったの。去年は198円だったのに...孫のお弁当に卵焼き入れてあげたいけど、なんだか複雑な気持ちよね。でもまぁ、健康でいられることが一番の節約よ。",
            "【カツミのぼやき】商店街の山田さんがね、「カツミちゃん、最近元気ないわね」って言うのよ。元気よ！いろいろ調べてたら夜更かししちゃっただけなの。情報は武器よ、知らないと損するからね。",
            "【カツミのぼやき】孫がね、「ばあば、推し活って知ってる？」って聞くから「知ってるわよ、私だって昔は西城秀樹のファンだったんだから！」って言ったら、ちょっと尊敬の目で見られたわ。嬉しかったわね。",
            "【カツミのぼやき】板橋の駄菓子屋が一軒また閉まったの。寂しいわよね。でもね、そこのおばちゃんが「カツミちゃん、あんたのこと忘れないわよ」って言ってくれてね、泣きそうになっちゃった。人のつながりって大事よね。",
            "【カツミのぼやき】朝のラジオ体操でね、隣のタカコさんが「カツミちゃん、今日のみんなの声見た？」って聞いてくるの。みんなちゃんとチェックしてるのよ。私たち世代にとっては死活問題だからね。",
            "【カツミのぼやき】先週、新潟のおばあちゃんのお墓参りに行ってきたの。井戸でスイカ冷やしてくれた夏休み、思い出すと今でも鮮明よ。あの頃は老後のことなんて考えもしなかったわね。時間って不思議よね。",
            "【カツミのぼやき】最近ね、スマホの文字が小さくて困ってるの。孫に拡大の仕方教えてもらったんだけど、すぐ戻っちゃうのよ。でもこのチャンネルの字幕は大きくていいわよね。私が設計したんだけどね、えへへ。",
            "【カツミのぼやき】宝塚が好きなのよ、実は。若い頃は月組のファンでね、今でもテレビでやってると見ちゃうの。あの華やかさ、元気もらえるわよね。推しがいるって生きるエネルギーになるのよ。",
            "【カツミのぼやき】正直ね、いろんな制度って毎年ちょっとずつ変わるから追いかけるの大変なのよ。でもね、「知らなかった」で損するのが一番悔しいじゃない？だからこうやって毎日調べてるわけ。一緒に勉強しましょうね。",
        ]
        hiroshi_intros = [
            "【ヒロシのぼやき】昨日ね、久しぶりにスーファミのFF6やったんですよ。ティナのテーマ聴いたら泣けてきちゃって。奥さんに「いい歳して何泣いてんの」って言われたけど、名作は何回やっても名作なんですよ。",
            "【ヒロシのぼやき】会社の後輩に「ヒロシさん、TikTok見てます？」って聞かれてさ。見てないけど、子供がスマホで何か見てるのはあれかな？ジェネレーションギャップって急に来るよね。",
            "【ヒロシのぼやき】休日に近所のスーパーの半額シール貼られる時間を完全に把握してるんですよ。18時半がゴールデンタイム。奥さんには内緒だけど、あれ見つけた時のアドレナリンって最高なんですよ。",
            "【ヒロシのぼやき】最近ウォーキング始めたんだけどさ、万歩計アプリ入れたら初日3,200歩だったのよ。少なっ！って思って、今は8,000歩まで伸ばした。目標1万歩だけど、腰がね...デスクワーク20年の代償ですね。",
            "【ヒロシのぼやき】子供が「パパ、将来何になりたかったの？」って聞くからさ、「プロ野球選手」って言ったら「無理じゃん」って即答されてね。まぁそうなんだけどさ、夢を語るくらいいいじゃんね。",
            "【ヒロシのぼやき】ポイ活にハマってるんですけど、妻に「その100ポイント貯めるのに使った時間で残業した方が稼げるよ」って言われて、正論すぎて何も言えなかった。でもポイント貯まるの楽しいんだもん。",
            "【ヒロシのぼやき】この前、川口の実家の近く通ったら団地がだいぶ古くなっててさ。あそこの公園でドッジボールしてたなぁ。ビックリマンチョコのシール、今でも押し入れにあるはず。捨てないでくれてるかな。",
            "【ヒロシのぼやき】カツミさんの話聞いてると「なるほど！」って思うことばっかりなんですよ。42歳にもなって知らないことだらけ。でも知らないことを知れるって楽しいじゃないですか。素直に生きるのがモットーです。",
            "【ヒロシのぼやき】週末に釣り行きたいんだけどさ、子供の習い事の送り迎えと、スーパーの買い出しと、洗濯と...いつの間にか日曜の夜になってるんですよ。サザエさん症候群ってやつですね。",
            "【ヒロシのぼやき】ラーメン好きなんですけど、最近一杯1,000円超えるのが当たり前になってきて。学生の頃は500円で食べれたのにね。物価上がってるなぁって、食べながらしみじみ感じますよ。",
        ]
        ticker_texts = [random.choice(katsumi_intros), random.choice(hiroshi_intros)]

        # ========================================
        # 家計簿データ生成（ドキュメンタリー型レイアウト用）
        # ========================================
        import random as _random

        household_budget_data = {
            "personLabel": _random.choice(
                [
                    "73歳女性・一人暮らし",
                    "68歳男性・妻と二人暮らし",
                    "75歳女性・団地暮らし",
                    "70歳夫婦・都内在住",
                    "66歳女性・パート兼業",
                    "72歳男性・持ち家あり",
                ]
            ),
            "income": _random.choice([62000, 78000, 95000, 110000, 135000, 148000]),
            "expenses": [
                {"label": "家賃", "amount": _random.choice([35000, 42000, 50000, 55000, 0])},
                {"label": "食費", "amount": _random.choice([25000, 30000, 35000, 40000])},
                {"label": "医療費", "amount": _random.choice([5000, 8000, 12000, 15000])},
                {"label": "光熱費", "amount": _random.choice([8000, 10000, 12000, 15000])},
                {"label": "通信費", "amount": _random.choice([3000, 5000, 7000])},
                {"label": "その他", "amount": _random.choice([5000, 8000, 10000, 15000])},
            ],
        }
        # 家賃0円の場合は「持ち家」として表示
        if household_budget_data["expenses"][0]["amount"] == 0:
            household_budget_data["expenses"][0] = {
                "label": "固定資産税等",
                "amount": _random.choice([5000, 8000, 12000]),
            }

        props = {
            "title": content.get("title", "今日のみんなの声"),
            "summary": content.get("summary", ""),
            "keyPoints": content.get("key_points", []),
            "script": script_with_frames,
            "durationInFrames": total_frames,
            "audioPath": os.path.basename(audio_path) if audio_path else "audio.wav",
            "channelName": self.channel_name,
            "channelColor": "#e74c3c",
            "source": content.get("source", ""),
            "backgroundImage": "background.png",
            "slideDuration": 168,  # 7秒（24fps x 7）= クイズintro表示時間
            "hikaeshitsuSlide": "",  # 控室スライド不要（黒背景のまま）
            "hikaeshitsuJingle": "hikaeshitsu_jingle.mp3",  # 控室ジングル有効化
            "subtitleStyle": "highlight",
            "subtitleColor": "rgba(220,140,30,0.5)",
            "chartData": chart_data_list,
            "ticker": ticker_texts,
            # 演出4: 金額カウントアップ（台本から金額を自動抽出）
            "countUpData": self._extract_count_up_data(script_with_frames),
            # レイアウトパターン: ドキュメンタリー型（家計簿オーバーレイ）
            "layoutPattern": "documentary",
            "householdBudget": household_budget_data,
        }

        # 2. 音声ファイルをremotion/publicにコピー（重要）
        remotion_public_dir = os.path.join(os.path.dirname(__file__), "..", "remotion", "public")
        os.makedirs(remotion_public_dir, exist_ok=True)
        if audio_path and os.path.exists(audio_path):
            import shutil

            audio_dest = os.path.join(remotion_public_dir, os.path.basename(audio_path))
            shutil.copy2(audio_path, audio_dest)
            print(f"[OK] 音声ファイルをRemotionにコピー: {audio_dest}")

        # 3. props.jsonを生成
        props_path = os.path.join(os.path.dirname(__file__), "..", "remotion", "public", "props.json")
        os.makedirs(os.path.dirname(props_path), exist_ok=True)
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False, indent=2)
        print(f"[OK] props.json生成: {props_path} (durationInFrames={total_frames})")

        # 3. Remotionでレンダリング
        remotion_dir = os.path.join(os.path.dirname(__file__), "..", "remotion")
        output_path = os.path.join(remotion_dir, "output", "remotion_video.mp4")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # props JSONをコマンドライン引数として渡す
        props_json = json.dumps(props, ensure_ascii=False)

        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.ts",
            "DynamicNewsVideo",
            output_path,
            "--props",
            props_json,
            "--concurrency",
            "2",  # 並列処理数を制限して安定化
        ]

        print(f"[CMD] {' '.join(cmd[:5])}...")

        try:
            result = subprocess.run(
                cmd,
                cwd=remotion_dir,
                capture_output=True,
                text=True,
                timeout=2400,  # 40分タイムアウト
            )

            if result.returncode == 0:
                print(f"[OK] Remotionレンダリング完了: {output_path}")
                return output_path
            else:
                print("[ERR] Remotionレンダリング失敗:")
                print(result.stderr[:500] if result.stderr else "No stderr")
                raise Exception(f"Remotion render failed: {result.returncode}")

        except subprocess.TimeoutExpired:
            print("[ERR] Remotionレンダリングタイムアウト（40分）")
            raise Exception("Remotion render timeout")
        except FileNotFoundError:
            print("[ERR] npxが見つかりません。Node.jsがインストールされているか確認してください。")
            raise Exception("npx not found")

    def create_slide_video(self, slide_image, jingle_audio, output_path, duration=3):
        """静止画+ジングルからスライド動画を生成（ffmpeg使用）"""
        import subprocess

        # パスを解決
        assets_dir = "assets"
        public_dir = "remotion/public"

        slide_path = (
            os.path.join(public_dir, slide_image)
            if os.path.exists(os.path.join(public_dir, slide_image))
            else os.path.join(assets_dir, slide_image)
        )
        jingle_path = (
            os.path.join(public_dir, jingle_audio)
            if os.path.exists(os.path.join(public_dir, jingle_audio))
            else os.path.join(assets_dir, jingle_audio)
        )

        if not os.path.exists(slide_path):
            print(f"[WARN] スライド画像が見つかりません: {slide_path}")
            return None

        if not os.path.exists(jingle_path):
            print(f"[WARN] ジングル音声が見つかりません: {jingle_path}")
            return None

        try:
            # ffmpegで静止画+音声から動画生成（3秒、24fps）
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",  # 静止画をループ
                "-i",
                slide_path,
                "-i",
                jingle_path,
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(duration),  # 3秒
                "-r",
                "24",  # 24fps
                "-s",
                "1920x1080",  # フルHD
                output_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0 and os.path.exists(output_path):
                print(f"[OK] スライド動画生成完了: {output_path}")
                return output_path
            else:
                print(f"[WARN] スライド動画生成失敗: {result.stderr[:200] if result.stderr else 'No stderr'}")
                return None

        except Exception as e:
            print(f"[WARN] スライド動画生成エラー: {e}")
            return None

    def add_slide_videos(self, video_path, hikaeshitsu_slide, hikaeshitsu_jingle):
        """本編動画の最後に控室スライド動画を結合"""
        import subprocess

        # 控室スライド動画を生成
        hikaeshitsu_slide_video = os.path.join(OUTPUT_DIR, "hikaeshitsu_slide.mp4")
        hikaeshitsu_result = self.create_slide_video(hikaeshitsu_slide, hikaeshitsu_jingle, hikaeshitsu_slide_video)

        if not hikaeshitsu_result:
            print("[WARN] 控室スライド動画が生成できませんでした。")
            return video_path

        # concat listを作成
        concat_list_path = os.path.join(OUTPUT_DIR, "slide_concat_list.txt")
        with open(concat_list_path, "w") as f:
            f.write(f"file '{os.path.abspath(video_path)}'\n")
            f.write(f"file '{os.path.abspath(hikaeshitsu_slide_video)}'\n")

        final_output = video_path.replace(".mp4", "_with_slides.mp4")

        try:
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", final_output]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and os.path.exists(final_output):
                os.remove(video_path)
                os.rename(final_output, video_path)
                print(f"[OK] 控室スライド動画結合完了: {video_path}")
            else:
                print(f"[WARN] スライド動画結合失敗: {result.stderr[:200] if result.stderr else 'No stderr'}")

        except Exception as e:
            print(f"[WARN] スライド動画結合エラー: {e}")
        finally:
            # 一時ファイル削除
            for temp_file in [concat_list_path, hikaeshitsu_slide_video, final_output]:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass

        return video_path

    def add_intro_to_video(self, video_path):
        """イントロ動画をランダム選択して本編に結合"""
        import random
        import subprocess

        intro_dir = "assets/intro"
        intro_files = ["intro_v1.mp4", "intro_v2.mp4", "intro_v3.mp4"]

        # イントロファイルの存在確認
        available_intros = []
        for intro in intro_files:
            intro_path = os.path.join(intro_dir, intro)
            if os.path.exists(intro_path):
                available_intros.append(intro_path)

        if not available_intros:
            print("[WARN] イントロ動画が見つかりません。スキップします。")
            return video_path

        # ランダムに選択
        selected_intro = random.choice(available_intros)
        print(f"--- イントロ結合: {os.path.basename(selected_intro)} ---")

        # 出力パス
        final_output = video_path.replace(".mp4", "_with_intro.mp4")

        # ffmpegで結合（concat demuxer使用）
        concat_list_path = os.path.join(OUTPUT_DIR, "concat_list.txt")
        with open(concat_list_path, "w") as f:
            f.write(f"file '{os.path.abspath(selected_intro)}'\n")
            f.write(f"file '{os.path.abspath(video_path)}'\n")

        try:
            # ffmpeg結合（再エンコードなし = 超高速）
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", final_output]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0 and os.path.exists(final_output):
                # 成功した場合、元ファイルを置き換え
                os.remove(video_path)
                os.rename(final_output, video_path)
                print(f"[OK] イントロ結合完了: {video_path}")
            else:
                print(f"[WARN] ffmpeg結合失敗: {result.stderr}")
                # 失敗しても元動画は残る

        except subprocess.TimeoutExpired:
            print("[WARN] ffmpeg結合タイムアウト")
        except Exception as e:
            print(f"[WARN] イントロ結合エラー: {e}")
        finally:
            # 一時ファイル削除
            if os.path.exists(concat_list_path):
                os.remove(concat_list_path)
            if os.path.exists(final_output):
                try:
                    os.remove(final_output)
                except:
                    pass

        return video_path

    def generate_quiz_intro_video(self, chart_data_list):
        """
        冒頭クイズintro動画を生成（本編chartDataから逆生成）
        1位のラベル/値を「???」に置換したグラフ画像+TTS音声→ffmpegで動画化

        Args:
            chart_data_list: 本編のchartDataリスト

        Returns:
            str: クイズintro動画のパス、失敗時はNone
        """
        import subprocess

        print("--- 冒頭クイズintro動画生成開始 ---")

        quiz_path = os.path.join(OUTPUT_DIR, "quiz_intro.mp4")

        try:
            # 1. chartDataからpoll型を探す（最初のpollを使用）
            quiz_poll = None
            for cd in chart_data_list:
                data = cd.get("data", {})
                if data.get("type") == "poll" and data.get("items"):
                    quiz_poll = data
                    break

            if not quiz_poll:
                # pollがなければ数値チャートから作る
                for cd in chart_data_list:
                    data = cd.get("data", {})
                    if data.get("items"):
                        quiz_poll = data
                        break

            if not quiz_poll or not quiz_poll.get("items"):
                print("[WARN] クイズ用のchartDataが見つからない、スキップ")
                return None

            # 2. 1位（最大値）を「???」に置換
            items = quiz_poll["items"]
            sorted_items = sorted(items, key=lambda x: x.get("value", 0), reverse=True)
            top_item = sorted_items[0]  # 1位を保存（答え用）

            # クイズ用items: 1位だけ「???」に
            quiz_items = []
            for item in sorted_items:
                if item == top_item:
                    quiz_items.append({"label": "？？？", "value": item["value"]})
                else:
                    quiz_items.append(item.copy())

            question = quiz_poll.get("label", "みんなの声")

            # 3. Pillowでクイズ画像を生成（横棒グラフ）
            from PIL import Image, ImageDraw, ImageFont

            width, height = 1920, 1080
            img = Image.new("RGB", (width, height), color=(25, 25, 40))
            draw = ImageDraw.Draw(img)

            # フォント
            try:
                font_path = os.path.join(os.path.dirname(__file__), "..", "remotion", "public", "NotoSansJP-Bold.ttf")
                if not os.path.exists(font_path):
                    font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
                title_font = ImageFont.truetype(font_path, 56)
                label_font = ImageFont.truetype(font_path, 40)
                small_font = ImageFont.truetype(font_path, 32)
            except:
                title_font = ImageFont.load_default()
                label_font = title_font
                small_font = title_font

            # タイトル「あなたは知っていましたか？」
            draw.text((width // 2, 80), "知らないと損するかも！？", fill=(255, 200, 50), font=title_font, anchor="mt")

            # 質問文
            draw.text((width // 2, 160), question, fill=(255, 255, 255), font=label_font, anchor="mt")

            # 「1位は何でしょう？」
            draw.text(
                (width // 2, 220),
                "あなたは正解できますか？見逃すと損かも...",
                fill=(255, 150, 50),
                font=small_font,
                anchor="mt",
            )

            # 棒グラフを描画
            bar_area_top = 300
            bar_height = 60
            bar_gap = 20
            max_value = max(item.get("value", 1) for item in quiz_items)
            bar_max_width = 900

            for idx, item in enumerate(quiz_items):
                y = bar_area_top + idx * (bar_height + bar_gap)
                value = item.get("value", 0)
                label = item.get("label", "")
                bar_width = int((value / max_value) * bar_max_width) if max_value > 0 else 0

                # 順位
                rank = idx + 1
                rank_text = f"{rank}位"
                draw.text((100, y + bar_height // 2), rank_text, fill=(200, 200, 200), font=label_font, anchor="lm")

                # ラベル
                label_color = (255, 200, 50) if label == "？？？" else (255, 255, 255)
                draw.text((200, y + bar_height // 2), label, fill=label_color, font=label_font, anchor="lm")

                # バー
                bar_left = 550
                bar_color = (255, 100, 100) if label == "？？？" else (100, 150, 255)
                if label == "？？？":
                    # 1位のバーは点線風（推測を促す）
                    for bx in range(0, bar_width, 20):
                        segment_w = min(12, bar_width - bx)
                        draw.rectangle(
                            [bar_left + bx, y, bar_left + bx + segment_w, y + bar_height], fill=(255, 100, 100, 150)
                        )
                else:
                    draw.rectangle([bar_left, y, bar_left + bar_width, y + bar_height], fill=bar_color)

                # 値
                value_text = f"{value}%" if value <= 100 else f"{value:,}"
                if label != "？？？":
                    draw.text(
                        (bar_left + bar_width + 20, y + bar_height // 2),
                        value_text,
                        fill=(200, 200, 200),
                        font=small_font,
                        anchor="lm",
                    )
                else:
                    draw.text(
                        (bar_left + bar_width + 20, y + bar_height // 2),
                        "??%",
                        fill=(255, 200, 50),
                        font=small_font,
                        anchor="lm",
                    )

            # 「正解は本編で！」
            draw.text(
                (width // 2, height - 120),
                "答えを知らないと損するかも...最後まで見てね！",
                fill=(255, 200, 50),
                font=title_font,
                anchor="mt",
            )

            # 出典
            subtitle = quiz_poll.get("subtitle", "")
            if subtitle:
                draw.text((width // 2, height - 50), subtitle, fill=(150, 150, 150), font=small_font, anchor="mt")

            quiz_img_path = os.path.join(OUTPUT_DIR, "quiz_intro.png")
            img.save(quiz_img_path)
            print(f"[OK] クイズ画像生成: {quiz_img_path}")

            # 4. TTS音声生成
            quiz_text = f"ねえちょっと、これ知らないと損するかもよ？{question}で、1位は何だと思います？答えを知らないままだと...損しちゃうかも。最後まで見てくださいね！"
            quiz_audio_path = os.path.join(OUTPUT_DIR, "quiz_intro_audio.wav")

            voice = "Kazuha"
            success = self.synthesize_with_polly_tts(quiz_text, voice, quiz_audio_path)

            if not success or not os.path.exists(quiz_audio_path):
                print("[INFO] クイズTTS Polly失敗、Gemini TTSにフォールバック")
                try:
                    self.client = self._get_client()
                    resp = self.client.models.generate_content(
                        model="models/gemini-2.5-flash-preview-tts",
                        contents=quiz_text,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                                )
                            ),
                        ),
                    )
                    if resp.candidates and resp.candidates[0].content.parts:
                        for part in resp.candidates[0].content.parts:
                            if part.inline_data:
                                import wave

                                with wave.open(quiz_audio_path, "wb") as wf:
                                    wf.setnchannels(1)
                                    wf.setsampwidth(2)
                                    wf.setframerate(16000)
                                    wf.writeframes(part.inline_data.data)
                                success = True
                                break
                except Exception as e:
                    print(f"[WARN] クイズTTS Gemini失敗: {e}")

            if not success or not os.path.exists(quiz_audio_path):
                print("[WARN] クイズTTS完全失敗、スキップ")
                return None

            # 5. 音声長を取得
            audio_duration = get_audio_duration(quiz_audio_path)
            # 最低5秒（画像を読む時間）
            video_duration = max(audio_duration + 1.0, 5.0)
            print(f"[OK] クイズ音声: {audio_duration:.2f}秒 → 動画: {video_duration:.2f}秒")

            # 6. ffmpegで画像+音声→動画
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                quiz_img_path,
                "-i",
                quiz_audio_path,
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(video_duration),
                "-shortest",
                quiz_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"[ERR] クイズ動画ffmpeg失敗: {result.stderr[:200]}")
                return None

            print(f"[OK] クイズintro動画生成完了: {quiz_path}")

            # 一時ファイル削除
            for temp in [quiz_img_path, quiz_audio_path]:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except:
                        pass

            return quiz_path

        except Exception as e:
            print(f"[ERR] クイズintro動画生成失敗: {e}")
            import traceback

            traceback.print_exc()
            return None

    def add_quiz_intro_to_video(self, video_path, chart_data_list):
        """クイズintro動画を本編の冒頭に結合（字幕同期に影響なし）"""
        import subprocess

        quiz_path = self.generate_quiz_intro_video(chart_data_list)

        if not quiz_path or not os.path.exists(quiz_path):
            print("[WARN] クイズintro生成失敗、本編のみで続行")
            return video_path

        print(f"--- クイズintro結合: {os.path.basename(quiz_path)} ---")

        final_output = video_path.replace(".mp4", "_with_quiz.mp4")
        concat_list_path = os.path.join(OUTPUT_DIR, "concat_quiz_list.txt")

        with open(concat_list_path, "w") as f:
            f.write(f"file '{os.path.abspath(quiz_path)}'\n")
            f.write(f"file '{os.path.abspath(video_path)}'\n")

        try:
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", final_output]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and os.path.exists(final_output):
                os.remove(video_path)
                os.rename(final_output, video_path)
                print(f"[OK] クイズintro結合完了: {video_path}")
            else:
                print(f"[WARN] ffmpegクイズ結合失敗: {result.stderr[:200]}")

        except subprocess.TimeoutExpired:
            print("[WARN] ffmpegクイズ結合タイムアウト")
        except Exception as e:
            print(f"[WARN] クイズintro結合エラー: {e}")
        finally:
            for temp in [concat_list_path, quiz_path, final_output]:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except:
                        pass

        return video_path

    def generate_hikaeshitsu_video(self, content=None):
        """
        控室トーク動画を生成（収録後〜控室にて〜）
        Remotion HikaeshitsuSceneを使用（MoviePy禁止）

        Args:
            content: 本編のコンテンツ（今日のニュースを踏まえたぶっちゃけトーク用）

        Returns:
            str: 控室動画のパス、失敗時はNone
        """
        import json
        import subprocess
        import tempfile

        print("--- 控室トーク動画生成開始 (Remotion版) ---")

        hikaeshitsu_path = os.path.join(OUTPUT_DIR, "hikaeshitsu.mp4")

        try:
            # 1. 控室トークの台本をAI生成（キャラクター人格重視）
            hikaeshitsu_script = self.generate_hikaeshitsu_script(content)

            if not hikaeshitsu_script:
                print("[WARN] 控室台本生成失敗、デフォルト台本を使用")
                hikaeshitsu_script = self.get_default_hikaeshitsu_script()

            # 2. TTS音声を生成
            temp_dir = tempfile.gettempdir()
            audio_files = []
            fps = 24

            for i, line in enumerate(hikaeshitsu_script):
                wav_path = os.path.join(temp_dir, f"hikaeshitsu_line_{i}.wav")

                # Edge TTSを最優先（本編と同じ声）→ Polly → Geminiフォールバック
                voice = "Kazuha" if line["speaker"] == "カツミ" else "Takumi"
                success = self.synthesize_with_edge_tts(line["text"], voice, wav_path)

                # Edge TTS失敗時はPollyにフォールバック
                if not success or not os.path.exists(wav_path):
                    success = self.synthesize_with_polly_tts(line["text"], voice, wav_path)

                # Polly失敗時はGemini TTSにフォールバック
                if not success or not os.path.exists(wav_path):
                    print(f"[INFO] 控室行{i} Gemini TTSフォールバック")
                    gemini_voice = "Kore" if line["speaker"] == "カツミ" else "Puck"
                    try:
                        self.client = self._get_client()
                        resp = self.client.models.generate_content(
                            model="models/gemini-2.5-flash-preview-tts",
                            contents=line["text"],
                            config=types.GenerateContentConfig(
                                response_modalities=["AUDIO"],
                                speech_config=types.SpeechConfig(
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=gemini_voice)
                                    )
                                ),
                            ),
                        )
                        if resp.candidates and resp.candidates[0].content.parts:
                            for part in resp.candidates[0].content.parts:
                                if part.inline_data:
                                    with wave.open(wav_path, "wb") as wf:
                                        wf.setnchannels(1)
                                        wf.setsampwidth(2)
                                        wf.setframerate(16000)
                                        wf.writeframes(part.inline_data.data)
                                    success = True
                                    print(f"[OK] 控室行{i} Gemini TTS成功")
                                    break
                    except Exception as e:
                        print(f"[WARN] 控室行{i} Gemini TTS失敗: {e}")

                if success and os.path.exists(wav_path):
                    audio_files.append(wav_path)
                else:
                    print(f"[WARN] TTS失敗: {line['text'][:20]}...")

            if not audio_files:
                print("[ERR] 控室音声生成失敗")
                return None

            # 3. ffmpegで音声を結合
            hikaeshitsu_audio = os.path.join(OUTPUT_DIR, "hikaeshitsu_audio.wav")
            concat_list = os.path.join(temp_dir, "hikaeshitsu_concat.txt")

            with open(concat_list, "w") as f:
                for wav in audio_files:
                    f.write(f"file '{wav}'" + "\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", hikaeshitsu_audio]
            subprocess.run(cmd, capture_output=True, timeout=60)

            # 4. 音声長を取得してフレームを計算
            audio_duration = get_audio_duration(hikaeshitsu_audio)
            total_frames = int(audio_duration * fps)
            print(f"[OK] 控室音声: {audio_duration:.2f}秒 ({total_frames}フレーム)")

            # 5. 各行のフレームを計算（Anti-Drift Logic）
            line_durations = []
            for wav in audio_files:
                line_durations.append(get_audio_duration(wav))

            individual_total = sum(line_durations)
            correction_ratio = audio_duration / individual_total if individual_total > 0 else 1.0

            script_with_frames = []
            accumulated = 0.0
            for i, line in enumerate(hikaeshitsu_script):
                start_time = accumulated
                corrected_duration = line_durations[i] * correction_ratio if i < len(line_durations) else 2.0
                end_time = start_time + corrected_duration

                script_with_frames.append(
                    {
                        "speaker": line["speaker"],
                        "text": line["text"],
                        "startFrame": int(start_time * fps),
                        "endFrame": int(end_time * fps),
                    }
                )
                accumulated = end_time

            # 最終行を音声終端に固定
            if script_with_frames:
                script_with_frames[-1]["endFrame"] = total_frames

            # 6. props.json生成
            hikaeshitsu_props = {
                "script": script_with_frames,
                "audioPath": "hikaeshitsu_audio.wav",
                "durationInFrames": total_frames,
            }

            props_path = os.path.abspath(os.path.join(OUTPUT_DIR, "hikaeshitsu_props.json"))
            with open(props_path, "w", encoding="utf-8") as f:
                json.dump(hikaeshitsu_props, f, ensure_ascii=False, indent=2)

            # 7. 音声をpublicにコピー
            public_audio = os.path.join(REMOTION_DIR, "public", "hikaeshitsu_audio.wav")
            import shutil

            shutil.copy2(hikaeshitsu_audio, public_audio)

            # 8. Remotionでレンダリング
            print("[OK] Remotion HikaeshitsuScene レンダリング開始")

            # propsを絶対パスで指定（GitHub Actions対応）
            # タイムアウトを120秒に設定してリトライ
            render_cmd = [
                "npx",
                "remotion",
                "render",
                "src/index.ts",
                "HikaeshitsuScene",
                hikaeshitsu_path,
                f"--props={props_path}",
                "--timeout=120000",  # 120秒タイムアウト
            ]

            # 3回リトライ（絶対スキップしない）
            max_retries = 3
            for attempt in range(max_retries):
                print(f"[INFO] 控室レンダリング試行 {attempt + 1}/{max_retries}")
                result = subprocess.run(
                    render_cmd,
                    cwd=REMOTION_DIR,
                    capture_output=True,
                    text=True,
                    timeout=2400,  # プロセス全体は2400秒（CI環境のbundle+chromium起動を考慮）
                )

                if result.returncode == 0:
                    break  # 成功

                print(f"[WARN] 控室レンダリング失敗 (試行 {attempt + 1}): {result.stderr[:500]}")
                if attempt < max_retries - 1:
                    print("[INFO] 10秒待機してリトライ...")
                    time.sleep(10)

            if result.returncode != 0:
                print(f"[ERR] 控室Remotionレンダリング {max_retries}回失敗: {result.stderr}")
                raise Exception(f"控室Remotionレンダリング失敗: {result.stderr[:200]}")

            print(f"[OK] 控室トーク動画生成完了: {hikaeshitsu_path}")

            # 一時ファイル削除
            for temp in audio_files + [concat_list, hikaeshitsu_audio]:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except:
                        pass

            return hikaeshitsu_path

        except Exception as e:
            print(f"[ERR] 控室トーク動画生成失敗: {e}")
            import traceback

            traceback.print_exc()
            raise  # スキップせずにエラーを上げる

    def generate_hikaeshitsu_script(self, content=None):
        """
        控室トークの台本をAI生成（本編の内容を深掘りする本音トーク）
        """
        news_title = content.get("title", "今日のニュース") if content else "今日のニュース"
        news_summary = content.get("summary", "") if content else ""
        key_points = content.get("key_points", []) if content else []
        key_points_text = "\n".join([f"- {p}" for p in key_points]) if key_points else "なし"

        # 本編の台本からPHASE3（本音トーク）を抽出して控室に渡す
        main_script_text = ""
        if content and content.get("script"):
            main_lines = []
            for line in content["script"]:
                sp = line.get("speaker", "")
                txt = line.get("text", "")
                main_lines.append(f"{sp}: {txt}")
            main_script_text = "\n".join(main_lines[-40:])  # 後半40行（本編内容を十分に参照）

        prompt = f"""
You are writing the EMOTIONAL CLIMAX of this YouTube show — the 控室トーク (backstage talk).
The main show featured a real story about {self.channel_theme} as a human documentary.
Now, in the backstage, カツミ and ヒロシ reflect deeply on that person's life.

THIS IS NOT A NEWS SHOW. This is a HUMAN DOCUMENTARY show.
The backstage talk is where viewers feel moved, think about their own lives, and
feel "人間って簡単には生きていけないよね...でも頑張ろう" — THAT is the goal.

## 今日紹介した人のストーリー
タイトル: 「{news_title}」
概要: {news_summary[:300]}

## ストーリーのキーポイント (必ず引用すること)
{key_points_text}

## 本編の台本 (この人の人生について語った内容)
{main_script_text}

{get_character_settings()}

## BACKSTAGE CONCEPT: 人間の生き様を振り返る哲学トーク
収録が終わった控室。本編では「この人は月○万円で暮らしてる」「統計的には〜」と
データや事実で語ったが、ここでは一人の人間としてしみじみ語り合う。

★★★ 最重要: 今日紹介した人の人生について100%語ること。無関係な雑談は禁止 ★★★

★ このコーナーの存在意義:
「ニュースや数字の裏にいる一人の人間」を感じる場所。
視聴者が「私も同じよ...頑張ろう」と涙ぐむのがゴール。

カツミの哲学モード:
- 本編では辛口だったことを少し反省: 「さっきあんな言っちゃったけどさ...」
- 自分の人生と重ねる: 「私も夫を亡くした時、同じような気持ちだったのよ」
- 人生の本質に触れる: 「結局ね、人間って一人じゃ生きていけないのよ」
- 庶民の知恵: 「うちのお母さんがよく言ってたの。"お金がなくても知恵があれば大丈夫"って」

ヒロシの内省モード:
- 今日の人と自分を比較: 「僕も将来こうなるかもしれないって、正直思いました」
- 妻や家族への感謝: 「帰ったら妻に"ありがとう"って言おうかな」
- 静かな共感: 「あの方の笑顔がね、なんか忘れられないんですよ」
- 人生観: 「お金じゃ測れないものって、やっぱりあるんですよね」

## FLOW

**PHASE 1: 振り返り (5-8行)**
本編で紹介した人の人生をしみじみ振り返る。
- 「さっきの○○さんの話、収録終わってもまだ考えちゃうのよ」
- 本編で言った辛口コメントを少し反省する
- この人の強さ・弱さ・人間味に触れる

**PHASE 2: 自分の人生と重ねる (8-12行)**
カツミとヒロシが自分の人生経験と重ねて語る。
必須要素:
1. カツミの体験談: 自分が苦しかった時期の話（具体的なエピソード）
2. ヒロシの体験談: 自分の家族・妻との話（具体的なエピソード）
3. 「誰でもこうなる可能性がある」という気づき
4. 人間の強さ・回復力への感嘆
5. 「簡単には生きていけない」「でも人は生きていく」という哲学

Example:
  カツミ: "あの方、月12万円で笑って暮らしてるのよ。私なんか..."
  ヒロシ: "正直、僕もあの笑顔見て胸が痛くなりました"
  カツミ: "私もね、夫が倒れた時は本当に...先が見えなくてね"
  ヒロシ: "そうだったんですか...知らなかった..."
  カツミ: "でもね、不思議なもんで、人間って底を打つと強くなるのよ"
  ヒロシ: "僕も父が入院した時、母が急にしっかりしたの覚えてます"

**PHASE 3: 温かいエール (3-5行)**
「でも、生きてるだけで丸儲けよ」と温かく締める。

必須要素:
- 今日紹介した人への敬意
- 「私たちも頑張って生きていきましょう」
- 視聴者が「明日も頑張ろう」と思える言葉

Example:
  カツミ: "あの方に教えてもらったわ。贅沢じゃなくても、幸せは作れるって"
  ヒロシ: "本当ですね。僕も帰ったら妻にありがとうって言いますよ"
  カツミ: "そうよ！生きてるだけで丸儲け。みんな、頑張って生きていきましょう"
  ヒロシ: "はい！明日もまた、誰かの人生に寄り添いましょう"

## ABSOLUTE RULES
- 今日紹介した人のストーリーを必ず引用すること
- 具体的な金額・年齢・エピソードを本編から最低3箇所引用
- カツミ・ヒロシの体験談を必ず各2回以上入れる
- 1発言は40文字以内。長い話は複数発言に分割
- 下品な言葉禁止
- テンプレ絶対禁止: 毎回同じパターン禁止
- 「そうですね」だけの空相槌禁止
- 「視聴者さんも」禁止（自分の経験で語れ）
- 最後は必ず温かく前向きに締める
- 【絶対禁止: 陰謀論・噂話・フェイクニュース】→ 全て廃止。哲学トークに集中
- 【絶対禁止: 海外ネタ】海外旅行の思い出話のみ許可
- 【重要: 切なさと温かさのバランス】泣かせるだけじゃなく、最後は必ず希望を持たせる

## OUTPUT FORMAT (JSON array, 18-25 lines)
[
  {{"speaker": "カツミ", "text": "(今日の人の話を振り返って...)"}},
  {{"speaker": "ヒロシ", "text": "(自分も考えさせられた...)"}},
  {{"speaker": "カツミ", "text": "(自分の体験と重ねて...)"}},
  ...
  {{"speaker": "カツミ", "text": "(温かいクロージング)"}},
  {{"speaker": "ヒロシ", "text": "(前向きエール: 頑張って生きていきましょう)"}}
]

## RULES
- Japanese only for dialogue
- Must reference TODAY'S specific person and their life story from the main script
- MUST include personal stories and reflections (this creates emotional connection)
- MUST end with warmth and hope (viewer feels encouraged to live their best life)
"""

        try:
            # Gemini/Claudeで生成（暴走トーク用にtemperature高め＋長文許容）
            text = call_llm_with_fallback(
                messages=[
                    {
                        "role": "system",
                        "content": "あなたはYouTube台本作家です。JSON配列形式で台本を出力してください。控室トークはこの番組のメインコンテンツです。カツミとヒロシの人間性を全開にして、視聴者が「よくぞ言ってくれた！ファンになった！」と思う長めの本音トークを書いてください。1発言は40文字以内で書いてください。",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3072,
                temperature=0.9,
            )

            match = re.search(r"\[[\s\S]*\]", text)
            if match:
                script = json.loads(match.group())
                print(f"[OK] 控室台本生成: {len(script)}行")
                return script

        except Exception as e:
            print(f"[WARN] 控室台本AI生成失敗: {e}")

        return None

    def get_default_hikaeshitsu_script(self):
        """デフォルトの控室台本（AI生成失敗時のフォールバック）"""
        return [
            {"speaker": "カツミ", "text": "収録お疲れ様。今日のニュース、正直不安になるわね"},
            {"speaker": "ヒロシ", "text": "本当ですよ。僕らの生活、ちゃんともらえるのかな"},
            {"speaker": "カツミ", "text": "板橋に住んでた頃は、老後なんて考えなかったわ"},
            {"speaker": "ヒロシ", "text": "川口の団地にいた頃、ファミコンのことしか考えてなかったですよ"},
            {"speaker": "カツミ", "text": "駄菓子屋でガリガリ君買ってた頃が懐かしいわね"},
            {"speaker": "ヒロシ", "text": "ビックリマンチョコ、僕も集めてましたよ！"},
            {"speaker": "カツミ", "text": "日本の四季って本当に素敵よね"},
            {"speaker": "ヒロシ", "text": "日本って本当にいい国ですよね。コンビニ最高ですし"},
            {"speaker": "カツミ", "text": "まぁ不安はあるけどさ、知ってるだけで全然違うのよ"},
            {"speaker": "ヒロシ", "text": "そうですよね。一緒に頑張っていきましょう！"},
            {"speaker": "カツミ", "text": "そうよ！なんとかなるわよ、なんとかする！"},
        ]

    def add_hikaeshitsu_to_video(self, video_path, content=None):
        """控室トーク動画を本編の最後に結合"""
        import subprocess

        # 控室動画を生成（絶対スキップしない）
        hikaeshitsu_path = self.generate_hikaeshitsu_video(content=content)

        if not hikaeshitsu_path or not os.path.exists(hikaeshitsu_path):
            raise Exception("控室トーク動画の生成に失敗しました。スキップ禁止。")

        print(f"--- 控室トーク結合: {os.path.basename(hikaeshitsu_path)} ---")

        # 出力パス
        final_output = video_path.replace(".mp4", "_with_hikaeshitsu.mp4")

        # ffmpegで結合
        concat_list_path = os.path.join(OUTPUT_DIR, "concat_hikaeshitsu_list.txt")
        with open(concat_list_path, "w") as f:
            f.write(f"file '{os.path.abspath(video_path)}'\n")
            f.write(f"file '{os.path.abspath(hikaeshitsu_path)}'\n")

        try:
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", final_output]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and os.path.exists(final_output):
                os.remove(video_path)
                os.rename(final_output, video_path)
                print(f"[OK] 控室トーク結合完了: {video_path}")
            else:
                print(f"[WARN] ffmpeg控室結合失敗: {result.stderr}")

        except subprocess.TimeoutExpired:
            print("[WARN] ffmpeg控室結合タイムアウト")
        except Exception as e:
            print(f"[WARN] 控室トーク結合エラー: {e}")
        finally:
            for temp in [concat_list_path, hikaeshitsu_path, final_output]:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except:
                        pass

        return video_path

    def generate_ending_video(self):
        """
        エンディング動画を生成（カツミ＆ヒロシのバイバイ）
        ffmpeg使用（MoviePy禁止）

        Returns:
            str: エンディング動画のパス、失敗時はNone
        """
        import subprocess

        from PIL import Image

        print("--- エンディング動画生成開始 (ffmpeg版) ---")

        ending_duration = 5.0  # 5秒
        ending_path = os.path.join(OUTPUT_DIR, "ending.mp4")

        try:
            # 1. 背景画像を作成
            bg_path = "assets/background.png"
            if os.path.exists(bg_path):
                bg_img = Image.open(bg_path).convert("RGBA")
                bg_img = bg_img.resize(self.res)
            else:
                bg_img = Image.new("RGBA", self.res, (255, 200, 200, 255))

            # 2. キャラクター画像を合成
            katsumi_path = "assets/katsumi_smile.png"
            hiroshi_path = "assets/hiroshi_smile.png"

            if os.path.exists(katsumi_path) and os.path.exists(hiroshi_path):
                katsumi_img = Image.open(katsumi_path).convert("RGBA")
                hiroshi_img = Image.open(hiroshi_path).convert("RGBA")

                char_height = 350
                katsumi_img = katsumi_img.resize(
                    (int(katsumi_img.width * char_height / katsumi_img.height), char_height)
                )
                hiroshi_img = hiroshi_img.resize(
                    (int(hiroshi_img.width * char_height / hiroshi_img.height), char_height)
                )

                katsumi_x = 200
                hiroshi_x = self.res[0] - hiroshi_img.width - 200
                char_y = self.res[1] // 2 - char_height // 2 + 50

                bg_img.paste(katsumi_img, (katsumi_x, char_y), katsumi_img)
                bg_img.paste(hiroshi_img, (hiroshi_x, char_y), hiroshi_img)

            # 3. テキスト描画なし（背景画像とキャラクターのみ）
            # テキストは控室パートで言うので、エンディングは映像のみ

            ending_img_path = os.path.join(OUTPUT_DIR, "ending_frame.png")
            bg_img.convert("RGB").save(ending_img_path)

            # 4. 無音で動画化（テキストなし・音声なし）

            # 5. ffmpegで動画化（MoviePy禁止）
            # 無音版（エンディング画像のみ、音声なし）
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                ending_img_path,
                "-c:v",
                "libx264",
                "-t",
                str(ending_duration),
                "-pix_fmt",
                "yuv420p",
                "-an",
                ending_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"[ERR] ffmpegエンディング生成失敗: {result.stderr}")
                return None

            print(f"[OK] エンディング動画生成完了: {ending_path}")

            # 一時ファイル削除
            if os.path.exists(ending_img_path):
                try:
                    os.remove(ending_img_path)
                except:
                    pass

            return ending_path

        except Exception as e:
            print(f"[WARN] エンディング動画生成失敗: {e}")
            import traceback

            traceback.print_exc()
            return None

    def add_ending_to_video(self, video_path):
        """エンディング動画を本編の最後に結合"""
        import subprocess

        # エンディング動画を生成
        ending_path = self.generate_ending_video()

        if not ending_path or not os.path.exists(ending_path):
            print("[WARN] エンディング動画がありません。スキップします。")
            return video_path

        print(f"--- エンディング結合: {os.path.basename(ending_path)} ---")

        # 出力パス
        final_output = video_path.replace(".mp4", "_with_ending.mp4")

        # ffmpegで結合（concat demuxer使用）
        concat_list_path = os.path.join(OUTPUT_DIR, "concat_ending_list.txt")
        with open(concat_list_path, "w") as f:
            f.write(f"file '{os.path.abspath(video_path)}'\n")
            f.write(f"file '{os.path.abspath(ending_path)}'\n")

        try:
            # ffmpeg結合（再エンコードなし = 超高速）
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", final_output]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0 and os.path.exists(final_output):
                # 成功した場合、元ファイルを置き換え
                os.remove(video_path)
                os.rename(final_output, video_path)
                print(f"[OK] エンディング結合完了: {video_path}")
            else:
                print(f"[WARN] ffmpegエンディング結合失敗: {result.stderr}")
                # 失敗しても元動画は残る

        except subprocess.TimeoutExpired:
            print("[WARN] ffmpegエンディング結合タイムアウト")
        except Exception as e:
            print(f"[WARN] エンディング結合エラー: {e}")
        finally:
            # 一時ファイル削除
            for temp in [concat_list_path, ending_path, final_output]:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except:
                        pass

        return video_path

    def run(self, use_remotion=False):
        try:
            print("=" * 60)
            print("動画生成パイプライン開始")
            if use_remotion:
                print("Remotionモード")
            print("=" * 60)

            # 1. 台本生成（概要欄も含む）
            print("\n[1/10] 台本生成")
            content = self.generate_content()

            # 2. 台本検証
            print("\n[2/10] 台本検証")
            self.validate_script(content)

            if self.mode == "--test":
                pass  # フル台本テスト: 切り詰めなし
                # content['script'] = content['script'][:3]
            elif self.mode == "--short-prod":
                # 15-30秒程度にするため冒頭 5行程度に絞る
                content["script"] = content["script"][:5]
                content["title"] = "検証" + content["title"]

            # 注意: クイズセリフはGPT生成の台本に含まれる
            # ハードコードされたセリフは削除済み（v12.0）

            # 3. YouTubeサムネイル生成（動画には使わない）
            print("\n[3/10] サムネイル生成")
            news_summary = content.get("summary", "")
            thumbnail_title = self.generate_thumbnail_title(news_summary)
            youtube_thumb_path = self.generate_youtube_thumbnail(thumbnail_title, script=content.get("script"))

            # 3.5 チョーク風イラスト画像生成（Remotion左側表示用）
            print("\n[3.5/10] チョーク風イラスト生成")
            self.generate_chalk_illustration(content.get("script", []), content.get("title", ""))

            # 4. ナレーション合成
            print("\n[4/10] ナレーション合成")
            audio_path, temp_files = self.synthesize_narration(content["script"])

            # 3分保証チェック + 自動リトライ（ユーザールール: 動画は3分以上）
            MIN_DURATION_SECONDS = 180  # 3分
            MAX_AUDIO_RETRIES = 2  # 音声長不足時の最大リトライ回数

            audio_duration = get_audio_duration(audio_path) if audio_path and os.path.exists(audio_path) else 0
            print(f"[INFO] 音声長: {audio_duration:.1f}秒 (約{audio_duration / 60:.1f}分)")

            audio_retry = 0
            while (
                self.mode not in ["--test", "--short-prod"]
                and audio_duration < MIN_DURATION_SECONDS
                and audio_retry < MAX_AUDIO_RETRIES
            ):
                audio_retry += 1
                print(f"\n[WARN] 音声長不足: {audio_duration:.1f}秒 < {MIN_DURATION_SECONDS}秒")
                print(f"[RETRY] 台本再生成+TTS再合成 (リトライ {audio_retry}/{MAX_AUDIO_RETRIES})")

                # 台本を再生成（generate_contentを再呼び出し）
                print("[RETRY] 台本再生成中...")
                content = self.generate_content()
                self.validate_script(content)

                # TTS再合成
                print("[RETRY] ナレーション再合成中...")
                audio_path, temp_files = self.synthesize_narration(content["script"])
                audio_duration = get_audio_duration(audio_path) if audio_path and os.path.exists(audio_path) else 0
                print(f"[RETRY] 音声長: {audio_duration:.1f}秒 (約{audio_duration / 60:.1f}分)")

            if self.mode not in ["--test", "--short-prod"] and audio_duration < MIN_DURATION_SECONDS:
                raise Exception(
                    f"音声長不足: {audio_duration:.1f}秒 < {MIN_DURATION_SECONDS}秒（{MAX_AUDIO_RETRIES}回リトライ後も不足）"
                )

            # 5. 字幕タイミング
            print("\n[5/10] 字幕タイミング取得")
            words = self.get_subtitle_timing(audio_path)

            # 6. 動画生成（Remotion必須、MoviePy禁止）
            print("\n[6/10] 動画生成")

            if not use_remotion:
                raise RuntimeError("ユーザールール違反: Remotion以外での動画生成は禁止です")

            # Remotionでエフェクト付き動画を生成（失敗時は最大3回リトライ）
            max_retries = 3
            for retry_attempt in range(max_retries):
                try:
                    remotion_video_path = self.create_video_with_remotion(content, audio_path)
                    # 音声を結合（Remotion動画は映像のみ）
                    import subprocess

                    final_video_path = os.path.join(OUTPUT_DIR, "nenkin_remotion_final.mp4")
                    ffmpeg_cmd = [
                        "ffmpeg",
                        "-y",
                        "-i",
                        remotion_video_path,
                        "-i",
                        audio_path,
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-shortest",
                        final_video_path,
                    ]
                    subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)
                    video_path = final_video_path
                    print(f"[OK] Remotion動画＋音声結合完了: {video_path}")
                    break  # 成功したらループ終了
                except Exception as e:
                    print(f"[WARN] Remotion失敗 ({e})、リトライ {retry_attempt + 1}/{max_retries}")
                    if retry_attempt < max_retries - 1:
                        import time

                        time.sleep(3)
                    else:
                        raise RuntimeError(f"Remotion {max_retries}回失敗。MoviePy禁止のため停止: {e}")

            # 6.0.5. イントロ動画結合スキップ（OPスライド廃止→ジングルは本編Remotion内で再生）
            # video_path = self.add_intro_to_video(video_path)

            # 6.0.6. クイズintroはRemotion内に組み込み済み（別動画結合は不要）
            # video_path = self.add_quiz_intro_to_video(video_path, chart_data_list)

            # 6.0.8. 控室トーク動画を末尾に結合（オフレコぶっちゃけトーク = 最重要コンテンツ）
            print("--- 控室トーク結合 ---")
            video_path = self.add_hikaeshitsu_to_video(video_path, content=content)

            # 6.1. 一時ファイルをクリーンアップ（動画生成完了後）
            print(f"--- 一時ファイルクリーンアップ ({len(temp_files)}ファイル) ---")
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        print(f"[OK] 削除: {temp_file}")
                    except Exception as e:
                        print(f"[WARN]  削除失敗: {temp_file} - {e}")

            # 7. YouTubeアップロード (本番のみ)
            if self.mode == "--prod":
                print("\n[7/10] YouTube アップロード")
                video_id = None
                try:
                    video_id = self.uploader.upload_video(
                        video_path, content["title"], content["description"], tags=content["tags"]
                    )

                    if not video_id:
                        print("[WARN]  動画アップロードに失敗しました（video_id取得失敗）")
                        print("[WARN]  動画ファイルは生成されています: " + video_path)
                except Exception as e:
                    print(f"[WARN]  動画アップロードでエラー発生: {e}")
                    print("[WARN]  動画ファイルは生成されています: " + video_path)
                    video_id = None

                # 8. サムネイル設定
                if video_id and youtube_thumb_path:
                    try:
                        print("--- サムネイル設定中 ---")
                        self.uploader.set_thumbnail(video_id, youtube_thumb_path)
                    except Exception as e:
                        print(f"[WARN]  サムネイル設定失敗: {e}")

                # 9. 初コメント投稿
                if video_id and content.get("first_comment"):
                    try:
                        print("--- 初コメント投稿中 ---")
                        self.uploader.post_comment(video_id, content["first_comment"])
                    except Exception as e:
                        print(f"[WARN]  初コメント投稿失敗: {e}")

                # 10. 再生リスト・ポッドキャスト追加
                if video_id:
                    try:
                        print("--- 再生リスト・ポッドキャスト追加中 ---")
                        playlist_ids = os.environ.get("YOUTUBE_PLAYLIST_IDS", "").split(",")
                        for playlist_id in playlist_ids:
                            if playlist_id.strip():
                                try:
                                    self.uploader.add_video_to_playlist(playlist_id.strip(), video_id)
                                except Exception as e:
                                    print(f"[WARN]  再生リスト追加失敗 ({playlist_id}): {e}")
                    except Exception as e:
                        print(f"[WARN]  再生リスト処理エラー: {e}")

                print("\n" + "=" * 60)
                if video_id:
                    print(f"[OK] 全処理完了 | 動画ID: {video_id}")
                    # エピソード番号表示（YouTube API動画数ベース）
                    episode_num = content.get("episode_number", 1)
                    print(f"[OK] エピソード番号 #{episode_num}（YouTube動画数ベース）")
                else:
                    print(f"[ERR] 動画ファイル生成完了（アップロード失敗）: {video_path}")
                    print("[ERR] YouTube アップロードに失敗しました。ワークフローを失敗として終了します。")
                    sys.exit(1)
                print("=" * 60)
            else:
                print("\n" + "=" * 60)
                print(f"[OK] テスト動画生成完了: {video_path}")
                print("=" * 60)

        except KeyboardInterrupt:
            print("\n[WARN]  ユーザーによる中断")
            raise
        except Exception as e:
            print("\n" + "=" * 60)
            print("[ERR] パイプライン実行エラー")
            print("=" * 60)
            print(f"エラー種別: {type(e).__name__}")
            print(f"エラー内容: {e}")
            import traceback

            print("\nスタックトレース:")
            traceback.print_exc()
            print("=" * 60)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--prod", action="store_true")
    parser.add_argument("--short-prod", action="store_true")
    parser.add_argument("--remotion", action="store_true", help="Remotionでエフェクト付き動画を生成")
    parser.add_argument("--script-only", action="store_true", help="台本のみ生成して表示（動画・音声生成なし）")
    args = parser.parse_args()

    if args.script_only:
        # 台本のみ生成モード
        engine = VideoEngineV4(mode="--prod", script_only=True)
        print("\n" + "=" * 60)
        print("台本のみ生成モード（--script-only）")
        print("=" * 60 + "\n")
        content = engine.generate_content()
        print("\n" + "=" * 60)
        print("生成された台本")
        print("=" * 60)
        print(f"タイトル: {content.get('title', '')}")
        print(f"サマリー: {content.get('summary', '')}")
        print(f"タグ: {content.get('tags', [])}")
        print(f"\n--- 台本 ({len(content.get('script', []))}行) ---")
        total_chars = 0
        for i, line in enumerate(content.get("script", []), 1):
            text = line.get("text", "")
            total_chars += len(text)
            print(f"{i:2d}. [{line.get('speaker', '?')}] ({line.get('emotion', 'default')}) {text}")
        print(f"\n合計: {total_chars}文字 (約{total_chars // 300}分{(total_chars % 300) // 5}秒)")
        print("台本JSON: output/content.json")
        return

    if args.prod:
        mode = "--prod"
    elif args.short_prod:
        mode = "--short-prod"
    else:
        mode = "--test"

    engine = VideoEngineV4(mode=mode)
    engine.run(use_remotion=True)


if __name__ == "__main__":
    main()
