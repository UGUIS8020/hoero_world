import io
import json
import os
import base64
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, time, timezone
from urllib.parse import unquote
import re
import math

# サードパーティライブラリ
import boto3
import imageio_ffmpeg as ffmpeg
import requests
from boto3.dynamodb.conditions import Attr
from dotenv import load_dotenv
from moviepy import VideoFileClip
from PIL import Image
from pytz import timezone as pytz_timezone

# Flask関連
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required
from flask_mail import Mail, Message

# ローカルモジュール
from extensions import db, mail
from models.dynamodb_category import list_blog_categories_all  # ← 変更
from models.dynamodb_inquiry import InquiryDDB
from models.main import (
    BlogCategoryForm,
    BlogPostForm,
    BlogSearchForm,
    InquiryForm,
    UpdateCategoryForm,
)
from types import SimpleNamespace
from utils.blog_dynamo import (
    create_blog_post_in_dynamo,
    delete_post_by_id,
    get_post_by_id,
    list_recent_posts,
    update_post_fields,
    list_posts_by_category,
    list_all_posts,
    paginate_posts,
)
from utils.common_utils import (
    ZipHandler,
    cleanup_temp_files,
    get_next_sequence_number,
    process_image,
    sanitize_filename,
)
from views.news.autotransplant_news import ai_collect_news
from utils.stl_dynamo import list_stl_posts, create_stl_post, get_stl_post_by_id


JST = pytz_timezone('Asia/Tokyo')
current_time = datetime.now(JST)

bp = Blueprint('main', __name__, template_folder='hoero_world/templates', static_folder='hoero_world/static')

load_dotenv()

# AWSクライアントの初期化
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

PREFIX = 'meziro/'
BUCKET_NAME = os.getenv("BUCKET_NAME")



# ZIPハンドラーのインスタンス作成
zip_handler_instance = ZipHandler()  # インスタンスを作成

from urllib.parse import urlparse, parse_qs

def extract_youtube_id(url: str | None) -> str:
    if not url:
        return ""
    u = url.strip()

    # youtu.be/VIDEOID
    if "youtu.be/" in u:
        return u.split("youtu.be/")[1].split("?")[0].split("/")[0]

    p = urlparse(u)
    host = (p.netloc or "").lower()
    path = (p.path or "")

    if "youtube.com" in host:
        # /shorts/VIDEOID
        if "/shorts/" in path:
            return path.split("/shorts/")[1].split("?")[0].split("/")[0]

        # /embed/VIDEOID
        if "/embed/" in path:
            return path.split("/embed/")[1].split("?")[0].split("/")[0]

        # watch?v=VIDEOID
        qs = parse_qs(p.query)
        if qs.get("v"):
            return qs["v"][0]

    return ""


@bp.route('/')
def index():
    form = BlogSearchForm()
    page = request.args.get('page', 1, type=int)

    # blog（必要なら）
    all_posts = list_all_posts(limit=1000)
    blog_posts = paginate_posts(all_posts, page=page, per_page=10)
    blog_categories = list_blog_categories_all()

    # =========================
    # ★トップに出す STL掲示板（最新2件）
    #   サムネ優先順位: YouTube → STL → 画像
    # =========================
    top_stl_posts = []
    try:
        # ★ ユーザーテーブルを取得
        users_table = current_app.config.get("HOERO_USERS_TABLE")
        
        stl_items = list_stl_posts(limit=2)
        for it in stl_items:
            pid = str(it.get("post_id", "")).strip()
            if not pid:
                continue

            # ★ 著者情報を取得
            user_id = str(it.get("user_id", ""))
            author_name = "Unknown"
            if users_table and user_id:
                try:
                    user_response = users_table.get_item(Key={"user_id": user_id})
                    user_data = user_response.get("Item", {})
                    if user_data:
                        author_name = user_data.get("display_name", "Unknown")
                except Exception as e:
                    current_app.logger.warning(f"ユーザー情報取得エラー (user_id: {user_id}): {e}")

            # --- YouTube ---
            youtube_url = (it.get("youtube_url", "") or it.get("youtube_embed_url", "") or "").strip()
            youtube_id = (it.get("youtube_id", "") or extract_youtube_id(youtube_url) or "").strip()

            # --- STL(GLB) ---
            stl_key = (it.get("stl_file_path") or "").lstrip("/")
            stl_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{stl_key}" if stl_key else ""

            # --- Image ---
            image_key = (it.get("image_file_path") or "").lstrip("/")
            image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{image_key}" if image_key else ""

            top_stl_posts.append(
                SimpleNamespace(
                    post_id=pid,
                    title=it.get("title", ""),
                    content=it.get("content", ""),
                    created_at=(it.get("created_at") or "")[:10],
                    author_name=author_name,  # ★ 取得した著者名を使用

                    # STL
                    stl_key=stl_key,
                    stl_url=stl_url,
                    stl_filename=it.get("stl_filename", ""),

                    # YouTube
                    youtube_url=youtube_url,
                    youtube_id=youtube_id,

                    # Image
                    image_file_path=image_key,
                    image_url=image_url,
                )
            )
    except Exception as e:
        current_app.logger.warning("load top stl posts failed: %s", e)

    # （サイドバー用：最新5件）
    recent_stl_posts = []
    try:
        stl_recent_items = list_stl_posts(limit=5)
        for it in stl_recent_items:
            pid = str(it.get("post_id", "")).strip()
            if not pid:
                continue

            # サイドバーは必要最低限でOK（タイトル+リンク用IDだけでもOK）
            recent_stl_posts.append(
                SimpleNamespace(
                    post_id=pid,
                    title=it.get("title", ""),
                )
            )
    except Exception as e:
        current_app.logger.warning("load recent stl posts failed: %s", e)

    # autotransplant_headlines はそのまま
    autotransplant_headlines = []
    try:
        from .news.autotransplant_news import dental_query_items
        all_items = []
        for kind in ["research", "news", "case"]:
            items, _ = dental_query_items(kind=kind, lang="ja", limit=10)
            all_items.extend(items)

        all_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        autotransplant_headlines = [
            {
                "title": it.get("title"),
                "url": it.get("url"),
                "published_at": (it.get("published_at") or "")[:10],
                "ai_headline": it.get("ai_headline"),
                "ai_summary": it.get("ai_summary"),
                "headline_ja": it.get("ai_headline"),
            }
            for it in all_items[:5]
            if it.get("title") and it.get("url")
        ]
    except Exception as e:
        current_app.logger.warning("load autotransplant headlines failed: %s", e)

    return render_template(
        'main/index.html',
        blog_posts=blog_posts,
        blog_categories=blog_categories,
        form=form,
        top_stl_posts=top_stl_posts,
        recent_stl_posts=recent_stl_posts,
        autotransplant_headlines=autotransplant_headlines,
    )

@bp.route('/category_maintenance', methods=['GET', 'POST'])
@login_required
def category_maintenance():
    if not current_user.is_administrator:
        abort(403)

    page = request.args.get('page', 1, type=int)
    per_page = 10

    # DynamoDB から全カテゴリ取得
    items = list_blog_categories_all()
    total = len(items)

    # ページング（単純に Python でスライス）
    start = (page - 1) * per_page
    end = start + per_page
    page_items_raw = items[start:end]

    # テンプレートで今まで通り blog_category.id / blog_category.name / blog_category.category
    page_items = [
        SimpleNamespace(
            id=int(it["category_id"]),
            name=it.get("name", ""),
            category=it.get("name", ""),
        )
        for it in page_items_raw
    ]

    blog_categories = SimplePagination(
        items=page_items,
        page=page,
        per_page=per_page,
        total=total,
    )

    form = BlogCategoryForm()
    if form.validate_on_submit():
        # RDS ではなく Dynamo に保存
        new_id = create_blog_category_in_dynamo(form.category.data)
        print(f"Dynamo にカテゴリ追加: id={new_id}, name={form.category.data}")
        flash('ブログカテゴリが追加されました', 'success')
        return redirect(url_for('main.category_maintenance'))
    elif form.errors:
        form.category.data = ""
        flash(form.errors['category'][0], 'danger')

    return render_template(
        'main/category_maintenance.html',
        blog_categories=blog_categories,
        form=form
    )

