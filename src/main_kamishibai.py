"""
紙芝居（こすり直し）パイプライン v2.0
===========================================
人気YouTube動画を分析 → カツミ・ヒロシ視点でリライト → Pillow画像 → TTS音声 → Remotion動画 → サムネイル → YouTube投稿 → スプシログ

使い方:
  python main_kamishibai.py                    # テスト実行（投稿しない）
  python main_kamishibai.py --prod             # 本番（YouTube投稿あり）
  python main_kamishibai.py --theme 家庭料理    # テーマ指定
"""

import os
import sys
import json
import time
import asyncio
import subprocess
import argparse
import random
import datetime
import re

from dotenv import load_dotenv
load_dotenv()

# ==========================================
# 定数
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTION_DIR = os.path.join(SCRIPT_DIR, "..", "remotion")
PUBLIC_DIR = os.path.join(REMOTION_DIR, "public")
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "out")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(PUBLIC_DIR, exist_ok=True)

# チャンネル設定（.envから読み込み）
CHANNEL_THEME = os.getenv("CHANNEL_THEME", "家庭料理")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "おばあちゃんの台所")
CHANNEL_COLOR = os.getenv("CHANNEL_COLOR", "#CD853F")

# APIキー
GOOGLE_API_KEYS = [k.strip() for k in os.getenv("GOOGLE_API_KEYS", "").split(",") if k.strip()]

# TTS設定
KATSUMI_VOICE = "ja-JP-NanamiNeural"  # Edge TTS 女性
HIROSHI_VOICE = "ja-JP-KeitaNeural"   # Edge TTS 男性

# Pillow設定
FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
CHAR_ASSETS = os.path.expanduser("~/.gemini/antigravity/shared_assets/character_expressions")

FPS = 24

