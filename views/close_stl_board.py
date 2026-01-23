import os
import datetime
import tempfile
from flask import Blueprint, render_template, flash, redirect, url_for, request, send_from_directory, current_app, abort
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length
import trimesh
from trimesh.visual.material import PBRMaterial
from dotenv import load_dotenv
import boto3
from types import SimpleNamespace
import re
from PIL import Image, ImageOps
import io

from utils.stl_dynamo import (
    create_stl_post,
    get_stl_post_by_id,
    list_stl_posts,
    delete_stl_post,
    paginate_stl_posts,
    create_stl_comment,
    get_comments_by_post,
    get_all_comments,
    delete_comments_by_post,
    create_stl_like,
    get_like_by_post_and_user,
    delete_stl_like,
    get_likes_by_post,
    get_all_likes,
    delete_likes_by_post,
    update_stl_post,
)

load_dotenv()

# AWSクライアントの初期化
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

BUCKET_NAME = os.getenv("BUCKET_NAME")

# STL掲示板用のブループリント
bp_close = Blueprint("close_stl_board", __name__, url_prefix="/close_stl_board")


def upload_resized_image_to_s3(file_storage, *, max_width=1000, quality=85, prefix="STL-board/images/"):
    """
    スマホ写真などを横幅max_widthに縮小してS3へアップロードし、S3キーを返す
    - 形式: jpeg/png/webp対応
    - exif回転補正あり
    """
    original = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(original)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise ValueError("画像は jpg/jpeg/png/webp のみアップロードできます")

    # Pillowで読み込み（EXIF回転も補正）
    img = Image.open(file_storage.stream)
    img = ImageOps.exif_transpose(img)

    # リサイズ（横幅だけ基準、縦横比維持）
    w, h = img.size
    if w > max_width:
        new_h = int(h * (max_width / float(w)))
        img = img.resize((max_width, new_h), Image.LANCZOS)

    # 透過PNG→JPEGの事故防止（PNG/WebPの透過は保持、JPEGはRGB化）
    out = io.BytesIO()

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    base = os.path.splitext(original)[0]
    base_filename = f"{timestamp}_{base}"

    if ext in [".jpg", ".jpeg"]:
        img = img.convert("RGB")
        img.save(out, format="JPEG", quality=quality, optimize=True)
        content_type = "image/jpeg"
        key = f"{prefix}{base_filename}.jpg"

    elif ext == ".png":
        # PNGはそのまま（圧縮）
        img.save(out, format="PNG", optimize=True)
        content_type = "image/png"
        key = f"{prefix}{base_filename}.png"

    else:  # .webp
        # WebPで保存（軽い）
        img.save(out, format="WEBP", quality=quality, method=6)
        content_type = "image/webp"
        key = f"{prefix}{base_filename}.webp"

    out.seek(0)

    s3.upload_fileobj(
        out,
        BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type}
    )
    return key


# STL投稿用フォーム
class STLPostForm(FlaskForm):
    title = StringField('タイトル', validators=[])
    content = TextAreaField('内容', render_kw={'placeholder': 'POST入力'})
    stl_file = FileField('STLファイル', validators=[FileAllowed(['stl'], 'STLファイルのみ許可されています')])
    image_file = FileField('画像', validators=[  # ★追加
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], '画像ファイルのみ許可されています')
    ])
    youtube_url = StringField('YouTube URL', render_kw={'placeholder': 'https://www.youtube.com/watch?v=...'})
    submit = SubmitField('更新する')


def extract_youtube_id(url: str) -> str:
    """YouTube URLから動画IDを抽出"""
    if not url:
        return ""
    
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""

def to_youtube_embed(url: str) -> str:
    """YouTube URLを埋め込み形式に変換"""
    video_id = extract_youtube_id(url)
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}"
    return ""