@bp.route('/<int:blog_category_id>/blog_category', methods=['GET', 'POST'])
@login_required
def blog_category(blog_category_id):
    if not current_user.is_administrator:
        abort(403)

    item = get_blog_category_in_dynamo(blog_category_id)
    if not item:
        abort(404)

    form = UpdateCategoryForm(blog_category_id)

    if form.validate_on_submit():
        update_blog_category_in_dynamo(blog_category_id, form.category.data)
        flash('ブログカテゴリが更新されました', 'success')
        return redirect(url_for('main.category_maintenance'))

    elif request.method == 'GET':
        form.category.data = item.get("name", "")

    return render_template('main/blog_category.html', form=form)

@bp.route('/<int:blog_category_id>/delete_category', methods=['GET', 'POST'])
@login_required
def delete_category(blog_category_id):
    if not current_user.is_administrator:
        abort(403)

    # あるかどうかチェック
    item = get_blog_category_in_dynamo(blog_category_id)
    if not item:
        abort(404)

    delete_blog_category_in_dynamo(blog_category_id)
    flash('ブログカテゴリが削除されました', 'success')
    return redirect(url_for('main.category_maintenance'))

def get_dynamo_user_id_by_email(email: str) -> str | None:
    """
    hoero-users テーブルから email に一致する user_id(UUID) を1件返す。
    見つからなければ None。
    """
    table = current_app.config["HOERO_USERS_TABLE"]  # 例: app.config で設定しておく
    resp = table.scan(
        FilterExpression=Attr("email").eq(email),
        ProjectionExpression="user_id",
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return items[0]["user_id"]

@bp.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    form = BlogPostForm()
    if form.validate_on_submit():
        try:
            print("フォーム検証成功")
            print(f"タイトル: {form.title.data}")
            print(f"カテゴリー: {form.category.data}")
            print(f"RDSユーザーID: {current_user.id}")
            print(f"メール: {current_user.email}")

            dynamo_user_id = get_dynamo_user_id_by_email(current_user.email)
            print(f"Dynamo user_id: {dynamo_user_id}")

            if not dynamo_user_id:
                raise RuntimeError("hoero-users に対応するユーザーが見つかりません")

            # 画像アップロード
            if form.picture.data:
                pic = add_featured_image(form.picture.data)
                print(f"画像保存: {pic}")
            else:
                pic = ''
                print("画像なし")

            # 動画アップロード（追加）
            if form.video.data:
                video = add_featured_video(form.video.data)
                print(f"動画保存: {video}")
            else:
                video = ''
                print("動画なし")

            author_name = current_user.display_name

            # 追加：YouTube URL（未入力なら空文字）
            youtube_url = (form.youtube_url.data or "").strip()
            print("YouTube URL:", youtube_url)

            # ★ カテゴリが存在しない／未設定でもOKにする
            if form.category.choices:
                category_id = form.category.data
                category_name_map = dict(form.category.choices)
                category_name = category_name_map.get(category_id, "")
            else:
                category_id = None
                category_name = ""

            post_id = create_blog_post_in_dynamo(
                user_id=dynamo_user_id,
                title=form.title.data,
                text=form.text.data,
                summary=form.summary.data or "",
                featured_image=pic,
                featured_video=video,
                youtube_url=youtube_url,          # ← 追加
                author_name=author_name,
                category_id=category_id,
                category_name=category_name,
            )
            print(f"DynamoDB に投稿作成, post_id={post_id}")

            flash('ブログ投稿が作成されました', 'success')
            return redirect(url_for('main.blog_post', blog_post_id=post_id))

        except Exception as e:
            print(f"エラー発生: {e}")
            flash(f'エラーが発生しました: {str(e)}', 'danger')
    else:
        print("フォーム検証失敗")
        print(f"エラー: {form.errors}")

    return render_template('main/create_post.html', form=form)


def _blog_categories_table():
    return current_app.config["BLOG_CATEGORIES_TABLE"]  # app.config で設定する

def list_blog_categories_all():
    """DynamoDB からカテゴリを全件取得して ID 昇順でソート"""
    table = _blog_categories_table()
    resp = table.scan()
    items = resp.get("Items", [])

    def _id(x):
        try:
            return int(x.get("category_id", 0))
        except Exception:
            return 0

    items.sort(key=_id)
    return items

def create_blog_category_in_dynamo(name: str) -> int:
    """新しいカテゴリを作成して category_id(int) を返す"""
    items = list_blog_categories_all()
    if items:
        max_id = max(int(i.get("category_id", 0)) for i in items)
        new_id = max_id + 1
    else:
        new_id = 1

    table = _blog_categories_table()
    table.put_item(
        Item={
            "category_id": str(new_id),
            "name": name,
        }
    )
    return new_id

def get_blog_category_in_dynamo(category_id: int):
    table = _blog_categories_table()
    resp = table.get_item(Key={"category_id": str(category_id)})
    return resp.get("Item")

def update_blog_category_in_dynamo(category_id: int, new_name: str):
    table = _blog_categories_table()
    table.update_item(
        Key={"category_id": str(category_id)},
        UpdateExpression="SET #nm = :n",
        ExpressionAttributeNames={"#nm": "name"},
        ExpressionAttributeValues={":n": new_name},
    )

def delete_blog_category_in_dynamo(category_id: int):
    table = _blog_categories_table()
    table.delete_item(Key={"category_id": str(category_id)})


class SimplePagination:
    """SQLAlchemy の paginate に似せた簡易オブジェクト"""
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total

    @property
    def pages(self):
        return max(1, math.ceil(self.total / self.per_page)) if self.per_page else 1

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1

    @property
    def next_num(self):
        return self.page + 1

@bp.route("/blog_maintenance")
@login_required
def blog_maintenance():
    posts = list_recent_posts(limit=50)   # DynamoDB から取得
    return render_template("main/blog_maintenance.html", blog_posts=posts)

# ========================================
# 一般ユーザー向けブログ表示ページ
# ========================================

@bp.route("/blog")
def blog_list():
    """ブログ一覧ページ（一般公開）"""
    page = request.args.get("page", 1, type=int)
    per_page = 12
    category_id = request.args.get("category")
    
    # 全投稿を取得
    all_posts = list_recent_posts(limit=1000)
    
    # 公開フラグでフィルタリング
    all_posts = [p for p in all_posts if p.get("is_published", True)]
    
    # カテゴリでフィルタリング
    if category_id:
        all_posts = [p for p in all_posts if p.get("category_id") == str(category_id)]
    
    # ページネーション処理
    total = len(all_posts)
    start = (page - 1) * per_page
    end = start + per_page
    posts_raw = all_posts[start:end]
    
    # ★ index と同じように SimpleNamespace に変換 + youtube_id を生成
    blog_posts = []
    for it in posts_raw:
        try:
            pid = int(it.get("post_id"))
        except Exception:
            continue
        
        # YouTube ID を抽出
        youtube_url = it.get("youtube_url", "") or it.get("youtube_embed_url", "")
        yid = it.get("youtube_id", "") or extract_youtube_id(youtube_url)
        
        blog_posts.append(
            SimpleNamespace(
                post_id=pid,
                title=it.get("title", ""),
                summary=it.get("summary", ""),
                text=it.get("text", ""),
                date=it.get("date", ""),
                author_name=it.get("author_name", ""),
                category_name=it.get("category_name", ""),
                
                featured_image=it.get("featured_image", ""),
                featured_video=it.get("featured_video", ""),
                featured_thumbnail=it.get("featured_thumbnail", ""),
                
                youtube_id=yid,
                youtube_embed_url=it.get("youtube_embed_url", ""),
                youtube_url=it.get("youtube_url", ""),
            )
        )
    
    pagination = SimplePagination(
        items=blog_posts,
        page=page,
        per_page=per_page,
        total=total
    )
    
    # カテゴリ一覧を取得
    categories = list_all_blog_categories()
    
    return render_template(
        "main/blog_list.html",
        blog_posts=blog_posts,
        pagination=pagination,
        categories=categories,
        current_category=category_id
    )


# ========================================
# ヘルパー関数（必要に応じて追加）
# ========================================

def list_all_blog_categories():
    """全カテゴリを取得"""
    table = _blog_categories_table()
    resp = table.scan()
    items = resp.get("Items", [])
    # category_id でソート
    return sorted(items, key=lambda x: int(x.get("category_id", 0)))


def get_blog_post_in_dynamo(post_id: str):
    """単一の投稿を取得"""
    table = _blog_posts_table()  # この関数が既にあると仮定
    resp = table.get_item(Key={"post_id": post_id})
    return resp.get("Item")


@bp.route('/colors', methods=['GET', 'POST'])
def colors():
    if request.method == 'POST':
        return colors_image_upload()
    return render_template('main/colors.html')

@bp.route('/raiden')
def raiden():    
    return render_template('main/raiden.html')

def save_resized_upload(file, save_path, max_width=1500):
    """
    アップロードされた画像を最大幅でリサイズして保存。
    """
    img = Image.open(file)
    if img.width > max_width:
        scale = max_width / img.width
        new_height = int(img.height * scale)
        img = img.resize((max_width, new_height), Image.LANCZOS)
    img.save(save_path)
    print(f"画像保存成功: {save_path}")  # ← これを追加しておくと確認しやすい

@bp.route('/colors_image_upload', methods=['GET', 'POST'])
def colors_image_upload():
    if 'file' not in request.files:
        return 'ファイルがありません', 400

    file = request.files['file']
    if file.filename == '':
        return 'ファイルが選択されていません', 400

    try:
        # ファイルの保存先（リサイズ保存）
        safe_filename = sanitize_filename(file.filename)
        
        filename = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)       

        # filename = os.path.join(current_app.config['UPLOAD_FOLDER'], file.filename)
        save_resized_upload(file, filename)  # 小さくしてローカル保存

        # リサイズ後の画像をS3にアップロード
        with open(filename, "rb") as f:
            s3.upload_fileobj(
                f,
                os.getenv('BUCKET_NAME'),
                # f'analysis_original/{file.filename}',
                f'analysis_original/{safe_filename}',
                ExtraArgs={'ContentType': 'image/png'}
            )

        # 処理実行
        # result_img = process_image(filename)
        result_img, color_data = process_image(filename)

        # 結果画像をBase64でテンプレートへ
        buffered = io.BytesIO()
        result_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        # ローカルファイル削除
        if os.path.exists(filename):
            os.remove(filename)

        return render_template('main/result.html', image_data=img_str, color_data=color_data)

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        if os.path.exists(filename):
            os.remove(filename)
        return str(e), 500