# ==========================================
# 1. YouTube検索: 人気動画を見つける
# ==========================================
def search_popular_videos(theme, max_results=5, min_views=10000):
    """YouTube Data API v3でテーマの人気動画を検索"""
    import httpx
    
    search_queries = [
        f"{theme} シニア",
        f"{theme} 高齢者",
        f"{theme} 60代 70代",
        f"{theme} ランキング",
        f"{theme} おすすめ",
    ]
    
    videos = []
    for api_key in GOOGLE_API_KEYS[:3]:
        for query in search_queries[:2]:
            try:
                url = "https://www.googleapis.com/youtube/v3/search"
                params = {
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": max_results,
                    "key": api_key,
                    "relevanceLanguage": "ja",
                    "regionCode": "JP",
                }
                resp = httpx.get(url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                    
                data = resp.json()
                for item in data.get("items", []):
                    vid = item["id"].get("videoId")
                    if not vid:
                        continue
                    
                    # 動画の統計情報を取得
                    stats_url = "https://www.googleapis.com/youtube/v3/videos"
                    stats_params = {"part": "statistics,snippet", "id": vid, "key": api_key}
                    stats_resp = httpx.get(stats_url, params=stats_params, timeout=10)
                    if stats_resp.status_code == 200:
                        stats_data = stats_resp.json()
                        if stats_data.get("items"):
                            stats = stats_data["items"][0]["statistics"]
                            views = int(stats.get("viewCount", 0))
                            comments = int(stats.get("commentCount", 0))
                            if views >= min_views:
                                videos.append({
                                    "id": vid,
                                    "title": item["snippet"]["title"],
                                    "channel": item["snippet"]["channelTitle"],
                                    "views": views,
                                    "comments": comments,
                                    "url": f"https://www.youtube.com/watch?v={vid}",
                                })
                time.sleep(0.5)
            except Exception as e:
                print(f"[WARN] YouTube検索エラー: {e}")
                continue
    
    # 重複除去 + 再生数降順ソート
    seen = set()
    unique = []
    for v in sorted(videos, key=lambda x: x["views"], reverse=True):
        if v["id"] not in seen:
            seen.add(v["id"])
            unique.append(v)
    
    return unique[:max_results]


# ==========================================
# 2. Gemini分析: 動画のポイント抽出
# ==========================================
def analyze_with_gemini(video_info, theme):
    """Gemini Flash APIで動画メタデータから紙芝居要素を生成"""
    from google import genai
    from google.genai import types

    api_key = random.choice(GOOGLE_API_KEYS) if GOOGLE_API_KEYS else None
    if not api_key:
        raise ValueError("GOOGLE_API_KEYSが設定されていません")
    
    client = genai.Client(api_key=api_key)
    
    ref_info = "\n".join([
        f"- {v['title']} ({v.get('channel','不明')}, {v['views']:,}回再生, コメント{v['comments']}件)"
        for v in video_info[:3]
    ])
    
    prompt = f"""あなたはYouTube紙芝居動画の台本構成エキスパートです。
テーマ: 「{theme}」
ターゲット: 60-80代日本人女性（中高年シニア層）

以下の人気YouTube動画を参考に、このテーマの紙芝居台本要素を生成してください:
{ref_info}

重要ルール:
- 「損得」感情を間接的に刺激する（「知らないと損」「実はまだ間に合う」）
- カツミ（庶民派おばちゃん）とヒロシ（物知りおじさん）の掛け合いで構成
- 体験談や庶民あるある、共感を含める
- 数字は具体的に
- 全6スライド構成
- 【最重要】OPスライド（1枚目/hook）は「衝撃の事実」で視聴者を釘付けにする:
  - クイズ形式ではなく、事実ベースの衝撃データを大きく表示
  - 例: 「夜間頻尿の潜在患者数...800万人」「捨てている野菜の皮に栄養の60%が...」
  - ポジティブでもネガティブでもOK
  - この1枚で「絶対にこの動画を最後まで見たい」と思わせるインパクト
  - data_numberに最も衝撃的な数値を入れること

出力はJSON形式で:
```json
{{
  "title": "YouTube投稿タイトル（40文字以内、知らないと損系）",
  "description": "YouTube概要欄テキスト（100文字以内）",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "slides": [
    {{
      "tag": "hook",
      "speaker": "katsumi",
      "subtitle": "衝撃の事実に驚くカツミのセリフ（40文字以内）",
      "data_title": "衝撃の事実タイトル（短く）",
      "data_number": "最も衝撃的な数値（例: 800万, 60%, 3人に1人）",
      "data_unit": "単位（人, %, 円 等）",
      "data_source": "出典（学会名・調査名等）",
      "table_header": "テーブルヘッダー",
      "table_rows": [["項目名", "内容"], ["項目名", "内容"]]
    }},
    {{
      "tag": "causes",
      "speaker": "hiroshi",
      "subtitle": "ヒロシの解説セリフ（40文字以内）",
      "data_title": "データパネルタイトル",
      "data_number": "数値",
      "data_unit": "単位",
      "table_header": "テーブルヘッダー",
      "table_rows": [["原因1", "詳細"], ["原因2", "詳細"], ["原因3", "詳細"]]
    }},
    {{
      "tag": "solutions",
      "speaker": "katsumi",
      "subtitle": "カツミの提案セリフ（40文字以内）",
      "data_title": "方法タイトル",
      "data_number": "数値",
      "data_unit": "単位",
      "table_header": "方法一覧ヘッダー",
      "table_rows": [["方法1", "詳細"], ["方法2", "詳細"]]
    }},
    {{
      "tag": "before_after",
      "speaker": "katsumi",
      "subtitle": "体験談セリフ（40文字以内、具体的数字入り）",
      "data_title": "体験者プロフィール",
      "data_number": "数値変化",
      "data_unit": "単位",
      "table_header": "BEFORE→AFTER",
      "table_rows": [["項目", "変化"], ["項目", "変化"]]
    }},
    {{
      "tag": "summary",
      "speaker": "hiroshi",
      "subtitle": "まとめセリフ（今日からできるアクション）",
      "data_title": "チェックリスト",
      "data_number": "1",
      "data_unit": "つだけ",
      "table_header": "タイミング",
      "table_rows": [["やること", "いつ"], ["やること", "いつ"]]
    }},
    {{
      "tag": "hikaeshitsu",
      "speaker": "katsumi",
      "subtitle": "控え室エピローグ（本編の余韻に浸るトーク）"
    }}
  ],
  "tts_scripts": [
    {{"slide": 0, "speaker": "katsumi", "text": "衝撃の事実に驚くカツミの30秒語り（hook用、数字を繰り返して強調）"}},
    {{"slide": 0, "speaker": "hiroshi", "text": "ヒロシの30秒応答（hook用、事実の背景を補足）"}},
    {{"slide": 1, "speaker": "hiroshi", "text": "ヒロシの30秒解説（causes用）"}},
    {{"slide": 1, "speaker": "katsumi", "text": "カツミの30秒反応（causes用）"}},
    {{"slide": 2, "speaker": "katsumi", "text": "カツミの30秒提案（solutions用）"}},
    {{"slide": 2, "speaker": "hiroshi", "text": "ヒロシの30秒補足（solutions用）"}},
    {{"slide": 3, "speaker": "katsumi", "text": "カツミの30秒体験談語り（before_after用）"}},
    {{"slide": 3, "speaker": "hiroshi", "text": "ヒロシの30秒感想（before_after用）"}},
    {{"slide": 4, "speaker": "hiroshi", "text": "ヒロシの30秒まとめ（summary用）"}},
    {{"slide": 4, "speaker": "katsumi", "text": "カツミの30秒締め（summary用）"}},
    {{"slide": 5, "speaker": "katsumi", "text": "控え室エピローグ: 本編を振り返って余韻に浸るカツミのしみじみトーク（30秒）"}},
    {{"slide": 5, "speaker": "hiroshi", "text": "控え室エピローグ: カツミに共感しながら温かく締めくくるヒロシのトーク（30秒）"}}
  ]
}}
```

重要な制約:
- OPスライド(hook)のdata_numberは動画内で最も衝撃的な事実の数値にすること
- 控え室(hikaeshitsu)はエピローグ。本編の余韻に浸れる温かいトーク。「今日の話、心に残ったね」的な振り返り
- 各tts_scriptsのtextは話し言葉で自然に。1スライドあたり2人で合計60秒程度（全体3分以上）。"""
    
    response = client.models.generate_content(
        model="gemini-2.5-pro",  # ウルトラプラン: Pro、プラン下げたら gemini-2.0-flash に戻す
        contents=prompt,
    )
    
    text = response.text
    if "```json" in text:
        json_str = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        json_str = text.split("```")[1].split("```")[0].strip()
    else:
        json_str = text.strip()
    
    return json.loads(json_str)


# ==========================================
# 3. Pillow画像生成: 6枚の紙芝居フレーム (自己完結版)
# ==========================================
def generate_kamishibai_images(analysis, theme, output_dir):
    """generate_images.py (自己完結版) で紙芝居画像を生成"""
    from generate_images import make_frame, draw_data_panel, draw_table_panel, paste_emotion_bubble
    
    slides = analysis.get("slides", [])
    image_paths = []
    
    color_map = {
        "hook": (200, 60, 40),
        "causes": (80, 140, 200),
        "solutions": (80, 160, 80),
        "before_after": (80, 180, 80),
        "summary": (255, 200, 60),
        "hikaeshitsu": (100, 100, 100),
    }
    
    table_color_map = {
        "hook": (255, 180, 100),
        "causes": (100, 200, 255),
        "solutions": (100, 255, 100),
        "before_after": (255, 200, 100),
        "summary": (100, 200, 255),
    }
    
    expressions = {
        "hook": {"ke": "neutral", "he": "neutral", "kb": "odoroki", "hb": "gimon"},
        "causes": {"ke": "happy", "he": "neutral", "kb": "hirameki", "hb": "gimon"},
        "solutions": {"ke": "guts", "he": "happy", "kb": "iine", "hb": "hirameki"},
        "before_after": {"ke": "guts", "he": "happy", "kb": "suki", "hb": "iine"},
        "summary": {"ke": "happy", "he": "guts", "kb": "iine", "hb": "suki"},
        "hikaeshitsu": {"ke": "happy", "he": "happy", "kb": "", "hb": ""},
    }
    
    for i, slide in enumerate(slides):
        tag = slide.get("tag", f"slide_{i+1}")
        spk = slide.get("speaker", "katsumi")
        sub = slide.get("subtitle", "")
        is_hikae = tag == "hikaeshitsu"
        
        expr = expressions.get(tag, expressions["hook"])
        
        try:
            img, d = make_frame(
                sub, "", f"{theme} | {CHANNEL_NAME}",
                expr["ke"], expr["he"],
                None if is_hikae else ("katsumi_sad" if tag == "hook" else "katsumi_happy"),
                None if is_hikae else ("hiroshi_happy" if tag == "hook" else "hiroshi_relieved"),
                spk,
                k_bubble=expr["kb"], h_bubble=expr["hb"],
                hikae=is_hikae
            )
            
            if not is_hikae:
                dc = color_map.get(tag, (200, 60, 40))
                tc = table_color_map.get(tag, (255, 180, 100))
                
                draw_data_panel(
                    img, d,
                    slide.get("data_title", ""),
                    "",
                    slide.get("data_number", "0"),
                    slide.get("data_unit", ""),
                    dc
                )
                
                rows = slide.get("table_rows", [])
                tr = [(r[0], r[1] if len(r) > 1 else "", (100, 200, 100)) for r in rows]
                draw_table_panel(
                    img, d,
                    slide.get("table_header", ""),
                    tc,
                    tr
                )
                
                paste_emotion_bubble(img, expr["kb"], side="left")
                paste_emotion_bubble(img, expr["hb"], side="right")
            
            fname = f"slide_{i+1:02d}_{tag}.png"
            fpath = os.path.join(output_dir, fname)
            img.save(fpath)
            image_paths.append(fname)
            print(f"  [{i+1}] {tag} -> {fname}")
            
        except Exception as e:
            print(f"  [{i+1}] {tag} ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    return image_paths


# ==========================================
# 4. TTS音声生成: Edge TTSで各スライドの音声
# ==========================================
def generate_tts_audio(tts_scripts, output_dir):
    """Edge TTSで各スライドのTTS音声を生成"""
    import edge_tts
    
    voice_map = {
        "katsumi": KATSUMI_VOICE,
        "hiroshi": HIROSHI_VOICE,
    }
    
    # スライドごとに音声をまとめる
    slide_audio = {}  # {slide_idx: [audio_path1, audio_path2]}
    
    for j, item in enumerate(tts_scripts):
        slide_idx = item.get("slide", 0)
        speaker = item.get("speaker", "katsumi")
        text = item.get("text", "")
        voice = voice_map.get(speaker, KATSUMI_VOICE)
        
        mp3_path = os.path.join(output_dir, f"tts_{j:02d}_{speaker}.mp3")
        wav_path = os.path.join(output_dir, f"tts_{j:02d}_{speaker}.wav")
        
        try:
            async def _gen():
                c = edge_tts.Communicate(text, voice)
                await c.save(mp3_path)
            
            asyncio.run(_gen())
            
            # mp3 → wav変換
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_path,
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                wav_path
            ], capture_output=True, timeout=30)
            
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
            
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                if slide_idx not in slide_audio:
                    slide_audio[slide_idx] = []
                slide_audio[slide_idx].append(wav_path)
                print(f"  TTS [{j}] slide{slide_idx} {speaker} → OK")
            else:
                print(f"  TTS [{j}] slide{slide_idx} {speaker} → FAIL (WAV empty)")
                
        except Exception as e:
            print(f"  TTS [{j}] slide{slide_idx} {speaker} → ERROR: {e}")
    
    # 各スライドの音声を結合
    slide_wavs = {}
    for slide_idx in sorted(slide_audio.keys()):
        wavs = slide_audio[slide_idx]
        if len(wavs) == 1:
            slide_wavs[slide_idx] = wavs[0]
        else:
            combined = os.path.join(output_dir, f"slide_{slide_idx:02d}_combined.wav")
            # ffmpegで結合
            list_file = os.path.join(output_dir, f"concat_{slide_idx}.txt")
            with open(list_file, "w") as f:
                for w in wavs:
                    f.write(f"file '{os.path.abspath(w)}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_file, "-c", "copy", combined
            ], capture_output=True, timeout=30)
            slide_wavs[slide_idx] = combined
    
    return slide_wavs


