from botocore.exceptions import ClientError
import time
import boto3
import zipfile
import shutil
import os
import cv2
from datetime import datetime
import time
from PIL import ImageDraw, ImageFont, Image
from sklearn.cluster import KMeans
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import tempfile
import re
import uuid
import unicodedata
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# DynamoDBの初期化
dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

counter_table = dynamodb.Table('Meziro-Counters')  # カウンター用のテーブル

def get_next_sequence_number():
    try:
        response = counter_table.update_item(
            Key={'counter_name': 'meziro_upload'},
            UpdateExpression='SET #val = if_not_exists(#val, :start) + :incr',
            ExpressionAttributeNames={'#val': 'counter_value'},
            ExpressionAttributeValues={':incr': 1, ':start': 0},
            ReturnValues='UPDATED_NEW'
        )
        return int(response['Attributes']['counter_value']), None  # ← 2つ返す
    except ClientError as e:
        fallback_id = int(time.time())
        warning_msg = f"[WARNING] DynamoDB失敗。代替IDとして {fallback_id} を使用します: {e}"
        print(warning_msg)
        return fallback_id, warning_msg  # ← 2つ返す
        
class ZipHandler:
    def __init__(self, upload_folder='uploads', temp_zip_folder='temp_zips'):
        self.UPLOAD_FOLDER = upload_folder
        self.TEMP_ZIP_FOLDER = temp_zip_folder
        
        # ディレクトリの作成
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(self.TEMP_ZIP_FOLDER, exist_ok=True)   

    def process_files(self, files, has_folder_structure=False):
        """ファイルを処理（常にZIPファイルを作成）"""
        if not files:
            raise ValueError('ファイルが選択されていません')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_dir = os.path.join(self.TEMP_ZIP_FOLDER, timestamp)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            print(f"Creating ZIP file {'(folder structure)' if has_folder_structure else '(all files)'}")
            zip_path = os.path.join(self.TEMP_ZIP_FOLDER, f'compressed_{timestamp}.zip')
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in files:
                    print(f"Processing file: {file.filename}")
                    filename = sanitize_filename(file.filename)

                    
                    
                    # フォルダ構造がある場合はパスを保持
                    if has_folder_structure and hasattr(file, 'webkitRelativePath') and file.webkitRelativePath:
                        arc_name = file.webkitRelativePath
                    elif has_folder_structure and hasattr(file, 'relativePath') and file.relativePath:
                        arc_name = file.relativePath
                    else:
                        # 構造がない場合は単にファイル名を使用
                        arc_name = filename
                        
                    temp_path = os.path.join(temp_dir, filename)
                    file.save(temp_path)
                    zipf.write(temp_path, arcname=arc_name)
            
            # 一時ディレクトリを削除
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            return zip_path, None
                
        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
    def process_files_no_zip(self, files):
        if not files:
            raise ValueError('ファイルが選択されていません')

        temp_dir = tempfile.mkdtemp()
        file_paths = []

        for file in files:
            filename = secure_filename(file.filename)
            save_path = os.path.join(temp_dir, filename)
            file.save(save_path)
            file_paths.append(save_path)

        return file_paths, temp_dir

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

    font = get_font(18)   
    
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

def sanitize_filename(filename, max_length=100):
    # パスの末尾だけを抽出
    filename = os.path.basename(filename)

    # Unicode正規化（日本語や特殊記号対応）
    filename = unicodedata.normalize('NFKD', filename)

    # 拡張子分離
    name, ext = os.path.splitext(filename)

    # 拡張子チェック
    if not ext or not ext.startswith("."):
        ext = ".bin"

    # 英数字と一部記号だけ残す
    safe_name = re.sub(r'[^A-Za-z0-9_.-]', '', name)

    # 名前部分が空になったらUUIDで補完
    if not safe_name:
        safe_name = uuid.uuid4().hex[:12]

    # 長さ制限（拡張子込み）
    safe_name = safe_name[:max_length - len(ext)]

    return safe_name + ext

def get_font(font_size=18):
    font_paths = [
        "C:/Windows/Fonts/msgothic.ttc",  # Windows
        "/usr/share/fonts/ipa-gothic-fonts/ipag.ttf",  # ← 追加済みの日本語フォント
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # fallback
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, font_size)
    return ImageFont.load_default()

import os
import time

def cleanup_temp_files(app_root_path, days_old=7, include_system_temp=False):
    """
    アプリ内の一時ディレクトリおよび（任意で）OS標準一時ディレクトリをクリーンアップする
    """
    import tempfile

    directories_to_clean = [
        os.path.join(app_root_path, 'temp_downloads'),
        os.path.join(app_root_path, 'temp_zips'),
        os.path.join(app_root_path, 'temp_uploads'),  # 追加対象
    ]
    
    total_files_deleted = 0

    for temp_dir in directories_to_clean:
        total_files_deleted += _cleanup_dir(temp_dir, days_old)

    if include_system_temp:
        system_temp_dir = tempfile.gettempdir()
        total_files_deleted += _cleanup_dir(system_temp_dir, days_old, filter_exts={'.stl', '.glb', '.zip'})

    return total_files_deleted


def _cleanup_dir(temp_dir, days_old, filter_exts=None):
    files_deleted = 0
    if not os.path.exists(temp_dir):
        logger.info(f"ディレクトリが存在しません: {temp_dir}")
        return 0

    logger.info(f"クリーンアップ中: {temp_dir}")

    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        try:
            if os.path.isfile(file_path):
                if filter_exts and not any(filename.endswith(ext) for ext in filter_exts):
                    continue
                if time.time() - os.path.getmtime(file_path) > days_old * 86400:
                    os.remove(file_path)
                    files_deleted += 1
            elif os.path.isdir(file_path):
                if time.time() - os.path.getmtime(file_path) > days_old * 86400:
                    shutil.rmtree(file_path)
                    files_deleted += 1
        except Exception as e:
            logger.error(f"削除失敗: {file_path} ({e})")

    logger.info(f"{temp_dir} 内の削除数: {files_deleted}")
    return files_deleted

def setup_scheduled_cleanup(app):
    """
    アプリケーションに定期的なクリーンアップタスクを設定する
    
    Parameters:
    -----------
    app : Flask application
        Flaskアプリケーションインスタンス
    """
    scheduler = BackgroundScheduler()
    
    # 毎日午前3時に実行するスケジューラを設定
    @scheduler.scheduled_job('cron', hour=3, minute=0)
    def scheduled_cleanup():
        with app.app_context():
            app_root_path = app.root_path
            logger.info("定期的なクリーンアップタスクを開始します")
            deleted_count = cleanup_temp_files(app_root_path)
            logger.info(f"定期的なクリーンアップタスク完了: 合計 {deleted_count} ファイルを削除しました")
    
    # before_first_requestの代わりに直接実行
    # アプリケーション初期化時に一度だけ実行
    with app.app_context():
        logger.info("初期クリーンアップタスクを実行中...")
        deleted_count = cleanup_temp_files(app.root_path)
        logger.info(f"初期クリーンアップタスク完了: 合計 {deleted_count} ファイルを削除しました")
    
    # スケジューラを開始
    scheduler.start()
    logger.info("定期的なクリーンアップスケジューラを開始しました")
    
    # アプリケーション終了時にスケジューラを停止
    import atexit
    atexit.register(lambda: scheduler.shutdown())