@bp.route('/ugu_box')
def ugu_box():
    # page = request.args.get('page', 1, type=int)
    # blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    s3_files = []
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix='ugu_box/')
        # LastModifiedでソートするためにリストに変換
        contents = response.get('Contents', [])
        # LastModifiedの降順（新しい順）でソート
        contents.sort(key=lambda x: x['LastModified'], reverse=True)
        
        for obj in contents:
            key = obj['Key']
            filename = os.path.basename(key)
            if filename:  # フォルダ名を除外
                # 署名付きURLを生成（有効期限1時間）
                file_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': BUCKET_NAME, 'Key': key},
                    ExpiresIn=604800  # 1週間（604800秒）有効
                )
                s3_files.append({
                    'filename': filename, 
                    'url': file_url,
                    'last_modified': obj['LastModified'].astimezone(JST).strftime('%Y-%m-%d %H:%M')   # 日時情報も追加
                })        

    except Exception as e:
        flash(f"S3ファイル一覧取得中にエラー: {str(e)}", "error")

    return render_template(
        'main/ugu_box.html')

zip_handler = ZipHandler()

import traceback  # ← これをファイルの先頭で追加

@bp.route('/ugu_box/upload', methods=['POST'])
def ugu_box_upload():
    files = request.files.getlist('files[]')
    
    if not files:
        return jsonify({"status": "error", "message": "ファイルが選択されていません"}), 400

    try:
        result, temp_dir = zip_handler.process_files_no_zip(files)

        uploaded_keys = []
        for file_path in result:
            filename = os.path.basename(file_path)
            s3_key = f"ugu_box/{filename}"
            with open(file_path, 'rb') as f:
                s3.upload_fileobj(f, BUCKET_NAME, s3_key)
            uploaded_keys.append(s3_key)

        # 一時ディレクトリ削除
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

        # zipファイル一覧を返す
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix='ugu_box/')
        zip_files = [
            os.path.basename(obj['Key'])
            for obj in response.get('Contents', [])
            if obj['Key'].endswith('.zip')
        ]

        return jsonify({
            "status": "success",
            "message": "アップロード完了",
            "zip_files": zip_files
        })

    except Exception as e:
        traceback.print_exc()  # ← ここに追加すると、ターミナルに詳細なエラー情報が表示されます
        return jsonify({"status": "error", "message": str(e)}), 500

    
@bp.route('/ugu_box/download/<filename>')
@login_required
def ugu_box_download(filename):
    try:
        # S3からファイルをダウンロード
        s3_key = f"ugu_box/{filename}"
        
        # 一時ファイルを作成
        temp_dir = os.path.join(current_app.root_path, 'temp_downloads')
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, filename)
        
        # S3からファイルをダウンロード
        s3.download_file(BUCKET_NAME, s3_key, temp_file_path)
        
        # ファイルを送信
        return send_from_directory(
            temp_dir,
            filename,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f"ファイルのダウンロード中にエラーが発生しました: {str(e)}", "error")
        return redirect(url_for('main.ugu_box'))  

@bp.route('/ugu_box/delete', methods=['POST'])
def ugu_box_delete():
    data = request.get_json()
    filename = data.get('filename')
    s3_key = f"ugu_box/{filename}"

    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@bp.route("/ugu_box/files")
def list_uploaded_files():
    objects = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix="ugu_box/")

    files = []
    for obj in objects.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue

        jst_time = obj["LastModified"].astimezone(JST)

        file_info = {
            "filename": os.path.basename(key),
            "size": obj["Size"],
            "last_modified": jst_time.strftime("%Y-%m-%d %H:%M"),
            "last_modified_dt": jst_time,  # ソートなどに使用するため保持
            "url": s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": BUCKET_NAME, "Key": key},
                ExpiresIn=3600,
            )
        }
        files.append(file_info)

    # ✅ 並び替え（新しいファイルが上）
    files.sort(key=lambda x: x["last_modified_dt"], reverse=True)

    # ✅ 並び替えに使った項目を削除
    for f in files:
        del f["last_modified_dt"]

    return jsonify(files)

