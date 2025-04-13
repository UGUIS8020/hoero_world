from PIL import ImageFont
import os
import re

def sanitize_filename(filename, max_length=100):
    """
    英数字と記号（-_ .）以外を削除した安全なファイル名を生成（日本語含む全角文字を除去）
    """
    filename = os.path.basename(filename)
    name, ext = os.path.splitext(filename)

    # 英数字、アンダースコア、ハイフン、ドットのみ許可
    name = re.sub(r'[^A-Za-z0-9_.-]', '', name)

    if not name:
        name = "unnamed_file"

    # 長さ制限（拡張子含む）
    max_name_length = max_length - len(ext)
    name = name[:max_name_length]

    return name + ext

def get_font(font_size=18):
    font_paths = [
        "C:/Windows/Fonts/msgothic.ttc",  # Windows
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",  # Linux代替
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, font_size)
    return ImageFont.load_default()