def reduce_stl_size(input_file_path, output_file_path, target_faces=70000):
    """Trimeshを使った軽量化"""
        
    mesh = trimesh.load_mesh(input_file_path)
    current_faces = len(mesh.faces)
    
    if current_faces > target_faces:
        print(f"[軽量化開始] 入力三角形面数: {current_faces} → 目標: {target_faces}")
        
        # Trimeshの簡略化機能を使用
        ratio = target_faces / current_faces
        mesh = mesh.simplify_quadric_decimation(target_faces)
        
        new_faces = len(mesh.faces)
        print(f"[軽量化完了] 変換後の三角形面数: {new_faces}")
    else:
        print(f"[軽量化不要] 三角形面数: {current_faces} ({target_faces} 以下)")
    
    mesh.export(output_file_path)
    
    return {
        'original_faces': current_faces,
        'new_faces': len(mesh.faces)
    }


def convert_stl_to_gltf(input_stl_path, output_gltf_path):
    try:
        loaded = trimesh.load(input_stl_path, force='mesh')
        if isinstance(loaded, trimesh.Scene):
            geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not geoms:
                raise ValueError("Scene内にTrimeshジオメトリがありません")
            mesh = trimesh.util.concatenate(geoms)
        else:
            mesh = loaded

        if not isinstance(mesh, trimesh.Trimesh) or mesh.faces is None or len(mesh.faces) == 0:
            raise ValueError("faces を持たないメッシュのため material を設定できません")

        # ★ここが光沢調整（PBR）
        mat = PBRMaterial(
            baseColorFactor=[50/255, 50/255, 50/255, 1.0],  # グレー（0〜1）
            metallicFactor=0.0,    # 金属っぽさ（0=非金属）
            roughnessFactor=0.25   # ★ツヤ：低いほどテカる（0.05〜0.3がツヤ強め）
        )

        # face_colors を使わず material で色+光沢を指定        
        mesh.visual.material = mat

        scene = trimesh.Scene(mesh)
        glb_data = scene.export(file_type='glb')

        with open(output_gltf_path, 'wb') as f:
            f.write(glb_data)
        return True

    except Exception as e:
        print(f"変換エラー: {e} ({type(e).__name__})")
        return False