@bp.route('/meziro')
def meziro():
    s3_files = []
    try:
        # ページング対応で 'meziro/' 配下を全取得
        kwargs = dict(Bucket=BUCKET_NAME, Prefix='meziro/', MaxKeys=1000)
        while True:
            resp = s3.list_objects_v2(**kwargs)
            for obj in resp.get('Contents', []):
                key = obj['Key']
                filename = os.path.basename(key)
                if not filename:  # フォルダ疑似キーはスキップ
                    continue

                # completed タグ取得（失敗時は False）
                completed = False
                try:
                    tag_resp = s3.get_object_tagging(Bucket=BUCKET_NAME, Key=key)
                    tags = {t['Key']: t['Value'] for t in tag_resp.get('TagSet', [])}
                    completed = (tags.get('completed') == 'true')
                except Exception as e:
                    # 権限/一時エラーはログだけ残して未完了扱い
                    current_app.logger.warning(f"[MEZIRO] get_object_tagging failed key={key}: {e}")

                # 署名付きURL（必要なら）
                file_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': BUCKET_NAME, 'Key': key},
                    ExpiresIn=604800  # 7日
                )

                s3_files.append({
                    'key': key,
                    'filename': filename,
                    'last_modified_dt': obj['LastModified'],  # まずはdatetimeで保持（後で整形）
                    'url': file_url,
                    'completed': completed,
                })

            if resp.get('IsTruncated'):
                kwargs['ContinuationToken'] = resp.get('NextContinuationToken')
            else:
                break

        # 新しい順に並べ替え → 表示用にJST文字列へ整形
        s3_files.sort(key=lambda x: x['last_modified_dt'], reverse=True)
        for f in s3_files:
            f['last_modified'] = f['last_modified_dt'].astimezone(JST).strftime('%Y-%m-%d %H:%M')
            del f['last_modified_dt']

    except Exception as e:
        flash(f"S3ファイル一覧取得中にエラー: {str(e)}", "error")

    return render_template('main/meziro.html', s3_files=s3_files)

@bp.route('/meziro_upload_index', methods=['GET'])
def meziro_upload_index():
    return render_template('main/meziro_upload_index.html')

@bp.route('/meziro_upload', methods=['POST'])
def meziro_upload():
    log = current_app.logger
    log.info("=== /meziro_upload START === ip=%s ua=%s", request.remote_addr, request.headers.get("User-Agent"))

    # 受信フォーム値
    business_name    = request.form.get('businessName', '')
    user_name        = request.form.get('userName', '')
    user_email       = request.form.get('userEmail', '')
    patient_name     = request.form.get('patientName', '') or request.form.get('PatientName', '')  # どちらか来る想定なら保険
    appointment_date = request.form.get('appointmentDate', '')
    appointment_hour = request.form.get('appointmentHour', '')
    project_type     = request.form.get('projectType', '')
    crown_type       = request.form.get('crown_type', '')
    teeth_raw        = request.form.get('teeth', '[]')
    shade            = request.form.get('shade', '')
    message          = request.form.get('userMessage', '')

    # teeth のJSONパース
    try:
        teeth = json.loads(teeth_raw)
        if not isinstance(teeth, list):
            raise ValueError("teeth is not list")
    except Exception as e:
        log.warning("teeth のJSONパース失敗: raw=%s err=%s", teeth_raw[:200], e)
        teeth = []

    # フォーム要約ログ（個人情報は最低限に）
    log.info(
        "Form summary: business=%s, user=%s, email=%s, project=%s, crown=%s, shade=%s, teeth_count=%d",
        business_name, user_name, user_email, project_type, crown_type, shade, len(teeth)
    )

    # 必須チェック（warning で記録）
    if not message:
        log.warning("必須エラー: message が空")
        return jsonify({'error': 'メッセージが入力されていません'}), 400
    if not business_name:
        log.warning("必須エラー: business_name が空")
        return jsonify({'error': '事業者名が入力されていません'}), 400
    if not user_name:
        log.warning("必須エラー: user_name が空")
        return jsonify({'error': '送信者名が入力されていません'}), 400
    if not user_email:
        log.warning("必須エラー: user_email が空")
        return jsonify({'error': 'メールアドレスが入力されていません'}), 400
    if not project_type:
        log.warning("必須エラー: project_type が空")
        return jsonify({'error': '製作物が選択されていません'}), 400

    if 'files[]' not in request.files:
        log.warning("必須エラー: files[] フィールドが存在しない")
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    files = request.files.getlist('files[]')
    if not files or files[0].filename == '':
        log.warning("必須エラー: files[] が空またはファイル名が空")
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    log.info("受信ファイル数: %d (例: %s)", len(files), files[0].filename)

    uploaded_urls = []
    numbered_ids  = []

    # フォルダ構造の有無
    has_folder = request.form.get('has_folder_structure', 'false').lower() == 'true'
    log.info("フォルダ構造フラグ: %s", has_folder)

    # 受付番号の採番
    session_id, warning_message = get_next_sequence_number()
    id_str = f"{session_id:05d}"  # 6桁ゼロ埋め（元コード準拠）
    log.info("発行受付番号: No.%s", id_str)

    # S3 バケット/リージョン
    bucket_name = os.getenv("BUCKET_NAME")
    region      = os.getenv("AWS_REGION")
    log.info("S3 config: bucket=%s region=%s", bucket_name, region)

    try:
        # ファイル加工（ZIP or 展開）
        result, temp_dir = zip_handler_instance.process_files(files, has_folder)
        log.info("process_files 完了: type=%s temp_dir=%s", type(result).__name__, temp_dir)

        if isinstance(result, list):
            # フォルダ構造のまま個別アップロード
            folder_prefix = f"meziro/{id_str}/"
            log.info("個別アップロード開始: prefix=%s, 件数=%d", folder_prefix, len(result))

            for index, file_path in enumerate(result, start=1):
                original_filename = os.path.basename(file_path)
                safe_filename     = sanitize_filename(original_filename)
                s3_key            = f"{folder_prefix}{index:03d}_{safe_filename}"
                s3_key            = get_unique_filename(bucket_name, s3_key)

                file_size = 0
                try:
                    file_size = os.path.getsize(file_path)
                except Exception:
                    pass

                with open(file_path, 'rb') as f:
                    s3.upload_fileobj(
                        f, bucket_name, s3_key,
                        ExtraArgs={'ContentType': 'application/octet-stream'}
                    )

                public_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
                uploaded_urls.append(public_url)
                numbered_ids.append(f"{id_str}_{index:03d}")

                log.info("S3アップロードOK: key=%s size=%d", s3_key, file_size)

        else:
            # ZIP アップロード
            zip_file_path = result
            try:
                zip_size = os.path.getsize(zip_file_path)
            except Exception:
                zip_size = -1
            log.info("ZIPアップロード準備: path=%s size=%d", zip_file_path, zip_size)

            # 受付内容のテキストを zip に同梱
            form_data_text = (
                f"【受付番号】No.{id_str}\n\n"
                f"【事業者名】{business_name}\n"
                f"【送信者名】{user_name}\n"
                f"【メールアドレス】{user_email}\n"
                f"【患者名】{patient_name}\n"
                f"【セット希望日時】{appointment_date} {appointment_hour}時\n"
                f"【製作物】{project_type}\n"
                f"【クラウン種別】{crown_type}\n"
                f"【対象部位】{', '.join(teeth)}\n"
                f"【シェード】{shade}\n"
                f"【メッセージ】\n{message.strip()}\n\n"
                "  渋谷歯科技工所\n"
                "  〒343-0845\n"
                "  埼玉県越谷市南越谷4-9-6 新越谷プラザビル203\n"
                "  TEL: 048-961-8151\n"
                "  email:shibuya8020@gmail.com"
            )

            with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', encoding='utf-8') as form_file:
                form_file.write(form_data_text)
                form_file_path = form_file.name

            with zipfile.ZipFile(zip_file_path, 'a') as zipf:
                arcname = f"{id_str}_info.txt"
                zipf.write(form_file_path, arcname=arcname)
                log.info("ZIPへ info 追記: %s", arcname)

            if os.path.exists(form_file_path):
                os.remove(form_file_path)

            numbered_filename = f"{id_str}_files.zip"
            s3_key = f"meziro/{numbered_filename}"
            s3_key = get_unique_filename(bucket_name, s3_key)

            with open(zip_file_path, 'rb') as f:
                s3.upload_fileobj(
                    f, bucket_name, s3_key,
                    ExtraArgs={'ContentType': 'application/zip'}
                )

            public_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
            uploaded_urls.append(public_url)
            numbered_ids.append(id_str)
            log.info("ZIPのS3アップロードOK: key=%s size=%d", s3_key, zip_size)

        # 一時ZIPがあれば削除
        if 'zip_file_path' in locals() and os.path.exists(zip_file_path):
            try:
                os.remove(zip_file_path)
                log.info("一時ZIP削除: %s", zip_file_path)
            except Exception as e:
                log.warning("一時ZIP削除失敗: %s err=%s", zip_file_path, e)

        # メール本文
        url_text = "\n".join(uploaded_urls)
        full_message = f"""ユーザーから以下のメッセージが届きました：

【受付番号】No.{id_str}
【事業者名】{business_name}
【送信者名】{user_name}
【メールアドレス】{user_email}
【患者名】{patient_name}
【セット希望日時】{appointment_date} {appointment_hour}時
【製作物】{project_type}
【クラウン種別】{crown_type}
【対象部位】{", ".join(teeth)}
【シェード】{shade}
【メッセージ】
{message}

【アップロードされたファイルリンク】
{url_text}
"""
        if warning_message:
            full_message += f"\n\n⚠️ システム警告：{warning_message}\n"
            log.warning("採番時警告: %s", warning_message)

        # 管理者へ
        try:
            msg = Message(
                subject=f"【仕事が来たよ】No.{id_str}",
                recipients=[os.getenv("MAIL_NOTIFICATION_RECIPIENT")],
                body=full_message
            )
            mail.send(msg)
            log.info("メール送信成功（管理者）")
        except Exception as e:
            log.error("メール送信失敗（管理者）: %s", e, exc_info=True)

        # 送信者へ
        try:
            confirmation_msg = Message(
                subject=f"【受付完了】No.{id_str} 技工指示の受付を承りました",
                recipients=[user_email],
                body=f"""{user_name} 様

この度は技工指示を送信いただき、誠にありがとうございます。
以下の内容で受付を完了いたしました。

【受付番号】No.{id_str}
【事業者名】{business_name}
【送信者名】{user_name}
【メールアドレス】{user_email}
【患者名】{patient_name}
【セット希望日時】{appointment_date} {appointment_hour}時
【製作物】{project_type}
【クラウン種別】{crown_type}
【対象部位】{", ".join(teeth)}
【シェード】{shade}
【メッセージ】
{message}

ファイルを確認の上、内容に応じて対応させていただきます。
万が一、内容に不備がある場合は別途ご連絡させていただきます。

--------------------------------
渋谷歯科技工所
〒343-0845 埼玉県越谷市南越谷4-9-6 新越谷プラザビル203
TEL: 048-961-8151
email: shibuya8020@gmail.com
"""
            )
            mail.send(confirmation_msg)
            log.info("送信者への確認メール送信成功")
        except Exception as e:
            log.error("送信者への確認メール送信失敗: %s", e, exc_info=True)

    except Exception as e:
        # ルート全体の最後の砦
        log.error("アップロード処理中に未捕捉エラー: %s", e, exc_info=True)

    # レスポンス
    if numbered_ids:
        resp_message = f"アップロード完了 受付No.{id_str}"
    else:
        resp_message = "アップロード成功（ファイルはありません）"

    log.info("=== /meziro_upload END No.%s files=%d ===", id_str, len(uploaded_urls))
    return jsonify({'message': resp_message, 'files': uploaded_urls})


