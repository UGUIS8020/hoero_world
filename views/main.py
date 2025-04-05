from flask import Blueprint, render_template, request, url_for, redirect, flash, abort,jsonify,send_from_directory
from flask_login import login_required, current_user
from models.common import BlogCategory, BlogPost, Inquiry
from models.main import BlogCategoryForm, UpdateCategoryForm, BlogPostForm, BlogSearchForm, InquiryForm
from extensions import db
from utils.zip_handler import ZipHandler
from werkzeug.utils import secure_filename
import boto3

import os
from PIL import Image
from flask import current_app
import re
from urllib.parse import quote, unquote
import shutil

bp = Blueprint('main', __name__, url_prefix='/main', template_folder='hoero_world/templates', static_folder='hoero_world/static')

# AWSクライアントの初期化
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

BUCKET_NAME = os.getenv("S3_BUCKET")

# ZIPハンドラーのインスタンス作成
zip_handler_instance = ZipHandler()  # インスタンスを作成

@bp.route('/category_maintenance', methods=['GET', 'POST'])
@login_required
def category_maintenance():
    page = request.args.get('page', 1, type=int)
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).paginate(page=page, per_page=10)
    form = BlogCategoryForm()
    if form.validate_on_submit():
        blog_category = BlogCategory(category=form.category.data)
        db.session.add(blog_category)
        db.session.commit()
        flash('ブログカテゴリが追加されました')
        return redirect(url_for('main.category_maintenance'))
    elif form.errors:
        form.category.data = ""
        flash(form.errors['category'][0])
    return render_template('main/category_maintenance.html', blog_categories=blog_categories, form=form)

@bp.route('/<int:blog_category_id>/blog_category', methods=['GET', 'POST'])
@login_required
def blog_category(blog_category_id):
    if not current_user.is_administrator():
        abort(403)
    blog_category = BlogCategory.query.get_or_404(blog_category_id)
    form = UpdateCategoryForm(blog_category_id)
    if form.validate_on_submit():
        blog_category.category = form.category.data
        db.session.commit()
        flash('ブログカテゴリが更新されました')
        return redirect(url_for('main.category_maintenance'))
    elif request.method == 'GET':
        form.category.data = blog_category.category
    return render_template('main/blog_category.html', form=form)

@bp.route('/<int:blog_category_id>/delete_category', methods=['GET', 'POST'])
@login_required
def delete_category(blog_category_id):
    if not current_user.is_administrator():
        abort(403)
    blog_category = BlogCategory.query.get_or_404(blog_category_id)
    db.session.delete(blog_category)
    db.session.commit()
    flash('ブログカテゴリが削除されました')
    return redirect(url_for('main.category_maintenance'))

@bp.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    form = BlogPostForm()
    if form.validate_on_submit():
        if form.picture.data:
            pic = add_featured_image(form.picture.data)
        else:
            pic = ''
        blog_post = BlogPost(title=form.title.data, text=form.text.data, featured_image=pic, user_id=current_user.id, category_id=form.category.data, summary=form.summary.data)
        db.session.add(blog_post)
        db.session.commit()
        flash('ブログ投稿が作成されました')
        return redirect(url_for('main.blog_maintenance'))
    return render_template('main/create_post.html', form=form)

@bp.route('/blog_maintenance')
@login_required
def blog_maintenance():
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)
    return render_template('main/blog_maintenance.html', blog_posts=blog_posts)

@bp.route('/ugu_box')
@login_required
def ugu_box():
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    s3_files = []
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix='uploads/')
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
                    ExpiresIn=3600
                )
                s3_files.append({
                    'filename': filename, 
                    'url': file_url,
                    'last_modified': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S')  # 日時情報も追加
                })
    except Exception as e:
        flash(f"S3ファイル一覧取得中にエラー: {str(e)}", "error")

    return render_template(
        'main/ugu_box.html',
        blog_posts=blog_posts,
        s3_files=s3_files
    )

@bp.route('/<int:blog_post_id>/blog_post')
def blog_post(blog_post_id):
    form = BlogSearchForm()
    blog_post = BlogPost.query.get_or_404(blog_post_id)
    # 最新記事の取得
    recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()

    # カテゴリの取得
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()

    return render_template('main/blog_post.html', post=blog_post, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, form=form)

@bp.route('/<int:blog_post_id>/delete_post', methods=['GET', 'POST'])
@login_required
def delete_post(blog_post_id):
    blog_post = BlogPost.query.get_or_404(blog_post_id)
    if blog_post.author != current_user:
        abort(403)
    db.session.delete(blog_post)
    db.session.commit()
    flash('ブログ投稿が削除されました')
    return redirect(url_for('main.blog_maintenance'))