# ==========================================
# 5. 音声尺に基づいてRemotionプロパティ生成
# ==========================================
def get_audio_duration(wav_path):
    """ffprobeで音声の長さを取得（秒）"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", wav_path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return 30.0  # フォールバック


def build_remotion_props(analysis, image_paths, slide_wavs, output_dir):
    """Remotion用のprops.jsonを構築"""
    slides = []
    total_frames = 0
    
    for i, img_name in enumerate(image_paths):
        wav_path = slide_wavs.get(i)
        if wav_path and os.path.exists(wav_path):
            duration_sec = get_audio_duration(wav_path)
            # 音声ファイルをpublicにコピー
            audio_name = f"slide_{i+1:02d}_audio.wav"
            audio_dest = os.path.join(PUBLIC_DIR, audio_name)
            subprocess.run(["cp", wav_path, audio_dest], capture_output=True)
        else:
            duration_sec = 30.0
            audio_name = ""
        
        duration_frames = max(int(duration_sec * FPS) + FPS, FPS * 5)  # 最低5秒
        
        slides.append({
            "image": img_name,
            "audioPath": audio_name,
            "durationFrames": duration_frames,
            "subtitle": analysis["slides"][i]["subtitle"] if i < len(analysis["slides"]) else "",
            "tag": analysis["slides"][i]["tag"] if i < len(analysis["slides"]) else f"slide_{i+1}",
        })
        total_frames += duration_frames
    
    # 3分（4320フレーム）以上を保証
    min_frames = 3 * 60 * FPS
    if total_frames < min_frames:
        # 各スライドに均等に追加
        extra = (min_frames - total_frames) // len(slides)
        for s in slides:
            s["durationFrames"] += extra
        total_frames = sum(s["durationFrames"] for s in slides)
    
    props = {
        "kamishibaiSlides": slides,
        "kamishibaiDuration": total_frames,
        "kamishibaiBgm": "hikaeshitsu_bgm.mp3",
        "channelName": CHANNEL_NAME,
        "channelColor": CHANNEL_COLOR,
    }
    
    props_path = os.path.join(REMOTION_DIR, "props.json")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False, indent=2)
    
    print(f"  props.json → {total_frames}フレーム ({total_frames/FPS:.1f}秒)")
    return props_path, total_frames


# ==========================================
# 6. Remotion動画レンダリング
# ==========================================
def render_video(props_path, total_frames, output_path):
    """Remotionで紙芝居動画をレンダリング"""
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts", "KamishibaiVideo",
        output_path,
        "--props", props_path,
        "--concurrency", "2",
    ]
    
    print(f"  Remotionレンダリング開始... ({total_frames}フレーム)")
    result = subprocess.run(cmd, cwd=REMOTION_DIR, capture_output=True, text=True, timeout=600)
    
    if result.returncode == 0 and os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  [OK] 動画生成完了: {output_path} ({size_mb:.1f}MB)")
        return True
    else:
        print(f"  [ERROR] Remotionレンダリング失敗")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        return False


# ==========================================
# 7. サムネイル自動生成
# ==========================================
def generate_thumbnail(analysis, theme, output_path):
    """YouTube用サムネイル画像を自動生成 (1280x720)"""
    from PIL import Image, ImageDraw, ImageFont
    from generate_images import gf
    
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    # グラデーション背景
    for y in range(H):
        r = int(20 + 60 * y / H)
        g = int(10 + 30 * y / H)
        b = int(40 + 80 * y / H)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    
    # 赤い帯（上部）
    d.rectangle([(0, 0), (W, 80)], fill=(200, 40, 40))
    d.text((30, 15), f"{CHANNEL_NAME}", fill=(255, 255, 255), font=gf(48),
           stroke_width=2, stroke_fill=(0, 0, 0))
    
    # メインタイトル
    title = analysis.get("title", f"{theme}の知恵")
    # 2行に分割
    import textwrap
    lines = textwrap.wrap(title, width=12)
    for i, line in enumerate(lines[:3]):
        y = 150 + i * 130
        d.text((60, y), line, fill=(255, 255, 0), font=gf(110),
               stroke_width=6, stroke_fill=(0, 0, 0))
    
    # フック数字（右下に大きく）
    slides = analysis.get("slides", [])
    if slides:
        num = slides[0].get("data_number", "")
        unit = slides[0].get("data_unit", "")
        if num:
            d.text((W - 400, H - 250), num, fill=(255, 80, 80), font=gf(160),
                   stroke_width=4, stroke_fill=(0, 0, 0))
            if unit:
                d.text((W - 400, H - 100), unit, fill=(255, 200, 200), font=gf(60),
                       stroke_width=2, stroke_fill=(0, 0, 0))
    
    img.save(output_path, quality=95)
    print(f"  サムネイル生成: {output_path}")
    return output_path


# ==========================================
# 8. YouTube投稿
# ==========================================
def upload_to_youtube(video_path, analysis, theme, thumbnail_path=None):
    """YouTube APIで動画を投稿"""
    try:
        sys.path.insert(0, os.path.join(SCRIPT_DIR))
        from youtube_uploader import YouTubeUploader
        
        uploader = YouTubeUploader()
        
        title = analysis.get("title", f"{theme}の知恵")
        description = analysis.get("description", "")
        tags = analysis.get("tags", [theme, "シニア", "知恵"])
        
        full_description = f"""{description}

