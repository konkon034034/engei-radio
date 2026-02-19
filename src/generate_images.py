"""
紙芝居画像生成 v6.0 (自己完結版)
===================================
GitHub Actions(Ubuntu)でもローカル(Mac)でも動作する。
素材がない場合はPillowで代替描画。
"""
from PIL import Image, ImageDraw, ImageFont
import os
import math
import textwrap

# ==========================================
# パス設定（環境に応じて自動解決）
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
PUBLIC_DIR = os.path.join(SCRIPT_DIR, "..", "remotion", "public")

# フォント: mac → Ubuntu → フォールバック
FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",  # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Ubuntu
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",  # Fedora
]

_font_path = None
for fp in FONT_CANDIDATES:
    if os.path.exists(fp):
        _font_path = fp
        break


def gf(size):
    """日本語フォントを返す（見つからない場合はデフォルト）"""
    if _font_path:
        try:
            return ImageFont.truetype(_font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ==========================================
# 画面レイアウト定数
# ==========================================
W, H = 1920, 1080

DATA_LEFT = 180
DATA_W = 600
DATA_TOP = 5
DATA_H = 640

TABLE_LEFT = 800
TABLE_W = 1100
TABLE_TOP = 5
TABLE_H = 640

BAR_Y = 645
BAR_H = 435
SUB_TOP = BAR_Y + 20
SUB_LEFT = 140
SOURCE_TOP = BAR_Y - 35

TICK_H = 80
TICK_TOP = H - TICK_H

CHAR_H = 220
CHAR_TOP = BAR_Y - CHAR_H - 80

STORY_MARGIN = 10
STORY_LEFT_X = STORY_MARGIN
STORY_LEFT_Y = 10
STORY_H = 150
STORY_RIGHT_Y = 10

BUBBLE_SIZE = 120
BUBBLE_Y = CHAR_TOP - BUBBLE_SIZE - 5


# ==========================================
# キャラ読み込み（フォールバック付き）
# ==========================================
def _find_asset(name, dirs=None):
    """複数ディレクトリからアセットを探す"""
    search_dirs = dirs or [
        os.path.join(ASSETS_DIR, "characters"),
        os.path.join(ASSETS_DIR, "emotions"),
        os.path.join(PUBLIC_DIR),
        os.path.join(PUBLIC_DIR, "emotions"),
    ]
    for d in search_dirs:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return None


def load_char(name, h):
    """キャラ画像を読み込み。なければカラフルな代替画像を生成"""
    path = _find_asset(f"{name}.png")
    if path:
        img = Image.open(path).convert("RGBA")
        r = h / img.height
        return img.resize((int(img.width * r), h), Image.LANCZOS)

    # フォールバック: シンプルなシルエット
    w = int(h * 0.7)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # キャラ名からカラーを決定
    if "katsumi" in name:
        color = (255, 180, 120, 200)
        label = "K"
    elif "hiroshi" in name:
        color = (120, 180, 255, 200)
        label = "H"
    else:
        color = (180, 180, 180, 200)
        label = "?"

    # 丸い頭 + 四角い体
    head_r = w // 3
    cx, cy = w // 2, head_r + 5
    d.ellipse([(cx - head_r, cy - head_r), (cx + head_r, cy + head_r)], fill=color)
    d.rectangle([(cx - w // 3, cy + head_r), (cx + w // 3, h - 5)], fill=color)
    d.text((cx - 10, cy - 15), label, fill=(255, 255, 255), font=gf(30))

    return img


def load_emotion_bubble(emotion_name):
    """吹き出しアイコンを読み込み。なければテキスト代替"""
    if not emotion_name:
        return None

    emo_map = {
        "question": "gimon", "thinking": "gimon", "gimon": "gimon",
        "idea": "hirameki", "hirameki": "hirameki",
        "happy": "iine", "excited": "iine", "iine": "iine",
        "guts": "suki", "suki": "suki",
        "concerned": "moyamoya", "tired": "moyamoya", "yareyare": "moyamoya",
        "moyamoya": "moyamoya", "fuman": "moyamoya",
        "surprised": "odoroki", "shocked": "odoroki", "odoroki": "odoroki",
    }
    name = emo_map.get(emotion_name, emotion_name)

    path = _find_asset(f"{name}.png")
    if path:
        icon = Image.open(path).convert("RGBA")
        return icon.resize((BUBBLE_SIZE, BUBBLE_SIZE), Image.LANCZOS)

    # フォールバック: テキスト吹き出し
    labels = {
        "gimon": "？", "hirameki": "💡", "iine": "👍",
        "suki": "♥", "moyamoya": "〜", "odoroki": "！",
    }
    label = labels.get(name, "◯")
    img = Image.new("RGBA", (BUBBLE_SIZE, BUBBLE_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([(5, 5), (BUBBLE_SIZE - 5, BUBBLE_SIZE - 5)], fill=(255, 255, 255, 200))
    d.text((BUBBLE_SIZE // 2 - 20, BUBBLE_SIZE // 2 - 25), label, fill=(60, 60, 60), font=gf(48))
    return img


def paste_emotion_bubble(img, emotion_name, side="left"):
    """吹き出しアイコンを配置"""
    icon = load_emotion_bubble(emotion_name)
    if not icon:
        return
    by = BUBBLE_Y
    if side == "left":
        bx = STORY_MARGIN
    else:
        bx = W - BUBBLE_SIZE - STORY_MARGIN
    img.paste(icon, (bx, by), icon)


# ==========================================
# フレーム生成
# ==========================================
def make_frame(subtitle, source, ticker, k_exp, h_exp, neg, pos, speaker,
               k_bubble="", h_bubble="", hikae=False):
    """紙芝居フレーム v6.0"""

    # === 背景 ===
    bg_path = _find_asset("background.png")
    if bg_path and not hikae:
        bg = Image.open(bg_path).convert("RGBA").resize((W, int(H * 1.15)), Image.LANCZOS)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        img.paste(bg, (0, int(-H * 0.075)))
    else:
        # フォールバック: グラデーション背景
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        if hikae:
            for y in range(H):
                r = int(20 + 30 * y / H)
                g = int(15 + 25 * y / H)
                b = int(40 + 40 * y / H)
                d.line([(0, y), (W, y)], fill=(r, g, b))
        else:
            for y in range(H):
                r = int(10 + 40 * y / H)
                g = int(20 + 50 * y / H)
                b = int(50 + 60 * y / H)
                d.line([(0, y), (W, y)], fill=(r, g, b))

    d = ImageDraw.Draw(img)

    if not hikae:
        # === 左上ネガキャラ ===
        if neg:
            nc = load_char(neg, STORY_H)
            if nc:
                img.paste(nc, (STORY_LEFT_X, STORY_LEFT_Y), nc)

        # === 右上ポジキャラ ===
        if pos:
            pc = load_char(pos, STORY_H)
            if pc:
                rx = W - pc.width - STORY_MARGIN
                img.paste(pc, (rx, STORY_RIGHT_Y), pc)

    # === 出典 ===
    if source and not hikae:
        st = f"出典：{source}"
        bb = d.textbbox((0, 0), st, font=gf(28))
        tw = bb[2] - bb[0]
        d.text((W - 20 - tw, SOURCE_TOP), st,
               fill=(255, 255, 255), font=gf(28),
               stroke_width=3, stroke_fill=(0, 0, 0))

    if not hikae:
        # === カツミ ===
        k_img = load_char(f"katsumi_{k_exp}", CHAR_H)
        if k_img:
            img.paste(k_img, (0, CHAR_TOP), k_img)
            nf = gf(28)
            nx = k_img.width // 2 - 36
            ny = CHAR_TOP + CHAR_H + 2
            d.text((nx, ny), "カツミ", fill=(255, 255, 255), font=nf,
                   stroke_width=3, stroke_fill=(0, 0, 0))
            if speaker == "katsumi":
                bb = d.textbbox((nx, ny), "カツミ", font=nf)
                d.line([(bb[0], bb[3] + 3), (bb[2], bb[3] + 3)], fill=(255, 220, 50), width=4)

        # === ヒロシ ===
        h_img = load_char(f"hiroshi_{h_exp}", CHAR_H)
        if h_img:
            hx = W - h_img.width
            img.paste(h_img, (hx, CHAR_TOP), h_img)
            nf = gf(28)
            nx2 = hx + h_img.width // 2 - 36
            ny2 = CHAR_TOP + CHAR_H + 2
            d.text((nx2, ny2), "ヒロシ", fill=(255, 255, 255), font=nf,
                   stroke_width=3, stroke_fill=(0, 0, 0))
            if speaker == "hiroshi":
                bb = d.textbbox((nx2, ny2), "ヒロシ", font=nf)
                d.line([(bb[0], bb[3] + 3), (bb[2], bb[3] + 3)], fill=(255, 220, 50), width=4)

    # === 字幕バー ===
    bar = Image.new("RGBA", (W, BAR_H), (0, 0, 0, int(0.75 * 255)))
    img.paste(bar, (0, BAR_Y), bar)

    # === 字幕テキスト ===
    fs = 72 if len(subtitle) > 30 else (82 if len(subtitle) > 20 else 95)
    sf = gf(fs)
    sc = (255, 255, 0) if hikae else (255, 255, 255)
    for i, ln in enumerate(textwrap.wrap(subtitle, width=int(1660 * 0.95 / fs))[:5]):
        d.text((SUB_LEFT, SUB_TOP + i * int(fs * 1.15)), ln, fill=sc, font=sf,
               stroke_width=5, stroke_fill=(0, 0, 0))

    # === ティッカー ===
    tk = Image.new("RGBA", (W, TICK_H), (0, 0, 0, int(0.95 * 255)))
    img.paste(tk, (0, TICK_TOP), tk)
    d.text((30, TICK_TOP + 16), ticker, fill=(255, 255, 255), font=gf(48),
           stroke_width=2, stroke_fill=(0, 0, 0))

    return img, d


def draw_data_panel(img, d, title, desc, big_number, big_unit, color=(200, 60, 40)):
    """左データパネル"""
    p = Image.new("RGBA", (DATA_W, DATA_H), (0, 0, 0, int(0.85 * 255)))
    img.paste(p, (DATA_LEFT, DATA_TOP), p)
    d.rectangle([(DATA_LEFT, DATA_TOP), (DATA_LEFT + 6, DATA_TOP + DATA_H)], fill=(231, 76, 60))

    d.text((DATA_LEFT + 20, DATA_TOP + 12), title, fill=(255, 255, 255), font=gf(36),
           stroke_width=1, stroke_fill=(0, 0, 0))

    for i, ln in enumerate(desc.split("\n")):
        d.text((DATA_LEFT + 20, DATA_TOP + 65 + i * 38), ln, fill=(255, 255, 255), font=gf(32),
               stroke_width=1, stroke_fill=(0, 0, 0))

    max_text_w = DATA_W - 60
    num_fs = 140
    while num_fs > 60:
        nf = gf(num_fs)
        bb = d.textbbox((0, 0), big_number, font=nf)
        tw = bb[2] - bb[0]
        if tw <= max_text_w:
            break
        num_fs -= 10

    nf = gf(num_fs)
    bb = d.textbbox((0, 0), big_number, font=nf)
    tw = bb[2] - bb[0]
    nx = DATA_LEFT + (DATA_W - tw) // 2
    ny = DATA_TOP + 200
    d.text((nx, ny), big_number, fill=color, font=nf,
           stroke_width=2, stroke_fill=(0, 0, 0))

    if big_unit:
        uf = gf(44)
        ubb = d.textbbox((0, 0), big_unit, font=uf)
        uw = ubb[2] - ubb[0]
        ux = DATA_LEFT + (DATA_W - uw) // 2
        uy = ny + num_fs + 5
        d.text((ux, uy), big_unit, fill=color, font=uf,
               stroke_width=1, stroke_fill=(0, 0, 0))


def draw_table_panel(img, d, header, hc, rows):
    """右テーブルパネル"""
    p = Image.new("RGBA", (TABLE_W, TABLE_H), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (TABLE_LEFT, TABLE_TOP), p)
    d.rectangle([(TABLE_LEFT, TABLE_TOP), (TABLE_LEFT + TABLE_W, TABLE_TOP + 48)], fill=(40, 60, 80))
    d.text((TABLE_LEFT + 15, TABLE_TOP + 8), header, fill=hc, font=gf(32),
           stroke_width=1, stroke_fill=(0, 0, 0))
    for i, (l, v, vc) in enumerate(rows):
        ry = TABLE_TOP + 52 + i * 50
        d.text((TABLE_LEFT + 15, ry + 6), l, fill=(255, 255, 255), font=gf(32),
               stroke_width=1, stroke_fill=(0, 0, 0))
        if v:
            bb = d.textbbox((0, 0), v, font=gf(32))
            tw = bb[2] - bb[0]
            d.text((TABLE_LEFT + TABLE_W - 15 - tw, ry + 6), v, fill=vc, font=gf(32),
                   stroke_width=1, stroke_fill=(0, 0, 0))
        if i < len(rows) - 1 and l:
            d.line([(TABLE_LEFT + 10, ry + 45), (TABLE_LEFT + TABLE_W - 10, ry + 45)],
                   fill=(60, 70, 85), width=1)


# ==========================================
# グラフ描画（Pillow純正・ライブラリ不要）
# ==========================================

def draw_bar_chart(img, d, title, labels, values, colors=None,
                   area_left=None, area_top=None, area_w=None, area_h=None):
    """縦棒グラフを描画（テーブルパネル位置に描画）"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W
    ah = area_h or TABLE_H

    # 背景パネル
    p = Image.new("RGBA", (aw, ah), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)

    # タイトル
    d.text((al + 15, at + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    if not values:
        return

    max_val = max(values) if values else 1
    n = len(values)
    chart_top = at + 55
    chart_h = ah - 120
    chart_left = al + 20
    chart_w = aw - 40
    bar_w = max(20, min(80, chart_w // (n * 2)))
    gap = (chart_w - bar_w * n) // (n + 1)

    default_colors = [
        (231, 76, 60), (52, 152, 219), (46, 204, 113),
        (241, 196, 15), (155, 89, 182), (230, 126, 34),
    ]
    if not colors:
        colors = default_colors

    for i, (label, val) in enumerate(zip(labels, values)):
        bx = chart_left + gap + i * (bar_w + gap)
        bar_h = int((val / max_val) * chart_h * 0.85) if max_val > 0 else 10
        by = chart_top + chart_h - bar_h
        c = colors[i % len(colors)]

        # 棒
        d.rectangle([(bx, by), (bx + bar_w, chart_top + chart_h)], fill=c)

        # 値ラベル
        vt = str(val)
        vbb = d.textbbox((0, 0), vt, font=gf(24))
        vw = vbb[2] - vbb[0]
        d.text((bx + (bar_w - vw) // 2, by - 30), vt, fill=c, font=gf(24),
               stroke_width=1, stroke_fill=(0, 0, 0))

        # X軸ラベル（短縮）
        sl = label[:6]
        lbb = d.textbbox((0, 0), sl, font=gf(20))
        lw = lbb[2] - lbb[0]
        d.text((bx + (bar_w - lw) // 2, chart_top + chart_h + 8), sl,
               fill=(200, 200, 200), font=gf(20))

    # X軸線
    d.line([(chart_left, chart_top + chart_h), (chart_left + chart_w, chart_top + chart_h)],
           fill=(100, 100, 100), width=2)


def draw_line_chart(img, d, title, labels, values, color=(52, 152, 219),
                    area_left=None, area_top=None, area_w=None, area_h=None):
    """折れ線グラフを描画"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W
    ah = area_h or TABLE_H

    p = Image.new("RGBA", (aw, ah), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)

    d.text((al + 15, at + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    if not values or len(values) < 2:
        return

    max_val = max(values)
    min_val = min(values)
    val_range = max_val - min_val if max_val != min_val else 1

    chart_top = at + 60
    chart_h = ah - 130
    chart_left = al + 60
    chart_w = aw - 90
    n = len(values)

    # グリッド線
    for i in range(5):
        gy = chart_top + int(chart_h * i / 4)
        d.line([(chart_left, gy), (chart_left + chart_w, gy)],
               fill=(50, 50, 60), width=1)
        gv = max_val - (val_range * i / 4)
        d.text((al + 10, gy - 10), f"{gv:.0f}",
               fill=(150, 150, 150), font=gf(18))

    # データポイント + 線
    points = []
    for i, val in enumerate(values):
        px = chart_left + int(chart_w * i / (n - 1))
        ratio = (val - min_val) / val_range
        py = chart_top + int(chart_h * (1 - ratio))
        points.append((px, py))

    # 塗りつぶしエリア（半透明）
    fill_points = points + [(points[-1][0], chart_top + chart_h), (points[0][0], chart_top + chart_h)]
    fill_color = color + (60,)
    # ライン
    for i in range(len(points) - 1):
        d.line([points[i], points[i + 1]], fill=color, width=4)

    # ドット + 値
    for i, ((px, py), val) in enumerate(zip(points, values)):
        d.ellipse([(px - 6, py - 6), (px + 6, py + 6)], fill=color, outline=(255, 255, 255), width=2)
        d.text((px - 15, py - 28), str(val),
               fill=(255, 255, 255), font=gf(20), stroke_width=1, stroke_fill=(0, 0, 0))

    # X軸ラベル
    for i, label in enumerate(labels):
        px = chart_left + int(chart_w * i / (n - 1))
        sl = label[:5]
        lbb = d.textbbox((0, 0), sl, font=gf(18))
        lw = lbb[2] - lbb[0]
        d.text((px - lw // 2, chart_top + chart_h + 10), sl,
               fill=(180, 180, 180), font=gf(18))


def draw_horizontal_bar_chart(img, d, title, labels, values, colors=None,
                               area_left=None, area_top=None, area_w=None, area_h=None):
    """横棒グラフ（比較用）"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W
    ah = area_h or TABLE_H

    p = Image.new("RGBA", (aw, ah), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)

    d.text((al + 15, at + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    if not values:
        return

    max_val = max(values) if values else 1
    n = len(values)
    chart_top = at + 55
    chart_left = al + 180
    bar_area_w = aw - 210
    bar_h = max(20, min(45, (ah - 80) // (n + 1)))
    gap = 10

    default_colors = [
        (231, 76, 60), (52, 152, 219), (46, 204, 113),
        (241, 196, 15), (155, 89, 182), (230, 126, 34),
    ]
    if not colors:
        colors = default_colors

    for i, (label, val) in enumerate(zip(labels, values)):
        by = chart_top + i * (bar_h + gap)
        bw = int((val / max_val) * bar_area_w * 0.9) if max_val > 0 else 10
        c = colors[i % len(colors)]

        # ラベル
        sl = label[:8]
        d.text((al + 10, by + 5), sl, fill=(200, 200, 200), font=gf(22))

        # 棒
        d.rectangle([(chart_left, by), (chart_left + bw, by + bar_h)], fill=c)

        # 値
        vt = str(val)
        d.text((chart_left + bw + 8, by + 5), vt, fill=c, font=gf(22),
               stroke_width=1, stroke_fill=(0, 0, 0))


def draw_pie_chart(img, d, title, labels, values, colors=None,
                   cx=None, cy=None, radius=None):
    """円グラフ"""
    cx = cx or (TABLE_LEFT + TABLE_W // 2)
    cy = cy or (TABLE_TOP + TABLE_H // 2)
    radius = radius or min(TABLE_W, TABLE_H) // 2 - 40

    d.text((TABLE_LEFT + 15, TABLE_TOP + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    if not values:
        return

    default_colors = [
        (231, 76, 60), (52, 152, 219), (46, 204, 113),
        (241, 196, 15), (155, 89, 182), (230, 126, 34),
    ]
    if not colors:
        colors = default_colors

    total = sum(values)
    start = -90
    for i, (label, val) in enumerate(zip(labels, values)):
        pct = val / total if total > 0 else 0
        end = start + pct * 360
        c = colors[i % len(colors)]
        d.pieslice([(cx - radius, cy - radius), (cx + radius, cy + radius)],
                   start=start, end=end, fill=c, outline=(20, 20, 40), width=2)
        mid_angle = math.radians((start + end) / 2)
        lx = cx + int((radius + 30) * math.cos(mid_angle))
        ly = cy + int((radius + 30) * math.sin(mid_angle))
        d.text((lx - 30, ly - 10), f"{label} {val}", fill=c, font=gf(20),
               stroke_width=1, stroke_fill=(0, 0, 0))
        start = end


def draw_donut_chart(img, d, title, labels, values, colors=None,
                     cx=None, cy=None, outer_r=None, inner_r=None, center_text=""):
    """ドーナツチャート"""
    cx = cx or (TABLE_LEFT + TABLE_W // 2)
    cy = cy or (TABLE_TOP + TABLE_H // 2)
    outer_r = outer_r or min(TABLE_W, TABLE_H) // 2 - 40
    inner_r = inner_r or outer_r - 80

    d.text((TABLE_LEFT + 15, TABLE_TOP + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    default_colors = [
        (231, 76, 60), (52, 152, 219), (46, 204, 113),
        (241, 196, 15), (155, 89, 182), (230, 126, 34),
    ]
    if not colors:
        colors = default_colors

    total = sum(values) if values else 1
    start = -90
    for i, val in enumerate(values):
        pct = val / total
        end = start + pct * 360
        c = colors[i % len(colors)]
        d.pieslice([(cx - outer_r, cy - outer_r), (cx + outer_r, cy + outer_r)],
                   start=start, end=end, fill=c, outline=(20, 20, 40), width=2)
        start = end
    # 内側を抜く
    bg = (15, 15, 30)
    d.ellipse([(cx - inner_r, cy - inner_r), (cx + inner_r, cy + inner_r)], fill=bg)
    if center_text:
        bb = d.textbbox((0, 0), center_text, font=gf(32))
        tw = bb[2] - bb[0]
        d.text((cx - tw // 2, cy - 18), center_text, fill=(200, 200, 200), font=gf(32))


def draw_radar_chart(img, d, title, labels, values, color=(52, 152, 219),
                     cx=None, cy=None, radius=None):
    """レーダーチャート（蜘蛛の巣）"""
    cx = cx or (TABLE_LEFT + TABLE_W // 2)
    cy = cy or (TABLE_TOP + TABLE_H // 2 + 20)
    radius = radius or min(TABLE_W, TABLE_H) // 2 - 50

    d.text((TABLE_LEFT + 15, TABLE_TOP + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    n = len(labels)
    if n < 3:
        return

    # グリッド
    for ring in [0.2, 0.4, 0.6, 0.8, 1.0]:
        pts = []
        for i in range(n):
            angle = math.radians(-90 + 360 * i / n)
            px = cx + int(radius * ring * math.cos(angle))
            py = cy + int(radius * ring * math.sin(angle))
            pts.append((px, py))
        pts.append(pts[0])
        for j in range(len(pts) - 1):
            d.line([pts[j], pts[j + 1]], fill=(50, 50, 65), width=1)

    # 軸+ラベル
    for i in range(n):
        angle = math.radians(-90 + 360 * i / n)
        ex = cx + int(radius * math.cos(angle))
        ey = cy + int(radius * math.sin(angle))
        d.line([(cx, cy), (ex, ey)], fill=(50, 50, 65), width=1)
        lx = cx + int((radius + 25) * math.cos(angle))
        ly = cy + int((radius + 25) * math.sin(angle))
        d.text((lx - 20, ly - 10), labels[i][:5], fill=(200, 200, 200), font=gf(20))

    # データ
    max_val = max(values) if values else 1
    data_pts = []
    for i in range(n):
        angle = math.radians(-90 + 360 * i / n)
        ratio = values[i] / max_val if max_val > 0 else 0
        px = cx + int(radius * ratio * math.cos(angle))
        py = cy + int(radius * ratio * math.sin(angle))
        data_pts.append((px, py))

    for i in range(len(data_pts)):
        j = (i + 1) % len(data_pts)
        d.line([data_pts[i], data_pts[j]], fill=color, width=3)
    for px, py in data_pts:
        d.ellipse([(px - 5, py - 5), (px + 5, py + 5)], fill=color, outline=(255, 255, 255), width=2)


def draw_ranking(img, d, title, items,
                 area_left=None, area_top=None, area_w=None):
    """ランキング表示（メダル付き）: items = [(label, value_str), ...]"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W

    p = Image.new("RGBA", (aw, TABLE_H), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)
    d.text((al + 15, at + 8), title, fill=(255, 200, 100), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    medal_colors = [(255, 215, 0), (192, 192, 192), (205, 127, 50)]
    for i, (label, val) in enumerate(items[:8]):
        y = at + 55 + i * 60
        mc = medal_colors[i] if i < 3 else (60, 60, 80)
        d.ellipse([(al + 10, y), (al + 45, y + 35)], fill=mc)
        d.text((al + 20, y + 4), str(i + 1),
               fill=(0, 0, 0) if i < 3 else (200, 200, 200), font=gf(22))
        d.text((al + 55, y + 5), str(label)[:15], fill=(255, 255, 255), font=gf(26))
        vbb = d.textbbox((0, 0), str(val), font=gf(26))
        vw = vbb[2] - vbb[0]
        d.text((al + aw - 20 - vw, y + 5), str(val), fill=(46, 204, 113), font=gf(26),
               stroke_width=1, stroke_fill=(0, 0, 0))


def draw_number_cards(img, d, cards, area_left=None, area_top=None):
    """数字カード群: cards = [(label, number, unit, color), ...]"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    card_w = 230
    card_h = 160
    gap = 15

    for i, (label, num, unit, color) in enumerate(cards[:3]):
        cx = al + i * (card_w + gap)
        d.rounded_rectangle([(cx, at), (cx + card_w, at + card_h)], radius=12, fill=(30, 30, 50))
        d.rectangle([(cx, at), (cx + card_w, at + 5)], fill=color)
        d.text((cx + 12, at + 15), str(label)[:10], fill=(180, 180, 180), font=gf(22))
        d.text((cx + 15, at + 50), str(num), fill=color, font=gf(56),
               stroke_width=2, stroke_fill=(0, 0, 0))
        d.text((cx + 150, at + 75), str(unit)[:4], fill=color, font=gf(28))


def draw_before_after(img, d, title, items,
                      area_left=None, area_top=None, area_w=None, area_h=None):
    """ビフォーアフター矢印: items = [(label, before, after), ...]"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W
    ah = area_h or TABLE_H

    p = Image.new("RGBA", (aw, ah), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)
    d.text((al + 15, at + 8), title, fill=(255, 200, 100), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    for i, (label, bef, aft) in enumerate(items[:7]):
        y = at + 55 + i * 75
        d.text((al + 10, y + 12), str(label)[:8], fill=(200, 200, 200), font=gf(24))
        # Before
        d.rounded_rectangle([(al + 200, y + 2), (al + 340, y + 48)], radius=6, fill=(80, 30, 30))
        d.text((al + 210, y + 10), str(bef)[:6], fill=(255, 100, 100), font=gf(26))
        # Arrow
        d.text((al + 355, y + 8), "->", fill=(255, 255, 0), font=gf(28))
        # After
        d.rounded_rectangle([(al + 410, y + 2), (al + 550, y + 48)], radius=6, fill=(30, 80, 30))
        d.text((al + 420, y + 10), str(aft)[:6], fill=(100, 255, 100), font=gf(26))


def draw_progress_gauges(img, d, title, items,
                         area_left=None, area_top=None, area_w=None, area_h=None):
    """プログレスゲージ: items = [(label, value_0_100, color), ...]"""
    al = area_left or TABLE_LEFT
    at = area_top or TABLE_TOP
    aw = area_w or TABLE_W
    ah = area_h or TABLE_H

    p = Image.new("RGBA", (aw, ah), (0, 0, 0, int(0.88 * 255)))
    img.paste(p, (al, at), p)
    d.text((al + 15, at + 8), title, fill=(255, 255, 255), font=gf(30),
           stroke_width=1, stroke_fill=(0, 0, 0))

    for i, (label, val, color) in enumerate(items[:8]):
        y = at + 55 + i * 65
        d.text((al + 10, y + 2), str(label)[:10], fill=(200, 200, 200), font=gf(22))
        bar_left = al + 200
        bar_w = aw - 280
        d.rounded_rectangle([(bar_left, y + 5), (bar_left + bar_w, y + 35)], radius=12, fill=(40, 40, 55))
        fill_w = int(val / 100 * bar_w)
        d.rounded_rectangle([(bar_left, y + 5), (bar_left + fill_w, y + 35)], radius=12, fill=color)
        d.text((bar_left + fill_w + 8, y + 5), f"{val}%", fill=color, font=gf(22))


def draw_icon_stats(img, d, title, filled, total, icon_color=(231, 76, 60),
                    label_text="", area_left=None, area_top=None):
    """アイコン統計（人型x個中y個が...）"""
    al = area_left or TABLE_LEFT
    at = area_top or (TABLE_TOP + TABLE_H - 150)

    d.text((al, at), title, fill=(255, 200, 100), font=gf(28),
           stroke_width=1, stroke_fill=(0, 0, 0))

    for i in range(min(total, 15)):
        x = al + 10 + i * 50
        y = at + 45
        c = icon_color if i < filled else (50, 50, 65)
        d.ellipse([(x + 10, y), (x + 32, y + 22)], fill=c)
        d.rectangle([(x + 7, y + 25), (x + 35, y + 55)], fill=c)

    d.text((al + total * 50 + 30, at + 55), f"{filled}/{total}",
           fill=icon_color, font=gf(36), stroke_width=2, stroke_fill=(0, 0, 0))
    if label_text:
        d.text((al + total * 50 + 140, at + 60), label_text,
               fill=(200, 200, 200), font=gf(26))

