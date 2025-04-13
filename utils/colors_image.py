import os
import cv2
import numpy as np
from PIL import ImageDraw, ImageFont, Image
from sklearn.cluster import KMeans
from collections import Counter

# アップロードされたファイルの一時保存先
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)

def get_main_color_list_img(img_path):
    """
    画像の主要7色を抽出し、使用頻度順にカラーブロック上部＋パーセンテージのみを表示する画像を生成。
    下部の色コード一覧テキストは表示しない。
    """
    # 画像読み込み & 色抽出
    cv2_img = cv2.imread(img_path)
    if cv2_img is None:
        raise ValueError(f"画像の読み込みに失敗しました: {img_path}")
    cv2_img = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
    
    # 元のピクセルデータを保存
    pixels = cv2_img.reshape(-1, 3)
    total_pixels = len(pixels)
    
    # クラスタリング
    cluster = KMeans(n_clusters=7, random_state=42)
    labels = cluster.fit_predict(X=pixels)
    colors = cluster.cluster_centers_.astype(int, copy=False)
    
    # クラスターごとのピクセル数をカウント
    label_counts = Counter(labels)
    
    # 使用頻度順の色情報を取得（明示的にソート）
    color_info = []
    for i in range(7):
        idx = i
        color = colors[idx]
        count = label_counts[idx]
        percentage = (count / total_pixels) * 100
        color_info.append((idx, color, count, percentage))
    
    # ピクセル数で降順ソート
    color_info.sort(key=lambda x: x[2], reverse=True)
    
    hex_rgb_list = []

    # 基本設定
    IMG_SIZE = 80
    MARGIN = 75
    COLOR_BLOCK_WIDTH = IMG_SIZE * 7 + MARGIN * 2
    
    # 結果画像のサイズ（テキスト表示部分を除去）
    width = COLOR_BLOCK_WIDTH
    height = IMG_SIZE + MARGIN * 2  # テキスト行分の高さを削除

    # 新しい画像キャンバス作成
    tiled_color_img = Image.new('RGB', (width, height), '#000000')
    draw = ImageDraw.Draw(tiled_color_img)

    try:
        font = ImageFont.truetype("msgothic.ttc", 50)  # Windowsの場合
    except IOError:
        font = ImageFont.load_default()
    
    # 使用頻度ラベルの追加
    draw.text((MARGIN, 35), "主要色（使用頻度順）:", fill='white', font=font)

    # カラーブロックを描画（使用頻度順）
    for i, (_, rgb, _, percentage) in enumerate(color_info):
        hex_code = '#%02x%02x%02x' % tuple(rgb)
        x = MARGIN + IMG_SIZE * i
        y = MARGIN + 20
        color_img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), hex_code)
        tiled_color_img.paste(color_img, (x, y))
        
        # 各色ブロックの上に使用頻度（%）を表示
        percentage_label = f"{percentage:.1f}%"
        bbox = draw.textbbox((0, 0), percentage_label, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = x + (IMG_SIZE - text_width) // 2
        draw.text((text_x, y - 30), percentage_label, fill='white', font=font)
        
        # データは収集するが表示はしない
        rgb_str = f'({rgb[0]}, {rgb[1]}, {rgb[2]})'
        percentage_str = f'{percentage:.1f}%'
        
        hex_rgb_list.append({
            'rank': i+1,
            'hex': hex_code, 
            'rgb': rgb_str,
            'percentage': percentage_str
        })

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



