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
from extensions import db
from models.common import STLPost, STLComment, STLLike
import pymeshlab
from trimesh.visual.material import PBRMaterial
from dotenv import load_dotenv
import boto3
import os

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
    title = StringField('タイトル', validators=[], default='Untitled')
    content = TextAreaField('内容', render_kw={'placeholder': 'POST入力'})
    stl_file = FileField('STLファイル', validators=[
        FileAllowed(['stl'], 'STLファイルのみ許可されています')    
    ])
    submit = SubmitField('投稿する')

# STLサイズ軽量化関数（ログ付き）
def reduce_stl_size(input_file_path, output_file_path, target_faces=50000):
    """
    STLファイルを読み込んで、三角形数を削減して保存する関数
    target_faces: 目標とする三角形数（例: 50000個）
    """
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_file_path)

    current_faces = ms.current_mesh().face_number()

    if current_faces > target_faces:
        print(f"[軽量化開始] 元の三角形数: {current_faces} → 目標: {target_faces}")
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_faces)
        new_faces = ms.current_mesh().face_number()
        print(f"[軽量化完了] 変換後の三角形数: {new_faces}")
    else:
        print(f"[軽量化不要] 三角形数: {current_faces}（{target_faces} 以下）")

    ms.save_current_mesh(output_file_path, binary=True)

    return {
        'original_faces': current_faces,
        'new_faces': ms.current_mesh().face_number()
    }

def convert_stl_to_gltf(input_stl_path, output_gltf_path):
    try:
        # STLファイルを読み込み
        mesh = trimesh.load_mesh(input_stl_path)

        # 質感を指定（例：赤っぽい金属）
        material = PBRMaterial(
            name="RedMetal",
            baseColorFactor=[0.8, 0.0, 0.0, 1.0],  # RGBA（赤）
            metallicFactor=1.0,
            roughnessFactor=0.2
        )

        # マテリアルを適用
        mesh.visual.material = material

        # シーンに追加してエクスポート
        scene = trimesh.Scene()
        scene.add_geometry(mesh)

        glb_data = scene.export(file_type='glb')

        with open(output_gltf_path, 'wb') as f:
            f.write(glb_data)

        return True
    except Exception as e:
        print(f"変換エラー: {e}")
        return False

# STL掲示板ページ
@bp.route('/', methods=['GET', 'POST'])
def index():
    form = STLPostForm()
    selected_post_id = request.args.get('post_id', type=int)
    page = request.args.get('page', 1, type=int)

    if form.validate_on_submit():
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
                        flash('ファイルが大きいため自動的に軽量化しました（約5MB以内）', 'warning')
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
                            ExtraArgs={
                                'ContentType': 'model/gltf-binary',                                
                            }
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

        post = STLPost(
            title=form.title.data,
            content=form.content.data,
            user_id=2,  # テスト用固定値
            stl_filename=glb_filename,
            stl_file_path=glb_file_path
        )
        db.session.add(post)
        db.session.commit()
        flash('投稿が作成されました', 'success')
        return redirect(url_for('stl_board.index'))

    posts = STLPost.query.filter(STLPost.stl_file_path.isnot(None)).order_by(
        STLPost.created_at.desc()
    ).paginate(page=page, per_page=5)

    # ⭐ ここから追記します！
    for post in posts.items:
        if post.stl_file_path:
            post.s3_presigned_url = f"https://shibuya8020.s3.amazonaws.com/{post.stl_file_path}"

    selected_post = None
    if selected_post_id:
        selected_post = STLPost.query.get_or_404(selected_post_id)

    comments = STLComment.query.all()
    likes = STLLike.query.all()

    return render_template('pages/stl_board.html',
                           form=form,
                           posts=posts,
                           selected_post=selected_post,
                           selected_post_id=selected_post_id,
                           comments=comments,
                           likes=likes)

@bp.route('/add_comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('content')
    parent_id = request.form.get('parent_id')  # 返信対象があれば

    if not content:
        flash('コメント内容を入力してください', 'danger')
        return redirect(url_for('stl_board.index', post_id=post_id))

    comment = STLComment(
        content=content,
        post_id=post_id,
        user_id=current_user.id,
        parent_comment_id=parent_id if parent_id else None
    )
    db.session.add(comment)
    db.session.commit()
    flash('コメントを追加しました', 'success')
    return redirect(url_for('stl_board.index', post_id=post_id))

@bp.route('/like_post/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    post = STLPost.query.get_or_404(post_id)
    
    existing_like = STLLike.query.filter_by(post_id=post_id, user_id=current_user.id).first()
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        flash('いいねを取り消しました', 'info')
    else:
        like = STLLike(post_id=post_id, user_id=current_user.id)
        db.session.add(like)
        db.session.commit()
        flash('いいねしました', 'success')

    return redirect(url_for('stl_board.index', post_id=post_id))

@bp.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = STLPost.query.get_or_404(post_id)

    # 投稿者 or 管理者でなければ403
    if current_user.id != post.user_id and not current_user.administrator:
        abort(403)

    try:
        # S3から削除
        if post.stl_file_path:           
            s3.delete_object(Bucket=BUCKET_NAME, Key=post.stl_file_path)

        # DBから削除
        db.session.delete(post)
        db.session.commit()
        flash('投稿を削除しました', 'success')
    except Exception as e:
        flash(f'削除時にエラーが発生しました: {str(e)}', 'danger')

    return redirect(url_for('stl_board.index'))


# STLファイルのダウンロード
@bp.route('/download/<filename>')
def download(filename):
    upload_folder = os.path.join(current_app.static_folder, 'uploads', 'stl')
    return send_from_directory(upload_folder, filename)

@bp.route('/post/<int:post_id>')
def view_post(post_id):
    post = STLPost.query.get_or_404(post_id)
    
    # S3 URLの設定（index関数と同様）
    if post.stl_file_path:
        post.s3_presigned_url = f"https://shibuya8020.s3.amazonaws.com/{post.stl_file_path}"
    
    comments = STLComment.query.filter_by(post_id=post_id).all()
    
    # 'pages/'フォルダ内のテンプレートを指定
    return render_template('pages/view_STL_post.html', post=post, comments=comments)