@bp.route('/meziro/download/<path:key>')
def meziro_download(key):
    try:
        # URLデコード
        decoded_key = unquote(key)
        filename = os.path.basename(decoded_key)
        
        # 一時ファイルを作成
        temp_dir = os.path.join(current_app.root_path, 'temp_downloads')
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, filename)
        
        # S3からファイルをダウンロード
        s3.download_file(BUCKET_NAME, decoded_key, temp_file_path)
        
        # ファイルを送信
        return send_from_directory(
            temp_dir,
            filename,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f"ファイルのダウンロード中にエラーが発生しました: {str(e)}", "error")
        return redirect(url_for('main.meziro'))


# ファイル削除用ルート
@bp.route('/meziro/delete', methods=['POST'])
def meziro_delete():
    try:
        # URLパラメータからキーを取得（単一ファイル削除用）
        key_param = request.args.get('key')
        
        if key_param:
            # 単一ファイル削除
            decoded_key = unquote(key_param)
            
            # S3からファイル削除
            s3.delete_object(
                Bucket=BUCKET_NAME,
                Key=decoded_key
            )
            flash(f"ファイルを削除しました", "success")
        else:
            # 複数ファイル選択削除
            selected_files = request.form.getlist('selected_files')
            
            if not selected_files:
                flash("削除するファイルが選択されていません", "warning")
                return redirect(url_for('main.meziro'))
            
            deleted_count = 0
            for key in selected_files:
                # URLデコード
                decoded_key = unquote(key)
                
                # S3からファイル削除
                s3.delete_object(
                    Bucket=BUCKET_NAME,
                    Key=decoded_key
                )
                deleted_count += 1
            
            flash(f"{deleted_count}件のファイルを削除しました", "success")
    except Exception as e:
        flash(f"削除中にエラーが発生しました: {str(e)}", "danger")
    
    return redirect(url_for('main.meziro'))

def list_files_with_completed():
    resp = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=PREFIX)
    files = []
    for obj in resp.get('Contents', []):
        key = obj['Key']
        # ディレクトリエントリ避け
        if key.endswith('/'):
            continue

        tag_resp = s3.get_object_tagging(Bucket=BUCKET_NAME, Key=key)
        tags = {t['Key']: t['Value'] for t in tag_resp.get('TagSet', [])}
        completed = (tags.get('completed') == 'true')

        files.append({
            'key': key,
            'filename': key.split('/')[-1],
            'last_modified': obj['LastModified'],  # テンプレ側で表示整形OK
            'completed': completed,
        })
    return files

@bp.route('/meziro/mark-complete', methods=['POST'])
def meziro_mark_complete():
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    completed = data.get('completed')

    if key is None or completed is None:
        return jsonify(success=False, message='パラメータ不足'), 400

    try:
        # 既存タグ維持＋completed上書き
        current = s3.get_object_tagging(Bucket=BUCKET_NAME, Key=key)
        tagset = {t['Key']: t['Value'] for t in current.get('TagSet', [])}
        tagset['completed'] = 'true' if completed else 'false'
        new_tagset = [{'Key': k, 'Value': v} for k, v in tagset.items()]
        s3.put_object_tagging(Bucket=BUCKET_NAME, Key=key, Tagging={'TagSet': new_tagset})
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=f'タグ更新失敗: {e}'), 500


