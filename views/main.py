from flask import Blueprint, render_template, request, url_for, redirect, flash, abort, jsonify, send_from_directory, current_app, request
from flask_login import login_required, current_user
from flask_mail import Mail, Message
from models.common import BlogCategory, BlogPost, Inquiry
from models.main import BlogCategoryForm, UpdateCategoryForm, BlogPostForm, BlogSearchForm, InquiryForm
from extensions import db
import boto3
import shutil
import os
from datetime import timezone, timedelta, datetime
from dotenv import load_dotenv
from PIL import Image
from flask import current_app
from urllib.parse import unquote
import io
import base64
from extensions import mail
from utils.common_utils import get_next_sequence_number, process_image, sanitize_filename, ZipHandler, setup_scheduled_cleanup, cleanup_temp_files


JST = timezone(timedelta(hours=9))
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

BUCKET_NAME = os.getenv("BUCKET_NAME")

# ZIPハンドラーのインスタンス作成
zip_handler_instance = ZipHandler()  # インスタンスを作成

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

@bp.route('/colors', methods=['GET', 'POST'])
def colors():
    if request.method == 'POST':
        return colors_image_upload()
    return render_template('main/colors.html')

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
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

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
        print("s3_files:", s3_files)

    except Exception as e:
        flash(f"S3ファイル一覧取得中にエラー: {str(e)}", "error")

    return render_template(
        'main/ugu_box.html')

zip_handler = ZipHandler()

@bp.route('/ugu_box/upload', methods=['POST'])
def ugu_box_upload():
    files = request.files.getlist('files[]')
    
    if not files:
        return jsonify({"status": "error", "message": "ファイルが選択されていません"}), 400

    try:
        result, temp_dir = zip_handler.process_files(files)

        if isinstance(result, list):
            # 圧縮していない → 複数ファイル（リスト）アップロード
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

        else:
            # 圧縮済みのZIPファイルパスが返ってきた
            zip_filename = os.path.basename(result)
            s3_key = f"ugu_box/{zip_filename}"
            with open(result, 'rb') as f:
                s3.upload_fileobj(f, BUCKET_NAME, s3_key)
            
            # 一時ZIPファイル削除（任意）
            os.remove(result)

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
        # 'meziro/' フォルダのオブジェクト一覧を取得
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix='meziro/')
        # LastModifiedでソートするためにリストに変換
        contents = response.get('Contents', [])
        # LastModifiedの降順（新しい順）でソート
        contents.sort(key=lambda x: x['LastModified'], reverse=True)
        
        for obj in contents:
            key = obj['Key']
            filename = os.path.basename(key)
            if filename:  # フォルダ名を除外
                # 署名付きURLを生成（1週間有効）
                file_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': BUCKET_NAME, 'Key': key},
                    ExpiresIn=604800  # 1週間（604800秒）有効
                )
                s3_files.append({
                    'filename': filename, 
                    'url': file_url,                    
                    'last_modified': obj['LastModified'].astimezone(JST).strftime('%Y-%m-%d %H:%M'),
                    'key': key  # 削除時に使用するため保存
                })
        print("s3_files:", s3_files)

    except Exception as e:
        flash(f"S3ファイル一覧取得中にエラー: {str(e)}", "error")

    return render_template(
        'main/meziro.html',  # MEZIROオリジナルのテンプレートを使用
        s3_files=s3_files
    )