@bp.route('/<int:blog_post_id>/update_post', methods=['GET', 'POST'])
@login_required
def update_post(blog_post_id):
    blog_post = BlogPost.query.get_or_404(blog_post_id)
    if blog_post.author != current_user:
        abort(403)
    form = BlogPostForm()
    if form.validate_on_submit():
        blog_post.title = form.title.data
        if form.picture.data:
            blog_post.featured_image = add_featured_image(form.picture.data)
        blog_post.text = form.text.data
        blog_post.summary = form.summary.data
        blog_post.category_id = form.category.data
        db.session.commit()
        flash('ブログ投稿が更新されました')
        return redirect(url_for('main.blog_post', blog_post_id=blog_post.id))
    elif request.method == 'GET':
        form.title.data = blog_post.title
        form.picture.data = blog_post.featured_image
        form.text.data = blog_post.text
        form.summary.data = blog_post.summary
        form.category.data = blog_post.category_id
    return render_template('main/create_post.html', form=form)

@bp.route('/')
def index():
    form = BlogSearchForm()
    # ブログ記事の取得
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    # 最新記事の取得
    recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()

    # カテゴリの取得
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()

    return render_template('main/index.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, form=form)

@bp.route('/search', methods=['GET', 'POST'])
def search():
    form = BlogSearchForm()
    searchtext = ""
    if form.validate_on_submit():
        searchtext = form.searchtext.data
    elif request.method == 'GET':
        form.searchtext.data = ""
    # ブログ記事の取得
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.filter((BlogPost.text.contains(searchtext)) | (BlogPost.title.contains(searchtext)) | (BlogPost.summary.contains(searchtext))).order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    # 最新記事の取得
    recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()

    # カテゴリの取得
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()

    return render_template('main/index.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, form=form, searchtext=searchtext)

@bp.route('/<int:blog_category_id>/category_posts')
def category_posts(blog_category_id):
    form = BlogSearchForm()

    # カテゴリ名の取得
    blog_category = BlogCategory.query.filter_by(id=blog_category_id).first_or_404()

    # ブログ記事の取得
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.filter_by(category_id=blog_category_id).order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    # 最新記事の取得
    recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()

    # カテゴリの取得
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()

    return render_template('main/index.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, blog_category=blog_category, form=form)

@bp.route('/inquiry', methods=['GET', 'POST'])
def inquiry():
    form = InquiryForm()
    if form.validate_on_submit():
        inquiry = Inquiry(name=form.name.data,
                            email=form.email.data,
                            title=form.title.data,
                            text=form.text.data)
        db.session.add(inquiry)
        db.session.commit()
        flash('お問い合わせが送信されました')
        return redirect(url_for('main.inquiry'))
    return render_template('main/inquiry.html', form=form)

@bp.route('/inquiry_maintenance')
@login_required
def inquiry_maintenance():
    page = request.args.get('page', 1, type=int)
    inquiries = Inquiry.query.order_by(Inquiry.id.desc()).paginate(page=page, per_page=10)
    return render_template('main/inquiry_maintenance.html', inquiries=inquiries)

@bp.route('/<int:inquiry_id>/display_inquiry')
@login_required
def display_inquiry(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    form = InquiryForm()
    form.name.data = inquiry.name
    form.email.data = inquiry.email
    form.title.data = inquiry.title
    form.text.data = inquiry.text
    return render_template('main/inquiry.html', form=form, inquiry_id=inquiry_id)

@bp.route('/<int:inquiry_id>/delete_inquiry', methods=['GET', 'POST'])
@login_required
def delete_inquiry(inquiry_id):
    inquiries = Inquiry.query.get_or_404(inquiry_id)
    if not current_user.is_administrator():
        abort(403)
    db.session.delete(inquiries)
    db.session.commit()
    flash('お問い合わせが削除されました')
    return redirect(url_for('main.inquiry_maintenance'))

@bp.route('/info')
def info():
    return render_template('main/info.html')

import traceback  # ← 追加（ファイルの先頭でもOK）

def sanitize_filename(filename):
    """
    ファイル名をサニタイズする関数
    - 危険な文字を除去
    - 日本語などのマルチバイト文字を保持
    - パス区切り文字を除去
    """
    # パス区切り文字を除去
    filename = os.path.basename(filename)
    
    # 危険な文字を除去（ただし日本語などのマルチバイト文字は保持）
    # 英数字、日本語、一部の記号のみを許可
    filename = re.sub(r'[^\w\s\-\.\u3000-\u9fff\u3040-\u309f\u30a0-\u30ff\uff00-\uff9f]', '', filename)
    
    # 先頭と末尾の空白を除去
    filename = filename.strip()
    
    # 空のファイル名の場合はデフォルト名を使用
    if not filename:
        filename = "unnamed_file"
    
    return filename

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

@bp.route('/upload', methods=['POST'])
def upload_file():
    if 'files[]' not in request.files:
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    files = request.files.getlist('files[]')
    if not files or files[0].filename == '':
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    temp_dir = None
    try:
        result, temp_dir = zip_handler_instance.process_files(files)

        # 圧縮されてない場合はリスト、されてる場合は文字列
        if isinstance(result, list):
            uploaded_keys = []
            for file_path in result:
                original_filename = os.path.basename(file_path)
                # ファイル名をサニタイズ
                safe_filename = sanitize_filename(original_filename)
                s3_key = f"uploads/{safe_filename}"
                
                # 重複チェックと一意のファイル名生成
                s3_key = get_unique_filename(BUCKET_NAME, s3_key)
                
                with open(file_path, 'rb') as f:
                    s3.upload_fileobj(
                        f, 
                        BUCKET_NAME, 
                        s3_key,
                        ExtraArgs={
                            'ACL': 'private',
                            'ContentType': 'application/octet-stream',
                            'ServerSideEncryption': 'AES256',
                            'Metadata': {
                                'original-filename': quote(original_filename)  # 元のファイル名をメタデータとして保存
                            }
                        }
                    )
                uploaded_keys.append(s3_key)
            
            # すべてのファイルのアップロードが完了したら一時ディレクトリを削除
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                
            return jsonify({
                'message': 'ファイルは正常にS3にアップロードされました',
                'files': uploaded_keys
            }), 200
        else:
            zip_path = result
            original_filename = os.path.basename(zip_path)
            # ZIPファイル名をサニタイズ
            safe_filename = sanitize_filename(original_filename)
            s3_key = f"uploads/{safe_filename}"
            
            # 重複チェックと一意のファイル名生成
            s3_key = get_unique_filename(BUCKET_NAME, s3_key)
            
            with open(zip_path, 'rb') as f:
                s3.upload_fileobj(
                    f, 
                    BUCKET_NAME, 
                    s3_key,
                    ExtraArgs={
                        'ACL': 'private',
                        'ContentType': 'application/zip',
                        'ServerSideEncryption': 'AES256',
                        'Metadata': {
                            'original-filename': quote(original_filename)  # 元のファイル名をメタデータとして保存
                        }
                    }
                )
            
            # ZIPファイルを削除
            if os.path.exists(zip_path):
                os.remove(zip_path)
                
            return jsonify({
                'message': 'ZIPファイルは正常にS3にアップロードされました',
                'file': s3_key
            }), 200

    except Exception as e:
        print("🔥 アップロード処理中にエラーが発生しました！")
        traceback.print_exc()  # 詳細なエラー情報をターミナルに出力
        
        # エラー発生時も一時ディレクトリを削除
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        return jsonify({'error': str(e)}), 500

@bp.route('/uploaded-files')
def file_list():
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix='uploads/')
    zip_files = [
        os.path.basename(obj['Key'])
        for obj in response.get('Contents', [])
        if obj['Key'].endswith('.zip')
    ]
    return render_template('ugu_box.html', zip_files=zip_files)

@bp.route('/delete-file', methods=['POST'])
def delete_file():
    filename = request.form.get('filename')
    s3_key = f"uploads/{filename}"

    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
        flash(f"{filename} をS3から削除しました。", "success")
    except Exception as e:
        flash(f"{filename} の削除中にエラーが発生しました: {str(e)}", "error")

    return redirect(url_for('main.ugu_box')) 
    
@bp.route('/download/<filename>')
@login_required
def download_file(filename):
    try:
        # S3からファイルをダウンロード
        s3_key = f"uploads/{filename}"
        
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
    finally:
        # 一時ファイルを削除
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def add_featured_image(upload_image):
    image_filename = upload_image.filename
    filepath = os.path.join(current_app.root_path, r'static/featured_image', image_filename)
    image_size = (800, 800)
    image = Image.open(upload_image)
    image.thumbnail(image_size)
    image.save(filepath)
    return image_filename