def to_youtube_embed(url: str | None) -> str:
    if not url:
        return ""

    url = url.strip()

    # embed
    if "youtube.com/embed/" in url:
        return url.split("?")[0]

    # shorts
    m = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}"

    # live
    m = re.search(r"youtube\.com/live/([A-Za-z0-9_-]{6,})", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}"

    # youtu.be
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}"

    # watch?v=
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}"

    return ""

# @bp.route('/<int:blog_post_id>/blog_post')
# def blog_post(blog_post_id):
#     form = BlogSearchForm()

#     item = get_post_by_id(blog_post_id)
#     if not item:
#         abort(404)

#     # --- ★ここで最新の表示名を解決する ---
#     users_table = current_app.config.get("HOERO_USERS_TABLE")
#     latest_author_name = item.get("author_name", "")  # fallback（記事に保存されてる名前）

#     uid = str(item.get("user_id", ""))  # email or uuid
#     if users_table and uid and "@" in uid:  # emailっぽい場合だけ users を引く（uuid混在対策）
#         try:
#             resp = users_table.get_item(Key={"user_id": uid})
#             u = resp.get("Item")
#             if u and u.get("display_name"):
#                 latest_author_name = u["display_name"]
#         except Exception as e:
#             print(f"[WARN] users_table lookup failed: {uid} / {e}")

#     # YouTube
#     youtube_url = item.get("youtube_url", "")
#     youtube_embed_url = to_youtube_embed(youtube_url)

#     post = SimpleNamespace(
#         id=int(item.get("post_id")),
#         title=item.get("title", ""),
#         text=item.get("text", ""),
#         summary=item.get("summary", ""),
#         featured_image=item.get("featured_image", ""),
#         featured_video=item.get("featured_video", ""),
#         youtube_url=youtube_url,
#         youtube_embed_url=youtube_embed_url,
#         date=item.get("date", ""),
#         author_name=latest_author_name,   # ★ここがポイント
#         category_name=item.get("category_name", ""),
#     )

#     # recent_posts（ここは表示名を出してないのでそのままでOK）
#     recent_items = list_recent_posts(limit=5)
#     recent_blog_posts = []
#     for it in recent_items:
#         try:
#             pid = int(it.get("post_id"))
#         except Exception:
#             continue

#         yurl = it.get("youtube_url", "") or it.get("youtube_embed_url", "")
#         yid = extract_youtube_id(yurl)

#         recent_blog_posts.append(
#             SimpleNamespace(
#                 id=pid,
#                 title=it.get("title", ""),
#                 featured_image=it.get("featured_image", ""),
#                 youtube_id=yid,
#             )
#         )

#     return render_template(
#         'main/blog_post.html',
#         post=post,
#         recent_blog_posts=recent_blog_posts,
#         blog_categories=[],
#         form=form
#     )


@bp.route('/blog/<int:blog_post_id>')  # ← URLを変更
def blog_post(blog_post_id):
    form = BlogSearchForm()

    item = get_post_by_id(blog_post_id)
    if not item:
        abort(404)

    # --- 最新の表示名を解決する ---
    users_table = current_app.config.get("HOERO_USERS_TABLE")
    latest_author_name = item.get("author_name", "")

    uid = str(item.get("user_id", ""))
    if users_table and uid and "@" in uid:
        try:
            resp = users_table.get_item(Key={"user_id": uid})
            u = resp.get("Item")
            if u and u.get("display_name"):
                latest_author_name = u["display_name"]
        except Exception as e:
            print(f"[WARN] users_table lookup failed: {uid} / {e}")

    # YouTube
    youtube_url = item.get("youtube_url", "")
    youtube_embed_url = to_youtube_embed(youtube_url)

    post = SimpleNamespace(
        id=int(item.get("post_id")),
        title=item.get("title", ""),
        text=item.get("text", ""),
        summary=item.get("summary", ""),
        featured_image=item.get("featured_image", ""),
        featured_video=item.get("featured_video", ""),
        youtube_url=youtube_url,
        youtube_embed_url=youtube_embed_url,
        date=item.get("date", ""),
        author_name=latest_author_name,
        category_name=item.get("category_name", ""),
    )

    # 最新記事
    recent_items = list_recent_posts(limit=5)
    recent_blog_posts = []
    for it in recent_items:
        try:
            pid = int(it.get("post_id"))
        except Exception:
            continue

        yurl = it.get("youtube_url", "") or it.get("youtube_embed_url", "")
        yid = extract_youtube_id(yurl)

        recent_blog_posts.append(
            SimpleNamespace(
                id=pid,
                title=it.get("title", ""),
                featured_image=it.get("featured_image", ""),
                youtube_id=yid,
            )
        )

    # ★ カテゴリ一覧を追加
    categories_raw = list_all_blog_categories()
    blog_categories = [
        SimpleNamespace(
            id=int(c["category_id"]),
            name=c.get("name", ""),
        )
        for c in categories_raw
    ]

    return render_template(
        'main/blog_post.html',
        post=post,
        recent_blog_posts=recent_blog_posts,
        blog_categories=blog_categories,  # ← 空リストではなく実データ
        form=form
    )


@bp.route('/<int:blog_post_id>/delete_post', methods=['POST'])
@login_required
def delete_post(blog_post_id):
    # ① Dynamo から該当記事取得（なければ 404）
    item = get_post_by_id(blog_post_id)    
    if not item:
        abort(404)

    # ② 必要なら「自分の投稿か」チェック
    #   user_id を hoero-users の user_id と合わせておけば、
    #   ここで current_user.id や current_user.dynamo_user_id と比較できます
    # if item.get("user_id") != str(current_user.id):
    #     abort(403)

    # ③ 削除
    ok = delete_post_by_id(blog_post_id)
    if not ok:
        abort(404)

    flash('ブログ投稿が削除されました')
    return redirect(url_for('main.blog_maintenance'))

@bp.route('/<int:blog_post_id>/update_post', methods=['GET', 'POST'])
@login_required
def update_post(blog_post_id):
    item = get_post_by_id(blog_post_id)
    if not item:
        abort(404)

    form = BlogPostForm()

    if form.validate_on_submit():
        fields = {
            "title": form.title.data,
            "summary": form.summary.data,
            "text": form.text.data,
            "category_id": str(form.category.data) if form.category.data else "",
            "youtube_url": (form.youtube_url.data or "").strip(),  # ★追加
        }

        # 画像更新
        if form.picture.data:
            new_filename = add_featured_image(form.picture.data)
            fields["featured_image"] = new_filename

        # 動画更新（★追加）
        if form.video.data:
            new_video_url = add_featured_video(form.video.data)
            fields["featured_video"] = new_video_url

        update_post_fields(blog_post_id, fields)

        flash('ブログ投稿が更新されました')
        return redirect(url_for('main.blog_post', blog_post_id=blog_post_id))

    elif request.method == 'GET':
        form.title.data = item.get("title", "")
        form.summary.data = item.get("summary", "")
        form.text.data = item.get("text", "")
        form.youtube_url.data = item.get("youtube_url", "")  # ★追加

        # category_id は Dynamo だと文字列なので int に直す
        cid = item.get("category_id", "")
        try:
            form.category.data = int(cid) if cid else None
        except Exception:
            form.category.data = None

        # 既存画像・動画の表示用
        if hasattr(form.picture, "object_data"):
            form.picture.object_data = item.get("featured_image", "")
        if hasattr(form.video, "object_data"):
            form.video.object_data = item.get("featured_video", "")

    return render_template('main/create_post.html', form=form)