@bp.route('/meziro_upload', methods=['POST'])
def meziro_upload():    
    # print("Form data received:", dict(request.form))
    # print("Files received:", [f.filename for f in request.files.getlist('files[]')])
    # print("Environment variables:", {
    #     'BUCKET_NAME': os.getenv('BUCKET_NAME'),
    #     'AWS_REGION': os.getenv('AWS_REGION')
    # })

    message = request.form.get('userMessage')
    if not message:
        return jsonify({'error': 'メッセージが入力されていません'}), 400

    if 'files[]' not in request.files:
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    files = request.files.getlist('files[]')
    if not files or files[0].filename == '':
        return jsonify({'error': 'ファイルが選択されていません'}), 400

    uploaded_urls = []
    numbered_ids = []
    
    # DynamoDBから次の受付番号を取得
    session_id = get_next_sequence_number()
    # 管理番号として6桁のゼロ埋め形式に
    id_str = f"{session_id:05d}"  # 例: 000001, 000002, ...
    
    try:
        result, temp_dir = zip_handler_instance.process_files(files)
        print(f"process_files result: {result}, type: {type(result)}")  # デバッグ用
        print(f"Number of files: {len(files)}")  # デバッグ用

        if isinstance(result, list):  # 圧縮していない場合
            for index, file_path in enumerate(result, start=1):
                original_filename = os.path.basename(file_path)
                safe_filename = sanitize_filename(original_filename)
                
                # 管理番号とファイル番号を組み合わせた名前
                numbered_filename = f"{id_str}_{index:03d}_{safe_filename}"
                s3_key = f"meziro/{numbered_filename}"
                s3_key = get_unique_filename(os.getenv("BUCKET_NAME"), s3_key)

                with open(file_path, 'rb') as f:
                    s3.upload_fileobj(
                        f,
                        os.getenv('BUCKET_NAME'),
                        s3_key,
                        ExtraArgs={'ContentType': 'application/octet-stream'}
                    )

                # 有効期限付きURLを生成
                presigned_url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': os.getenv('BUCKET_NAME'), 'Key': s3_key},
                    ExpiresIn=604800
                )

                uploaded_urls.append(presigned_url)
                numbered_ids.append(f"{id_str}_{index:03d}")
        else:  # 圧縮した場合（zipファイル）の処理
            zip_file_path = result
            print(f"Uploading zip file: {zip_file_path}")  # デバッグ用
            
            # 管理番号を含めたzipファイル名
            numbered_filename = f"{id_str}_files.zip"
            s3_key = f"meziro/{numbered_filename}"
            s3_key = get_unique_filename(os.getenv("BUCKET_NAME"), s3_key)

            with open(zip_file_path, 'rb') as f:
                s3.upload_fileobj(
                    f,
                    os.getenv('BUCKET_NAME'),
                    s3_key,
                    ExtraArgs={'ContentType': 'application/zip'}
                )

            # 有効期限付きURLを生成
            presigned_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': os.getenv('BUCKET_NAME'), 'Key': s3_key},
                ExpiresIn=604800
            )

            uploaded_urls.append(presigned_url)
            numbered_ids.append(id_str)
            
            # 一時ファイルの削除
            if os.path.exists(zip_file_path):
                os.remove(zip_file_path)

        # メール本文に署名付きURLを含める
        url_text = "\n".join(uploaded_urls)
        full_message = f"""ユーザーから以下のメッセージが届きました：

{message}

アップロードされたファイル（リンクは1週間有効です）：
{url_text}
"""

        msg = Message(
            subject=f"【仕事が来たよ】No.{id_str}",
            recipients=[os.getenv("MAIL_NOTIFICATION_RECIPIENT")],
            body=full_message
        )
        mail.send(msg)
        print("メール送信成功")

    except Exception as mail_error:
        import traceback
        print(f"メール送信失敗: {mail_error}")
        print(traceback.format_exc())  # スタックトレースを出力

    # 受付番号を表示
    if numbered_ids:
        message = f"アップロード完了 受付No.{id_str}"
    else:
        message = "アップロード成功（ファイルはありません）"

    return jsonify({'message': message, 'files': uploaded_urls})

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
# @bp.route('/meziro/delete', methods=['POST'])
# def meziro_delete():
#     try:
#         selected_files = request.form.getlist('selected_files')
        
#         if not selected_files:
#             flash("削除するファイルが選択されていません", "warning")
#             return redirect(url_for('main.meziro'))
        
#         deleted_count = 0
#         for key in selected_files:
#             # URLデコード
#             decoded_key = unquote(key)
            
#             # S3からファイル削除
#             s3.delete_object(
#                 Bucket=BUCKET_NAME,
#                 Key=decoded_key
#             )
#             deleted_count += 1
        
#         flash(f"{deleted_count}件のファイルを削除しました", "success")
#     except Exception as e:
#         flash(f"削除中にエラーが発生しました: {str(e)}", "danger")
    
#     return redirect(url_for('main.meziro'))

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
    image_size = (800, 800)
    image = Image.open(upload_image)
    image.thumbnail(image_size)
    image.save(filepath)
    return image_filename