━━━━━━━━━━━━━━━━━━━━
{CHANNEL_NAME}
カツミとヒロシがお届けする{theme}の知恵

チャンネル登録よろしくお願いします!
━━━━━━━━━━━━━━━━━━━━

#{'#'.join(tags[:5])}
"""
        
        result = uploader.upload(
            video_path=video_path,
            title=title[:100],
            description=full_description[:5000],
            tags=tags,
            category_id="22",
            thumbnail_path=thumbnail_path,
        )
        
        if result:
            video_id = result.get("id", "")
            url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"\n  ★ YouTube投稿完了: {url}")
            return url, video_id
        
    except Exception as e:
        print(f"  [ERROR] YouTube投稿失敗: {e}")
    
    return None, None


# ==========================================
# 9. スプシ投稿ログ
# ==========================================
def log_to_spreadsheet(theme, title, video_url, video_id, ref_videos):
    """スプシの紙芝居管理シートに投稿ログを記録"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        sa_key = os.getenv("SA_KEY_PATH", "/Users/user/.gemini/antigravity/credentials/service_account.json")
        sheet_id = os.getenv("SPREADSHEET_ID", "1wEx6UpIQ-QOcBYkYgSXa8L20jzJGHdw1WJyTxQGIWc0")
        
        if not os.path.exists(sa_key):
            print("  [SKIP] サービスアカウント鍵なし、スプシログをスキップ")
            return
        
        creds = Credentials.from_service_account_file(sa_key, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
        ])
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(sheet_id)
        
        try:
            sheet = ss.worksheet("紙芝居管理")
        except Exception:
            sheet = ss.add_worksheet(title="紙芝居管理", rows=500, cols=10)
            sheet.append_row(["日時", "リポ", "テーマ", "タイトル", "URL", "参考動画", "ステータス"])
        
        ref_str = " / ".join([v.get("title", "")[:30] for v in ref_videos[:3]])
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        repo_name = os.path.basename(os.path.dirname(SCRIPT_DIR))
        
        sheet.append_row([
            now,
            repo_name,
            theme,
            title[:50],
            video_url or "",
            ref_str,
            "投稿済" if video_url else "テスト",
        ])
        print(f"  [OK] スプシ投稿ログ記録完了")
        
    except Exception as e:
        print(f"  [WARN] スプシログ記録失敗: {e}")


