import os
import cv2
import numpy as np
from PIL import ImageDraw, ImageFont, Image
from sklearn.cluster import KMeans

# アップロードされたファイルの一時保存先
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)

def get_main_color_list_img(img_path):
    """
    画像の主要5色を抽出し、カラーブロック上部＋その下に色コード一覧を中央に表示する画像を生成。
    """
    # 画像読み込み & 色抽出
    cv2_img = cv2.imread(img_path)
    if cv2_img is None:
        raise ValueError(f"画像の読み込みに失敗しました: {img_path}")
    cv2_img = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
    cv2_img = cv2_img.reshape((cv2_img.shape[0] * cv2_img.shape[1], 3))

    cluster = KMeans(n_clusters=5, random_state=42)
    cluster.fit(X=cv2_img)
    colors = cluster.cluster_centers_.astype(int, copy=False)
    hex_rgb_list = []  # ← ここを追加

    # 基本設定
    IMG_SIZE = 80
    MARGIN = 10
    COLOR_BLOCK_WIDTH = IMG_SIZE * 5 + MARGIN * 2
    TEXT_LINES = 5  # 色の数だけ
    LINE_HEIGHT = 22

    # 結果画像のサイズ
    width = COLOR_BLOCK_WIDTH
    height = IMG_SIZE + MARGIN * 2 + TEXT_LINES * LINE_HEIGHT + 10
    # height = IMG_SIZE + MARGIN + TEXT_LINES * LINE_HEIGHT
    # height = IMG_SIZE + TEXT_LINES * LINE_HEIGHT + 10

    # 新しい画像キャンバス作成
    tiled_color_img = Image.new('RGB', (width, height), '#000000')
    draw = ImageDraw.Draw(tiled_color_img)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()

    # カラーブロックを描画
    for i, rgb in enumerate(colors):
        hex_code = '#%02x%02x%02x' % tuple(rgb)
        x = MARGIN + IMG_SIZE * i
        y = MARGIN
        color_img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), hex_code)
        tiled_color_img.paste(color_img, (x, y))

    # 説明テキストを下に中央表示
    text_y_start = IMG_SIZE + MARGIN + 10
    for i, rgb in enumerate(colors):
        hex_code = '#%02x%02x%02x' % tuple(rgb)
        rgb_str = f'({rgb[0]}, {rgb[1]}, {rgb[2]})'
        combined_text = f'{hex_code}  {rgb_str}'

        hex_rgb_list.append({'hex': hex_code, 'rgb': rgb_str})

        bbox = draw.textbbox((0, 0), combined_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = (width - text_width) // 2
        text_y = text_y_start + i * LINE_HEIGHT
        

        draw.text((text_x, text_y), combined_text, fill='white', font=font)

    return tiled_color_img, hex_rgb_list

def get_original_small_img(img_path, max_width=500):
    """
    元画像の小さくリサイズしたPILの画像を取得する。
    
    Parameters
    ----------
    img_path : str
        対象の画像のパス。
    max_width : int, optional
        最大幅。デフォルトは500px。
    
    Returns
    -------
    img : Image
        リサイズ後の画像。
        
    Raises
    ------
    FileNotFoundError
        画像ファイルが見つからない場合
    ValueError
        画像の読み込みに失敗した場合
    """
    try:
        img = Image.open(fp=img_path)
        
        # アスペクト比を保持しながらリサイズ
        if img.width > max_width:
            scale = max_width / img.width
            new_width = max_width
            new_height = int(img.height * scale)
            img = img.resize((new_width, new_height), Image.LANCZOS)
        
        return img
    except FileNotFoundError:
        raise FileNotFoundError(f"画像ファイルが見つかりません: {img_path}")
    except Exception as e:
        raise ValueError(f"画像処理中にエラーが発生しました: {str(e)}")

def process_image(img_path):
    """
    画像を処理して結果画像を生成する。
    
    Parameters
    ----------
    img_path : str
        対象の画像のパス。
    
    Returns
    -------
    result_img : Image
        処理結果の画像。
    """
    # 色の抽出
    # color_img = get_main_color_list_img(img_path)
    color_img, hex_rgb_list = get_main_color_list_img(img_path)
    
    # 元画像の縮小版
    small_img = get_original_small_img(img_path)
    
    MARGIN = 10
    # 結果画像の作成（元画像の下にカラーチャート）
    result_width = max(small_img.width, color_img.width)
    result_height = small_img.height + color_img.height + MARGIN
    
    
    result_img = Image.new('RGB', (result_width, result_height), '#000000')
    
    # 元画像を中央に配置
    x_offset = (result_width - small_img.width) // 2
    result_img.paste(small_img, (x_offset, 0))
    
    # カラーチャートを下に配置
    x_offset = (result_width - color_img.width) // 2
    result_img.paste(color_img, (x_offset, small_img.height + MARGIN))
    
    return result_img, hex_rgb_list