@bp.route('/search', methods=['GET', 'POST'])
def search():
    form = BlogSearchForm()
    searchtext = ""
    if form.validate_on_submit():
        searchtext = form.searchtext.data
    elif request.method == 'GET':
        form.searchtext.data = ""
    
    # DynamoDB からブログ記事を取得して検索
    page = request.args.get('page', 1, type=int)
    all_posts = list_all_posts(limit=1000)
    
    # 検索フィルタリング
    if searchtext:
        filtered_posts = [
            p for p in all_posts 
            if searchtext.lower() in p.get("title", "").lower() 
            or searchtext.lower() in p.get("text", "").lower()
            or searchtext.lower() in p.get("summary", "").lower()
        ]
    else:
        filtered_posts = all_posts
    
    blog_posts = paginate_posts(filtered_posts, page=page, per_page=10)
    
    # 最新記事
    recent_items = list_recent_posts(limit=5)
    recent_blog_posts = [
        SimpleNamespace(
            post_id=int(it.get("post_id")),
            title=it.get("title", ""),
            featured_image=it.get("featured_image", ""),
        )
        for it in recent_items
    ]
    
    # カテゴリ
    blog_categories = list_blog_categories_all()
    
    return render_template('main/index.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, form=form, searchtext=searchtext)

@bp.route('/<int:blog_category_id>/category_posts')
def category_posts(blog_category_id):
    form = BlogSearchForm()
    
    # DynamoDB からカテゴリ情報を取得
    categories = list_blog_categories_all()
    blog_category = None
    for cat in categories:
        if int(cat.get("category_id", 0)) == blog_category_id:
            blog_category = SimpleNamespace(
                id=int(cat["category_id"]),
                name=cat.get("name", ""),
            )
            break
    if not blog_category:
        abort(404)
    
    # カテゴリ別のブログ記事を取得
    page = request.args.get('page', 1, type=int)
    category_items = list_posts_by_category(blog_category_id)
    blog_posts = paginate_posts(category_items, page=page, per_page=10)
    
    # 最新記事
    recent_items = list_recent_posts(limit=5)
    recent_blog_posts = [
        SimpleNamespace(
            post_id=int(it.get("post_id")),
            title=it.get("title", ""),
            featured_image=it.get("featured_image", ""),
        )
        for it in recent_items
    ]
    
    # カテゴリ一覧
    blog_categories = list_blog_categories_all()
    
    return render_template('main/index.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, blog_category=blog_category, form=form)

def verify_recaptcha(response_token):
    """reCAPTCHAの検証（v3対応）"""
    secret_key = os.getenv("RECAPTCHA_SECRET_KEY")
    if not secret_key:
        return True  # 開発環境では検証スキップ

    url = "https://www.google.com/recaptcha/api/siteverify"
    data = {
        'secret': secret_key,
        'response': response_token,
        'remoteip': request.environ.get('REMOTE_ADDR')
    }

    try:
        response = requests.post(url, data=data, timeout=10)
        result = response.json()
        
        # ログ出力（開発時）
        print("reCAPTCHA応答:", result)
        
        # 成功かつスコアが高い場合のみ許可
        return result.get('success', False) and result.get('score', 0) >= 0.5

    except Exception as e:
        print(f"reCAPTCHA検証エラー: {e}")
        return False


@bp.route('/inquiry', methods=['GET', 'POST'])
def inquiry():
    # 一時的にフォームを無効化（スパム対策）
    FORM_TEMPORARILY_DISABLED = True  # ここをFalseにすれば復旧
    
    form = InquiryForm()
    inquiry_id = request.args.get("id")
    
    # フォームが無効化されている場合はPOSTを拒否
    if FORM_TEMPORARILY_DISABLED and request.method == 'POST':
        flash('申し訳ございませんが、現在お問い合わせフォームは一時的に停止中です。', 'warning')
        return redirect(url_for('main.inquiry'))

    if form.validate_on_submit():
        # ハニーポットチェック
        if request.form.get('website'):  # 空であるべき
            flash('不正な送信が検出されました。', 'danger')
            return redirect(url_for('main.inquiry'))
        
        # reCAPTCHA検証
        recaptcha_response = request.form.get('g-recaptcha-response')
        if not recaptcha_response or not verify_recaptcha(recaptcha_response):
            flash('reCAPTCHA認証が必要です。', 'danger')
            return render_template('main/inquiry.html', form=form, inquiry_id=inquiry_id)

        # DynamoDB保存
        inquiry = InquiryDDB.create(
            name=form.name.data,
            email=form.email.data,
            title=form.title.data,
            text=form.text.data
        )

        # メール送信（管理者 + 自動返信）
        try:
            # 管理者への通知
            msg = Message(
                subject=f"【お問い合わせ】{inquiry['title']}",
                sender=os.getenv("MAIL_INQUIRY_SENDER"),
                recipients=[os.getenv("MAIL_NOTIFICATION_RECIPIENT")]
            )
            msg.body = f"""以下の内容でお問い合わせがありました：

■名前: {inquiry['name']}
■メール: {inquiry['email']}
■件名: {inquiry['title']}
■内容:
{inquiry['text']}

■日時: {datetime.now(timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M')}
■送信者IP: {request.environ.get('REMOTE_ADDR', 'unknown')}
"""
            mail.send(msg)

            # 🔹 自動返信メール（ユーザー向け）
            auto_reply = Message(
                subject="【渋谷歯科技工所】お問い合わせありがとうございました",
                sender=os.getenv("MAIL_INQUIRY_SENDER"),
                recipients=[inquiry['email']]
            )
            auto_reply.body = f"""{inquiry['name']} 様

このたびはお問い合わせいただきありがとうございます。
以下の内容で受け付けました。

件名: {inquiry['title']}
内容:
{inquiry['text']}

担当者より折り返しご連絡いたします。
今しばらくお待ちください。

------------------------------------------------------------
渋谷歯科技工所
〒343-0845
埼玉県越谷市南越谷4-9-6 新越谷プラザビル203
TEL: 048-961-8151
email:shibuya8020@gmail.com
------------------------------------------------------------
"""
            mail.send(auto_reply)

        except Exception as e:
            flash("メール送信中にエラーが発生しました。", "danger")
            print(f"メール送信エラー: {e}")

        flash("お問い合わせを受け付けました。", "success")
        return redirect(url_for('main.inquiry'))
        
    elif request.method == 'POST':
        # バリデーションエラーをユーザーに表示
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text if hasattr(getattr(form, field), 'label') else field}: {error}", "danger")

    return render_template(
    "main/inquiry.html",
    form=form,
    inquiry_id=inquiry_id,
    recaptcha_site_key=os.getenv("RECAPTCHA_SITE_KEY")
)

@bp.route('/inquiry_maintenance')
@login_required
def inquiry_maintenance():
    page = request.args.get('page', 1, type=int)
    inquiries = InquiryDDB.paginate(page=page, per_page=10)
    return render_template('main/inquiry_maintenance.html', inquiries=inquiries)


@bp.route('/inquiry/<inquiry_id>/display')
@login_required
def display_inquiry(inquiry_id):
    inquiry = InquiryDDB.get_by_id(inquiry_id)
    if not inquiry:
        abort(404)
    form = InquiryForm()
    form.name.data = inquiry["name"]
    form.email.data = inquiry["email"]
    form.title.data = inquiry["title"]
    form.text.data = inquiry["text"]
    return render_template('main/inquiry.html', form=form, inquiry_id=inquiry_id)


@bp.route('/inquiry/<inquiry_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_inquiry(inquiry_id):
    inquiry = InquiryDDB.get_by_id(inquiry_id)
    if not inquiry:
        abort(404)
    if not current_user.is_administrator:
        abort(403)
    InquiryDDB.delete(inquiry_id)
    flash('お問い合わせが削除されました')
    return redirect(url_for('main.inquiry_maintenance'))

@bp.route('/info')
def info():
    return render_template('main/info.html')

import traceback  # ← 追加（ファイルの先頭でもOK）


def get_unique_filename(bucket, key):
    """
    重複しないファイル名を生成する関数
    """
    base, ext = os.path.splitext(key)
    counter = 1
    new_key = key
    
    # 同じ名前のファイルが存在する場合は番号を付加
    while True:
        try:
            s3.head_object(Bucket=bucket, Key=new_key)
            new_key = f"{base}_{counter}{ext}"
            counter += 1
        except:
            break
    
    return new_key

@bp.route('/s3_browser')
@bp.route('/s3_browser/<int:page>')
def s3_browser(page=1):
    """
    S3にアップロードされた画像一覧を表示するページ（ページネーション対応）
    """
    try:
        # S3バケットから'analysis_original/'プレフィックスを持つオブジェクト一覧を取得
        response = s3.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix='analysis_original/'
        )
        
        if 'Contents' not in response:
            return render_template('main/s3_browser.html', images=[], pagination={
                'total': 0, 'pages': 0, 'current': page, 'has_prev': False, 'has_next': False
            })
        
        all_images = []
        for obj in response['Contents']:
            # ファイル名のみを抽出（プレフィックスを除く）
            key = obj['Key']
            filename = key.split('/')[-1]
            
            # S3の一時的なURL生成（1時間有効）
            url = s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': BUCKET_NAME,
                    'Key': key
                },
                ExpiresIn=3600
            )
            
            all_images.append({
                'filename': filename,
                'key': key,
                'url': url,
                'size': obj['Size'],
                'last_modified': obj['LastModified']
            })
        
        # 最新の画像が先頭に来るようにソート
        all_images.sort(key=lambda x: x['last_modified'], reverse=True)
        
        # ページネーション設定
        per_page = 12  # 1ページあたりの表示数（3×3グリッド）
        total_images = len(all_images)
        total_pages = (total_images + per_page - 1) // per_page  # 切り上げ除算
        
        # ページ番号の検証
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        
        # 現在のページの画像を取得
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_images)
        current_images = all_images[start_idx:end_idx]
        
        # ページネーション情報
        pagination = {
            'total': total_images,
            'pages': total_pages,
            'current': page,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None,
            'page_range': range(max(1, page - 2), min(total_pages + 1, page + 3))  # ページ番号の範囲
        }
        
        return render_template(
            'main/s3_browser.html', 
            images=current_images, 
            pagination=pagination
        )
    
    except Exception as e:
        return f"エラーが発生しました: {str(e)}", 500