# ==========================================
# メインパイプライン
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="紙芝居パイプライン v2.0")
    parser.add_argument("--prod", action="store_true", help="本番モード（YouTube投稿あり）")
    parser.add_argument("--theme", type=str, default=None, help="テーマ指定")
    parser.add_argument("--skip-search", action="store_true", help="YouTube検索をスキップ")
    args = parser.parse_args()
    
    theme = args.theme or CHANNEL_THEME
    
    print(f"=" * 60)
    print(f"紙芝居パイプライン v2.0")
    print(f"テーマ: {theme}")
    print(f"チャンネル: {CHANNEL_NAME}")
    print(f"モード: {'本番' if args.prod else 'テスト'}")
    print(f"=" * 60)
    
    work_dir = os.path.join(OUT_DIR, f"kamishibai_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(work_dir, exist_ok=True)
    
    # Step 1: YouTube検索
    print(f"\n[1/9] YouTube検索: {theme}の人気動画...")
    if args.skip_search:
        videos = [{"id": "dummy", "title": f"{theme}の人気動画", "channel": "テスト", "views": 100000, "comments": 100, "url": ""}]
    else:
        videos = search_popular_videos(theme)
    
    if not videos:
        print("  人気動画が見つかりませんでした。ダミーデータで続行")
        videos = [{"id": "dummy", "title": f"{theme}の人気動画", "channel": "テスト", "views": 100000, "comments": 100, "url": ""}]
    
    for v in videos[:3]:
        print(f"  {v['title'][:50]} ({v['views']:,}回再生)")
    
    # Step 2: Gemini分析
    print(f"\n[2/9] Gemini分析: ポイント抽出...")
    analysis = analyze_with_gemini(videos, theme)
    
    analysis_path = os.path.join(work_dir, "analysis.json")
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"  タイトル: {analysis.get('title', '?')}")
    print(f"  スライド数: {len(analysis.get('slides', []))}")
    print(f"  TTS台本数: {len(analysis.get('tts_scripts', []))}")
    
    # Step 3: Pillow画像生成
    print(f"\n[3/9] Pillow画像生成: 6枚...")
    image_paths = generate_kamishibai_images(analysis, theme, PUBLIC_DIR)
    print(f"  生成画像数: {len(image_paths)}")
    
    # Step 4: TTS音声生成
    print(f"\n[4/9] TTS音声生成: Edge TTS...")
    tts_scripts = analysis.get("tts_scripts", [])
    slide_wavs = generate_tts_audio(tts_scripts, work_dir)
    print(f"  生成音声数: {len(slide_wavs)}スライド分")
    
    # Step 5: Remotionプロパティ生成
    print(f"\n[5/9] Remotionプロパティ生成...")
    props_path, total_frames = build_remotion_props(analysis, image_paths, slide_wavs, work_dir)
    
    # Step 6: Remotion動画レンダリング
    print(f"\n[6/9] Remotion動画レンダリング...")
    video_path = os.path.join(OUT_DIR, f"kamishibai_{theme}.mp4")
    success = render_video(props_path, total_frames, video_path)
    
    if not success:
        print("\n[ERROR] 動画生成に失敗しました")
        return
    
    # Step 7: サムネイル生成
    print(f"\n[7/9] サムネイル生成...")
    thumbnail_path = os.path.join(OUT_DIR, f"thumbnail_{theme}.jpg")
    generate_thumbnail(analysis, theme, thumbnail_path)
    
    # Step 8: YouTube投稿（本番モードのみ）
    video_url = None
    video_id = None
    if args.prod:
        print(f"\n[8/9] YouTube投稿...")
        video_url, video_id = upload_to_youtube(video_path, analysis, theme, thumbnail_path)
        if video_url:
            print(f"\n{'=' * 60}")
            print(f"★ 投稿完了: {video_url}")
            print(f"{'=' * 60}")
    else:
        print(f"\n[8/9] テストモード: YouTube投稿スキップ")
        print(f"  動画ファイル: {video_path}")
    
    # Step 9: スプシログ
    print(f"\n[9/9] スプシ投稿ログ...")
    log_to_spreadsheet(
        theme=theme,
        title=analysis.get("title", ""),
        video_url=video_url,
        video_id=video_id,
        ref_videos=videos,
    )
    
    print(f"\n完了! 作業ディレクトリ: {work_dir}")


if __name__ == "__main__":
    main()