@bp_close.route('/', methods=['GET', 'POST'])
@login_required
def index():
    form = STLPostForm()
    selected_post_id = request.args.get('post_id')
    page = request.args.get('page', 1, type=int)

    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("投稿するにはログインが必要です", "warning")
            return redirect(url_for("users.login"))

        # =========================================
        # 1) STLファイルの処理
        # =========================================
        stl_file = form.stl_file.data
        glb_filename = None
        glb_file_path = None

        if stl_file and stl_file.filename != '':
            if stl_file.filename.lower().endswith('.stl'):
                original_filename = secure_filename(stl_file.filename)
                timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                base_filename = f"{timestamp}_{os.path.splitext(original_filename)[0]}"
                glb_s3_key = f"STL-board/{base_filename}.glb"

                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as temp:
                        stl_file.save(temp.name)
                        temp_path = temp.name

                    file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
                    if file_size_mb > 5.0:
                        reduced_temp_path = temp_path.replace(".stl", "_reduced.stl")
                        reduce_stl_size(temp_path, reduced_temp_path)
                        upload_stl_path = reduced_temp_path
                        flash('ファイルが大きいため自動的に軽量化しました（元5MB以下）', 'warning')
                    else:
                        upload_stl_path = temp_path

                    glb_temp_path = upload_stl_path.replace(".stl", ".glb")
                    if not convert_stl_to_gltf(upload_stl_path, glb_temp_path):
                        flash('glTF変換に失敗しました', 'danger')
                        return redirect(url_for('close_stl_board.index'))

                    with open(glb_temp_path, "rb") as glb_data:
                        s3.upload_fileobj(
                            glb_data,
                            BUCKET_NAME,
                            glb_s3_key,
                            ExtraArgs={'ContentType': 'model/gltf-binary'}
                        )

                    # 後片付け
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    if upload_stl_path != temp_path and os.path.exists(upload_stl_path):
                        os.remove(upload_stl_path)
                    if os.path.exists(glb_temp_path):
                        os.remove(glb_temp_path)

                    glb_filename = f"{base_filename}.glb"
                    glb_file_path = glb_s3_key

                except Exception as e:
                    flash(f"S3アップロード中にエラーが発生しました: {str(e)}", 'danger')
                    return redirect(url_for('close_stl_board.index'))
            else:
                flash('STLファイルのみアップロードできます', 'danger')
                return redirect(url_for('close_stl_board.index'))

        # =========================================
        # 2) 画像ファイルの処理（横幅1000pxに縮小してS3へ）
        # =========================================
        image_file_path = None
        if form.image_file.data and form.image_file.data.filename:
            try:
                image_file_path = upload_resized_image_to_s3(
                    form.image_file.data,
                    max_width=1000,
                    quality=85,
                    prefix="STL-board/images/"
                )
            except Exception as e:
                flash(f"画像アップロード中にエラーが発生しました: {str(e)}", "danger")
                return redirect(url_for("close_stl_board.index"))

        # =========================================
        # 3) YouTube URL の処理
        # =========================================
        youtube_url = (form.youtube_url.data or "").strip()
        youtube_id = extract_youtube_id(youtube_url) if youtube_url else ""
        youtube_embed_url = to_youtube_embed(youtube_url) if youtube_url else ""

        # =========================================
        # 4) 投稿を作成
        # =========================================
        post_id = create_stl_post(
            title=form.title.data,
            content=form.content.data,
            user_id=current_user.email,
            stl_filename=glb_filename,
            stl_file_path=glb_file_path,
            youtube_url=youtube_url,
            youtube_id=youtube_id,
            youtube_embed_url=youtube_embed_url,
            image_file_path=image_file_path,  # ★追加
        )
        flash('投稿が作成されました', 'success')
        return redirect(url_for('close_stl_board.index'))

    # ==========================================================
    # 以下：表示処理（GET）
    # ==========================================================

    # ユーザーテーブル
    users_table = current_app.config.get("HOERO_USERS_TABLE")

    # 共通ヘルパー関数
    def resolve_author(user_id: str):
        user_id = str(user_id or "")
        author = SimpleNamespace(
            id=user_id,
            display_name="Unknown User",
            email=user_id if "@" in user_id else ""
        )
        if users_table and user_id:
            try:
                user_response = users_table.get_item(Key={"user_id": user_id})
                user_data = user_response.get("Item", {})
                if user_data:
                    author = SimpleNamespace(
                        id=user_id,
                        display_name=user_data.get("display_name", "Unknown User"),
                        email=user_data.get("email", "")
                    )
            except Exception as e:
                print(f"ユーザー情報取得エラー (user_id: {user_id}): {e}")
        return author

    def to_datetime(dt_value):
        """DynamoDBの文字列/Noneなどを datetime に寄せる"""
        if not dt_value:
            return datetime.datetime.utcnow()
        if hasattr(dt_value, "strftime"):
            return dt_value
        s = str(dt_value)
        try:
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return datetime.datetime.utcnow()

    # コメント・いいねを全件取得
    all_comments = get_all_comments()
    all_likes = get_all_likes()

    # コメントをテンプレ互換に整形
    all_comments_obj = []
    for c in (all_comments or []):
        c_dict = dict(c)
        raw_user_id = c_dict.pop("user_id", "")
        raw_created_at = c_dict.pop("created_at", None)
        c_user_id = str(raw_user_id or "")

        comment_obj = SimpleNamespace(
            **c_dict,
            user_id=c_user_id,
            author=resolve_author(c_user_id),
            created_at=to_datetime(raw_created_at)
        )
        all_comments_obj.append(comment_obj)

    # 投稿を取得
    posts_data = paginate_stl_posts(page=page, per_page=5)

    posts_items = []
    for it in posts_data["items"]:
        post_id = it.get("post_id")
        user_id = str(it.get("user_id", ""))
        author = resolve_author(user_id)
        created_at = to_datetime(it.get("created_at"))

        # YouTube 情報
        youtube_url = it.get("youtube_url", "")
        youtube_id = it.get("youtube_id", "") or extract_youtube_id(youtube_url)
        youtube_embed_url = it.get("youtube_embed_url", "") or to_youtube_embed(youtube_url)

        # ★画像
        image_path = it.get("image_file_path", "") or ""
        image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{image_path}" if image_path else None

        post_comments = [c for c in all_comments_obj if getattr(c, "post_id", None) == post_id]
        post_likes = [l for l in all_likes if l.get("post_id") == post_id]

        likes_wrapper = type('LikesWrapper', (), {
            'count': lambda self: len(post_likes),
            'all': lambda self: post_likes
        })()

        comments_wrapper = type('CommentsWrapper', (), {
            'count': lambda self: len(post_comments),
            'all': lambda self: post_comments
        })()

        post_obj = SimpleNamespace(
            post_id=post_id,
            title=it.get("title", ""),
            content=it.get("content", ""),
            user_id=user_id,
            stl_filename=it.get("stl_filename", ""),
            stl_file_path=it.get("stl_file_path", ""),
            image_file_path=image_path,     # ★追加（必要なら）
            image_url=image_url,            # ★追加（テンプレ表示用）
            created_at=created_at,
            author=author,
            likes=likes_wrapper,
            comments=comments_wrapper,
            youtube_url=youtube_url,
            youtube_id=youtube_id,
            youtube_embed_url=youtube_embed_url,
            s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{it.get('stl_file_path', '')}" if it.get("stl_file_path") else None
        )
        posts_items.append(post_obj)

    posts = SimpleNamespace(
        items=posts_items,
        page=posts_data["page"],
        pages=posts_data["pages"],
        has_prev=posts_data["has_prev"],
        has_next=posts_data["has_next"],
        prev_num=posts_data["prev_num"],
        next_num=posts_data["next_num"],
    )

    # selected_post
    selected_post = None
    if selected_post_id:
        post_item = get_stl_post_by_id(selected_post_id)
        if post_item:
            user_id = str(post_item.get("user_id", ""))
            author = resolve_author(user_id)
            created_at = to_datetime(post_item.get("created_at"))

            youtube_url = post_item.get("youtube_url", "")
            youtube_id = post_item.get("youtube_id", "") or extract_youtube_id(youtube_url)
            youtube_embed_url = post_item.get("youtube_embed_url", "") or to_youtube_embed(youtube_url)

            # ★画像
            image_path = post_item.get("image_file_path", "") or ""
            image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{image_path}" if image_path else None

            post_comments = [c for c in all_comments_obj if getattr(c, "post_id", None) == selected_post_id]
            post_likes = [l for l in all_likes if l.get("post_id") == selected_post_id]

            likes_wrapper = type('LikesWrapper', (), {
                'count': lambda self: len(post_likes),
                'all': lambda self: post_likes
            })()

            comments_wrapper = type('CommentsWrapper', (), {
                'count': lambda self: len(post_comments),
                'all': lambda self: post_comments
            })()

            selected_post = SimpleNamespace(
                post_id=post_item.get("post_id"),
                title=post_item.get("title", ""),
                content=post_item.get("content", ""),
                user_id=user_id,
                stl_file_path=post_item.get("stl_file_path", ""),
                image_file_path=image_path,   # ★追加
                image_url=image_url,          # ★追加
                created_at=created_at,
                author=author,
                likes=likes_wrapper,
                comments=comments_wrapper,
                youtube_url=youtube_url,
                youtube_id=youtube_id,
                youtube_embed_url=youtube_embed_url,
                s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{post_item.get('stl_file_path', '')}" if post_item.get("stl_file_path") else None
            )

    comments = all_comments_obj
    likes = all_likes

    return render_template(
        'pages/close_stl_board.html',
        form=form,
        posts=posts,
        selected_post=selected_post,
        selected_post_id=selected_post_id,
        comments=comments,
        likes=likes
    )