@bp.route('/s3_delete/<path:key>', methods=['POST'])
def s3_delete(key):
    """
    S3から指定された画像を削除する
    """
    try:
        # URLデコード
        decoded_key = unquote(key)
        
        # S3からファイル削除
        s3.delete_object(
            Bucket=BUCKET_NAME,
            Key=decoded_key
        )
        
        flash(f"ファイル '{decoded_key}' を削除しました", 'success')
        return redirect(url_for('main.s3_browser'))
    
    except Exception as e:
        flash(f"削除中にエラーが発生しました: {str(e)}", 'danger')
        return redirect(url_for('main.s3_browser'))
    
@bp.route('/admin/cleanup_temp_files', methods=['POST'])
@login_required
def manual_cleanup():
    if not current_user.is_administrator:
        abort(403)
    

    deleted_count = cleanup_temp_files(current_app.root_path)
    flash(f'{deleted_count} 件の一時ファイルをクリーンアップしました')
    return redirect(url_for('main.index'))  # 管理画面へリダイレクト
    
def add_featured_image(upload_image):
    image_filename = upload_image.filename
    filepath = os.path.join(current_app.root_path, r'static/featured_image', image_filename)
    image_size = (1000, 1000)
    image = Image.open(upload_image)
    image.thumbnail(image_size)
    image.save(filepath)
    return image_filename

def add_featured_video(upload_video):
    """
    動画をリサイズしてS3にアップロード
    """
    input_path = None
    output_path = None
    
    try:
        # 一時ファイルとして保存
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_input:
            upload_video.save(temp_input.name)
            input_path = temp_input.name
        
        # 出力用の一時ファイル
        output_path = tempfile.mktemp(suffix='.mp4')
        
        # imageio-ffmpegのバイナリパスを取得
        ffmpeg_exe = ffmpeg.get_ffmpeg_exe()
        
        # ffmpegでリサイズ
        ffmpeg_cmd = [
            ffmpeg_exe,
            '-i', input_path,
            '-vf', 'scale=\'if(gt(iw,ih),800,-2)\':\'if(gt(iw,ih),-2,800)\'',
            '-c:v', 'libx264',
            '-crf', '23',
            '-preset', 'medium',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        print(f"ffmpeg実行中...")
        result = subprocess.run(
            ffmpeg_cmd, 
            capture_output=True, 
            text=True,
            check=True
        )
        print(f"ffmpegリサイズ完了")
        
        # S3にアップロード
        s3 = boto3.client('s3')
        timestamp = int(datetime.now().timestamp() * 1000)
        original_filename = upload_video.filename
        base_name = os.path.splitext(original_filename)[0]
        video_filename = f"{timestamp}_{base_name}.mp4"
        
        bucket_name = 'shibuya8020'
        s3_key = f'videos/{video_filename}'
        
        with open(output_path, 'rb') as f:
            s3.upload_fileobj(
                f,
                bucket_name,
                s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
        
        video_url = f"https://{bucket_name}.s3.ap-northeast-1.amazonaws.com/{s3_key}"
        
        print(f"動画アップロード成功: {video_url}")
        return video_url
        
    except subprocess.CalledProcessError as e:
        print(f"ffmpegエラー: {e.stderr}")
        raise Exception(f"動画のリサイズに失敗しました")
    except Exception as e:
        print(f"動画処理エラー: {e}")
        raise e
    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.unlink(input_path)
            except:
                pass
        if output_path and os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except:
                pass

def resize_video_with_ffmpeg(input_path, output_path, max_size=800):
    """
    ffmpegで動画をリサイズ
    """
    cmd = [
        'ffmpeg',
        '-i', input_path,
        '-vf', f'scale=\'min({max_size},iw)\':\'min({max_size},ih)\':force_original_aspect_ratio=decrease',
        '-c:v', 'libx264',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        output_path
    ]
    subprocess.run(cmd, check=True)

@bp.route("/admin/ai_collect_dental", methods=["POST"])
def ai_collect_dental():
    """AIエージェントによる自律的な収集"""
    try:
        results_ja = ai_collect_news(lang="ja", max_iterations=5)
        time.sleep(2)
        results_en = ai_collect_news(lang="en", max_iterations=3)
        
        total = results_ja["saved"] + results_en["saved"]
        
        return jsonify({
            "success": True, 
            "total": total,
            "details": {
                "ja": results_ja,
                "en": results_en
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    
