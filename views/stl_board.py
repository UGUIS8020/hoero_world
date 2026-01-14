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
import pymeshlab
from types import SimpleNamespace

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
bp = Blueprint('stl_board', __name__, url_prefix='/stl_board')


# STL投稿用フォーム
class STLPostForm(FlaskForm):
    title = StringField('タイトル', validators=[])
    content = TextAreaField('内容', render_kw={'placeholder': 'POST入力'})
    stl_file = FileField('STLファイル', validators=[
        FileAllowed(['stl'], 'STLファイルのみ許可されています')
    ])
    submit = SubmitField('投稿する')


def reduce_stl_size(input_file_path, output_file_path, target_faces=50000):
    """STLファイルを読み込んで、三角形面数を削減して保存する関数"""
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_file_path)
    current_faces = ms.current_mesh().face_number()

    if current_faces > target_faces:
        print(f"[軽量化開始] 入力三角形面数: {current_faces} → 目標: {target_faces}")
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_faces)
        new_faces = ms.current_mesh().face_number()
        print(f"[軽量化完了] 変換後の三角形面数: {new_faces}")
    else:
        print(f"[軽量化不要] 三角形面数: {current_faces} ({target_faces} 以下)")

    ms.save_current_mesh(output_file_path, binary=True)
    return {
        'original_faces': current_faces,
        'new_faces': ms.current_mesh().face_number()
    }


def convert_stl_to_gltf(input_stl_path, output_gltf_path):
    try:
        mesh = trimesh.load_mesh(input_stl_path)
        material = PBRMaterial(
            name="RedMetal",
            baseColorFactor=[0.8, 0.0, 0.0, 1.0],
            metallicFactor=1.0,
            roughnessFactor=0.2
        )
        mesh.visual.material = material
        scene = trimesh.Scene()
        scene.add_geometry(mesh)
        glb_data = scene.export(file_type='glb')

        with open(output_gltf_path, 'wb') as f:
            f.write(glb_data)
        return True
    except Exception as e:
        print(f"変換エラー: {e}")
        return False