@bp_close.route('/add_comment/<post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('content')
    parent_id = request.form.get('parent_id')

    if not content:
        flash('コメント内容を入力してください', 'danger')
        return redirect(url_for('close_stl_board.index', post_id=post_id))

    create_stl_comment(
        post_id=post_id,        
        user_id=current_user.email,
        content=content,
        parent_comment_id=parent_id if parent_id else None
    )
    flash('コメントを追加しました', 'success')
    return redirect(url_for('close_stl_board.index', post_id=post_id))


@bp_close.route('/like_post/<post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    post = get_stl_post_by_id(post_id)
    if not post:
        abort(404)

    existing_like = get_like_by_post_and_user(post_id, current_user.id)
    if existing_like:
        delete_stl_like(existing_like["like_id"])
        flash('いいねを取り消しました', 'info')
    else:
        create_stl_like(post_id=post_id, user_id=current_user.id)
        flash('いいねしました', 'success')

    return redirect(url_for('close_stl_board.index', post_id=post_id))


@bp_close.route('/delete/<post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = get_stl_post_by_id(post_id)
    if not post:
        abort(404)

    # 投稿者 or 管理者でなければ403
    if str(current_user.id) != str(post.get("user_id", "")) and not current_user.administrator: abort(403)

    try:
        # S3から削除
        if post.get("stl_file_path"):
            s3.delete_object(Bucket=BUCKET_NAME, Key=post["stl_file_path"])

        # 関連するコメントといいねも削除
        delete_comments_by_post(post_id)
        delete_likes_by_post(post_id)
        
        # 投稿を削除
        delete_stl_post(post_id)
        flash('投稿を削除しました', 'success')
    except Exception as e:
        flash(f'削除時にエラーが発生しました: {str(e)}', 'danger')

    return redirect(url_for('close_stl_board.index'))


@bp_close.route('/download/<filename>')
def download(filename):
    upload_folder = os.path.join(current_app.static_folder, 'uploads', 'stl')
    return send_from_directory(upload_folder, filename)


@bp_close.route('/post/<post_id>')
def view_post(post_id):
    post_item = get_stl_post_by_id(post_id)
    if not post_item:
        abort(404)

    # YouTube 情報を取得
    youtube_url = post_item.get("youtube_url", "")
    youtube_id = post_item.get("youtube_id", "") or extract_youtube_id(youtube_url)
    youtube_embed_url = post_item.get("youtube_embed_url", "") or to_youtube_embed(youtube_url)

    # ユーザー情報を取得
    users_table = current_app.config.get("HOERO_USERS_TABLE")
    user_id = str(post_item.get("user_id", ""))
    author_name = "Unknown User"
    
    if users_table and user_id:
        try:
            user_response = users_table.get_item(Key={"user_id": user_id})
            user_data = user_response.get("Item", {})
            if user_data:
                author_name = user_data.get("display_name", "Unknown User")
        except Exception as e:
            print(f"ユーザー情報取得エラー: {e}")

    # 作成日時を datetime に変換
    created_at = post_item.get("created_at", "")
    try:
        created_at_dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        created_at_dt = datetime.datetime.utcnow()

    image_path = post_item.get("image_file_path", "") or ""
    image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{image_path}" if image_path else None

    post = SimpleNamespace(
        post_id=post_item.get("post_id"),
        title=post_item.get("title", ""),
        content=post_item.get("content", ""),
        user_id=user_id,
        author_name=author_name,
        created_at=created_at_dt,
        stl_file_path=post_item.get("stl_file_path", ""),
        youtube_url=youtube_url,
        youtube_id=youtube_id,
        youtube_embed_url=youtube_embed_url,
        image_file_path=image_path,
        image_url=image_url,
        s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{post_item.get('stl_file_path', '')}" if post_item.get("stl_file_path") else None
    )

    comments = get_comments_by_post(post_id)

    # ★ 最新のSTL投稿を取得（サイドバー用）
    try:
        recent_items = list_stl_posts(limit=5)
        print(f"\n=== 最新投稿取得 ===")
        print(f"取得した投稿数: {len(recent_items)}")
    except Exception as e:
        print(f"最新投稿取得エラー: {e}")
        recent_items = []
    
    recent_posts = []
    for idx, it in enumerate(recent_items, 1):
        pid = it.get("post_id")
        if not pid:
            continue
        
        # YouTube 情報を複数のソースから取得
        yurl = it.get("youtube_url", "")
        yembed = it.get("youtube_embed_url", "")
        yid_stored = it.get("youtube_id", "")
        
        # 優先順位: 保存済みID > URLから抽出 > embed URLから抽出
        yid = yid_stored or extract_youtube_id(yurl) or extract_youtube_id(yembed)
        
        stl_path = it.get("stl_file_path", "")
        
        # ★ 詳細なデバッグ出力
        print(f"\n[{idx}] 投稿ID: {pid}")
        print(f"    タイトル: {it.get('title', '無題')}")
        print(f"    youtube_url: '{yurl}'")
        print(f"    youtube_embed_url: '{yembed}'")
        print(f"    youtube_id (保存済み): '{yid_stored}'")
        print(f"    youtube_id (抽出結果): '{yid}'")
        print(f"    stl_file_path: '{stl_path}'")
        
        # 空文字列を None に変換
        yid = yid if yid and yid.strip() else None
        stl_path = stl_path if stl_path and stl_path.strip() else None
        
        print(f"    最終判定 - YouTube: {yid is not None}, STL: {stl_path is not None}")

        raw_created_at = it.get("created_at", "")
        try:
            recent_created_at_dt = datetime.datetime.fromisoformat(str(raw_created_at).replace("Z", "+00:00"))
        except Exception:
            recent_created_at_dt = None
        
        recent_posts.append(
            SimpleNamespace(
                post_id=pid,
                title=it.get("title", "無題"),
                youtube_id=yid,
                stl_file_path=stl_path,
                created_at=recent_created_at_dt
            )
        )
    
    print(f"\n=== recent_posts数: {len(recent_posts)} ===\n")

    return render_template('pages/close_stl_post_detail.html', 
                         post=post, 
                         comments=comments,
                         recent_posts=recent_posts)


@bp_close.route('/edit/<post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post_item = get_stl_post_by_id(post_id)
    if not post_item:
        abort(404)

    if str(current_user.email) != str(post_item.get("user_id", "")) and not current_user.administrator:
        abort(403)

    form = STLPostForm()

    if form.validate_on_submit():
        try:
            # ----------------------------
            # STL更新（必要なら）
            # ----------------------------
            stl_file = form.stl_file.data
            glb_filename = post_item.get("stl_filename")
            glb_file_path = post_item.get("stl_file_path")

            if stl_file and stl_file.filename:
                if not stl_file.filename.lower().endswith(".stl"):
                    flash("STLファイルのみアップロードできます", "danger")
                    return redirect(url_for("close_stl_board.edit_post", post_id=post_id))

                # 古いGLBを削除
                if post_item.get("stl_file_path"):
                    try:
                        s3.delete_object(Bucket=BUCKET_NAME, Key=post_item["stl_file_path"])
                    except Exception as e:
                        print(f"古いファイル削除エラー: {e}")

                original_filename = secure_filename(stl_file.filename)
                timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                base_filename = f"{timestamp}_{os.path.splitext(original_filename)[0]}"
                glb_s3_key = f"STL-board/{base_filename}.glb"

                with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as temp:
                    stl_file.save(temp.name)
                    temp_path = temp.name

                file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
                if file_size_mb > 5.0:
                    reduced_temp_path = temp_path.replace(".stl", "_reduced.stl")
                    reduce_stl_size(temp_path, reduced_temp_path)
                    upload_stl_path = reduced_temp_path
                    flash("ファイルが大きいため自動的に軽量化しました", "warning")
                else:
                    upload_stl_path = temp_path

                glb_temp_path = upload_stl_path.replace(".stl", ".glb")
                if not convert_stl_to_gltf(upload_stl_path, glb_temp_path):
                    flash("glTF変換に失敗しました", "danger")
                    return redirect(url_for("close_stl_board.edit_post", post_id=post_id))

                with open(glb_temp_path, "rb") as glb_data:
                    s3.upload_fileobj(
                        glb_data, BUCKET_NAME, glb_s3_key,
                        ExtraArgs={"ContentType": "model/gltf-binary"}
                    )

                # 一時ファイル掃除
                try:
                    os.remove(temp_path)
                except:
                    pass
                if upload_stl_path != temp_path and os.path.exists(upload_stl_path):
                    os.remove(upload_stl_path)
                if os.path.exists(glb_temp_path):
                    os.remove(glb_temp_path)

                glb_filename = f"{base_filename}.glb"
                glb_file_path = glb_s3_key

            # ----------------------------
            # 画像更新（必要なら：横幅1000pxに縮小してS3へ）
            # ----------------------------
            image_file_path = post_item.get("image_file_path")  # 既存を維持

            if form.image_file.data and form.image_file.data.filename:
                try:
                    image_file_path = upload_resized_image_to_s3(
                        form.image_file.data,
                        max_width=1000,
                        quality=85,
                        prefix="STL-board/images/"
                    )
                except Exception as e:
                    flash(f"画像アップロード中にエラーが発生しました: {str(e)}", "danger")
                    return redirect(url_for("close_stl_board.edit_post", post_id=post_id))

            # ----------------------------
            # YouTube更新
            # ----------------------------
            youtube_url = (form.youtube_url.data or "").strip()
            youtube_id = extract_youtube_id(youtube_url) if youtube_url else ""
            youtube_embed_url = to_youtube_embed(youtube_url) if youtube_url else ""

            # ----------------------------
            # DB更新
            # ----------------------------
            update_stl_post(
                post_id=post_id,
                title=form.title.data,
                content=form.content.data,
                stl_filename=glb_filename,
                stl_file_path=glb_file_path,
                youtube_url=youtube_url,
                youtube_id=youtube_id,
                youtube_embed_url=youtube_embed_url,
                image_file_path=image_file_path,
            )

            flash("投稿を更新しました", "success")
            return redirect(url_for("close_stl_board.view_post", post_id=post_id))

        except Exception as e:
            flash(f"更新中にエラーが発生しました: {str(e)}", "danger")

    elif request.method == "GET":
        form.title.data = post_item.get("title", "")
        form.content.data = post_item.get("content", "")
        form.youtube_url.data = post_item.get("youtube_url", "")

    # ============================
    # テンプレ用（表示用データ）
    # ============================

    # YouTube
    youtube_url = post_item.get("youtube_url", "")
    youtube_id = post_item.get("youtube_id", "") or extract_youtube_id(youtube_url)
    youtube_embed_url = post_item.get("youtube_embed_url", "") or to_youtube_embed(youtube_url)

    # ★画像URLを追加
    image_path = post_item.get("image_file_path", "") or ""
    image_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{image_path}" if image_path else None

    current_post = SimpleNamespace(
        post_id=post_item.get("post_id"),
        title=post_item.get("title", ""),
        content=post_item.get("content", ""),

        # STL
        stl_file_path=post_item.get("stl_file_path", ""),
        s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{post_item.get('stl_file_path', '')}"
            if post_item.get("stl_file_path") else None,

        # YouTube
        youtube_url=youtube_url,
        youtube_id=youtube_id,
        youtube_embed_url=youtube_embed_url,

        # ★画像
        image_file_path=image_path,
        image_url=image_url,
    )

    return render_template("pages/edit_stl_post.html", form=form, post_id=post_id, current_post=current_post)