@bp.route('/', methods=['GET', 'POST'])
def index():
    form = STLPostForm()
    selected_post_id = request.args.get('post_id')
    page = request.args.get('page', 1, type=int)

    if form.validate_on_submit():
        # ... (投稿処理は変更なし)
        if not current_user.is_authenticated:
            flash("投稿するにはログインが必要です", "warning")
            return redirect(url_for("users.login"))

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
                        return redirect(url_for('stl_board.index'))

                    with open(glb_temp_path, "rb") as glb_data:
                        s3.upload_fileobj(
                            glb_data,
                            BUCKET_NAME,
                            glb_s3_key,
                            ExtraArgs={'ContentType': 'model/gltf-binary'}
                        )

                    os.remove(temp_path)
                    if upload_stl_path != temp_path and os.path.exists(upload_stl_path):
                        os.remove(upload_stl_path)
                    if os.path.exists(glb_temp_path):
                        os.remove(glb_temp_path)

                    glb_filename = f"{base_filename}.glb"
                    glb_file_path = glb_s3_key

                except Exception as e:
                    flash(f"S3アップロード中にエラーが発生しました: {str(e)}", 'danger')
                    return redirect(url_for('stl_board.index'))
            else:
                flash('STLファイルのみアップロードできます', 'danger')
                return redirect(url_for('stl_board.index'))

        # DynamoDB に保存
        post_id = create_stl_post(
            title=form.title.data,
            content=form.content.data,
            user_id=current_user.id,
            stl_filename=glb_filename,
            stl_file_path=glb_file_path
        )
        flash('投稿が作成されました', 'success')
        return redirect(url_for('stl_board.index'))

    # ★ ユーザーテーブルを取得    
    users_table = current_app.config.get("HOERO_USERS_TABLE")
    
    # ★ コメントといいねを全件取得（一度だけ）
    all_comments = get_all_comments()
    all_likes = get_all_likes()
    
    # DynamoDB から投稿を取得
    posts_data = paginate_stl_posts(page=page, per_page=5)
    
    # SimpleNamespace に変換してテンプレート互換性を保つ
    posts_items = []
    for it in posts_data["items"]:
        post_id = it.get("post_id")
        
        # ユーザー情報を取得
        user_id = str(it.get("user_id", 0))
        author = SimpleNamespace(
            id=user_id,
            display_name="Unknown User",
            email=""
        )
        
        if users_table:
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
        
        # created_atをdatetimeオブジェクトに変換
        created_at_str = it.get("created_at", "")
        created_at = None
        if created_at_str:
            try:
                created_at = datetime.datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            except:
                created_at = datetime.datetime.utcnow()
        else:
            created_at = datetime.datetime.utcnow()
        
        # ★ この投稿のコメントといいねをフィルタ
        post_comments = [c for c in all_comments if c.get("post_id") == post_id]
        post_likes = [l for l in all_likes if l.get("post_id") == post_id]
        
        # ★ likesとcommentsをリストラッパーとして作成（selfを追加）
        likes_wrapper = type('LikesWrapper', (), {
            'count': lambda self: len(post_likes),  # ← selfを追加
            'all': lambda self: post_likes  # ← selfを追加
        })()

        comments_wrapper = type('CommentsWrapper', (), {
            'count': lambda self: len(post_comments),  # ← selfを追加
            'all': lambda self: post_comments  # ← selfを追加
        })()
        
        post_obj = SimpleNamespace(
            post_id=post_id,
            title=it.get("title", ""),
            content=it.get("content", ""),
            user_id=str(it.get("user_id", "")),
            stl_filename=it.get("stl_filename", ""),
            stl_file_path=it.get("stl_file_path", ""),
            created_at=created_at,
            author=author,
            likes=likes_wrapper,  # ★ 追加
            comments=comments_wrapper,  # ★ 追加
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

    selected_post = None
    if selected_post_id:
        post_item = get_stl_post_by_id(selected_post_id)
        if post_item:
            user_id = str(post_item.get("user_id", ""))

            # ★ intにしない（user_idは文字列で統一）
            author = SimpleNamespace(
                id=user_id,
                display_name="Unknown User",
                email=user_id if "@" in user_id else ""
            )

            if users_table:
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

            # created_atをdatetimeオブジェクトに変換
            created_at_str = post_item.get("created_at", "")
            if created_at_str:
                try:
                    created_at = datetime.datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                except Exception:
                    created_at = datetime.datetime.utcnow()
            else:
                created_at = datetime.datetime.utcnow()
            
            # ★ selected_postのコメントといいね
            post_comments = [c for c in all_comments if c.get("post_id") == selected_post_id]
            post_likes = [l for l in all_likes if l.get("post_id") == selected_post_id]

            likes_wrapper = type('LikesWrapper', (), {
                'count': lambda self: len(post_likes),  # ← selfを追加
                'all': lambda self: post_likes  # ← selfを追加
            })()

            comments_wrapper = type('CommentsWrapper', (), {
                'count': lambda self: len(post_comments),  # ← selfを追加
                'all': lambda self: post_comments  # ← selfを追加
            })()
            
            selected_post = SimpleNamespace(
                post_id=post_item.get("post_id"),
                title=post_item.get("title", ""),
                content=post_item.get("content", ""),
                user_id=str(post_item.get("user_id", "")),
                stl_file_path=post_item.get("stl_file_path", ""),
                created_at=created_at,
                author=author,
                likes=likes_wrapper,  # ★ 追加
                comments=comments_wrapper,  # ★ 追加
                s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{post_item.get('stl_file_path', '')}" if post_item.get("stl_file_path") else None
            )

    comments = all_comments
    likes = all_likes

    return render_template('pages/stl_board.html',
                           form=form,
                           posts=posts,
                           selected_post=selected_post,
                           selected_post_id=selected_post_id,
                           comments=comments,
                           likes=likes)


@bp.route('/add_comment/<post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('content')
    parent_id = request.form.get('parent_id')

    if not content:
        flash('コメント内容を入力してください', 'danger')
        return redirect(url_for('stl_board.index', post_id=post_id))

    create_stl_comment(
        post_id=post_id,
        user_id=current_user.id,
        content=content,
        parent_comment_id=parent_id if parent_id else None
    )
    flash('コメントを追加しました', 'success')
    return redirect(url_for('stl_board.index', post_id=post_id))


@bp.route('/like_post/<post_id>', methods=['POST'])
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

    return redirect(url_for('stl_board.index', post_id=post_id))


@bp.route('/delete/<post_id>', methods=['POST'])
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

    return redirect(url_for('stl_board.index'))


@bp.route('/download/<filename>')
def download(filename):
    upload_folder = os.path.join(current_app.static_folder, 'uploads', 'stl')
    return send_from_directory(upload_folder, filename)


@bp.route('/post/<post_id>')
def view_post(post_id):
    post_item = get_stl_post_by_id(post_id)
    if not post_item:
        abort(404)

    post = SimpleNamespace(
        post_id=post_item.get("post_id"),
        title=post_item.get("title", ""),
        content=post_item.get("content", ""),
        user_id=str(post_item.get("user_id", "")),
        stl_file_path=post_item.get("stl_file_path", ""),
        s3_presigned_url=f"https://{BUCKET_NAME}.s3.amazonaws.com/{post_item.get('stl_file_path', '')}" if post_item.get("stl_file_path") else None
    )

    comments = get_comments_by_post(post_id)

    return render_template('pages/stl_post_detail.html', post=post, comments=comments)