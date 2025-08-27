from flask import Blueprint, render_template, request, url_for, redirect, flash, abort, jsonify, send_from_directory, current_app, request, session, send_file
from flask_login import login_required, current_user
from flask_mail import Mail, Message
from models.common import BlogCategory, BlogPost, Inquiry
from models.main import BlogCategoryForm, UpdateCategoryForm, BlogPostForm, BlogSearchForm, InquiryForm
from extensions import db
import boto3
import shutil
import os, tempfile, json, zipfile
from datetime import timezone, timedelta, datetime
from dotenv import load_dotenv
from PIL import Image
from flask import current_app
from urllib.parse import unquote
import io
import base64
from extensions import mail
from utils.common_utils import get_next_sequence_number, process_image, sanitize_filename, ZipHandler, cleanup_temp_files
from pytz import timezone
import requests

JST = timezone('Asia/Tokyo')
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

@bp.route('/')
def index():
    form = BlogSearchForm()
    # ブログ記事の取得
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    # 最新記事の取得
    # recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()
    recent_blog_posts = blog_posts.items[:5]

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
    if not current_user.is_administrator:
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
    if not current_user.is_administrator:
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
        try:
            print("フォーム検証成功")
            print(f"タイトル: {form.title.data}")
            print(f"カテゴリー: {form.category.data}")
            print(f"ユーザーID: {current_user.id}")
            
            if form.picture.data:
                pic = add_featured_image(form.picture.data)
                print(f"画像保存: {pic}")
            else:
                pic = ''
                print("画像なし")
            
            blog_post = BlogPost(
                title=form.title.data, 
                text=form.text.data, 
                featured_image=pic, 
                user_id=current_user.id, 
                category_id=form.category.data, 
                summary=form.summary.data
            )
            
            print("BlogPostオブジェクト作成成功")
            db.session.add(blog_post)
            print("セッションに追加")
            db.session.commit()
            print("コミット成功")
            
            flash('ブログ投稿が作成されました', 'success')
            return redirect(url_for('main.blog_maintenance'))
            
        except Exception as e:
            db.session.rollback()
            print(f"エラー発生: {e}")
            flash(f'エラーが発生しました: {str(e)}', 'danger')
    else:
        print("フォーム検証失敗")
        print(f"エラー: {form.errors}")
    
    return render_template('main/create_post.html', form=form)

@bp.route('/blog_maintenance')
@login_required
def blog_maintenance():
    page = request.args.get('page', 1, type=int)
    # authorリレーションを使用してeager loading
    blog_posts = BlogPost.query.options(
        db.joinedload(BlogPost.author)
    ).order_by(BlogPost.date.desc()).paginate(page=page, per_page=10)
    return render_template('main/blog_maintenance.html', blog_posts=blog_posts)

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
【製作物】{project_type}
【セット希望日時】{appointment_date} {appointment_hour}時

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

    # if request.method == 'POST':
    #     print("フォームデータ:", form.data)
    #     print("バリデーション結果:", form.validate())
    #     print("バリデーションエラー:", form.errors)

    if form.validate_on_submit():
        # ハニーポットチェック
        if request.form.get('website'):  # 空であるべき
            flash('不正な送信が検出されました。', 'danger')
            return redirect(url_for('main.inquiry'))  # 'main.'を追加
        
        # reCAPTCHA検証
        recaptcha_response = request.form.get('g-recaptcha-response')
        if not recaptcha_response or not verify_recaptcha(recaptcha_response):
            flash('reCAPTCHA認証が必要です。', 'danger')  # 'error' → 'danger'
            return render_template('main/inquiry.html', form=form, inquiry_id=inquiry_id)  # パス修正

        # DB保存
        inquiry = Inquiry(
            name=form.name.data,
            email=form.email.data,
            title=form.title.data,
            text=form.text.data
        )
        db.session.add(inquiry)
        db.session.commit()

        # メール送信（管理者 + 自動返信）
        try:
            # 管理者への通知
            msg = Message(
                subject=f"【お問い合わせ】{inquiry.title}",
                sender=os.getenv("MAIL_INQUIRY_SENDER"),
                recipients=[os.getenv("MAIL_NOTIFICATION_RECIPIENT")]
            )
            msg.body = f"""以下の内容でお問い合わせがありました：

■名前: {inquiry.name}
■メール: {inquiry.email}
■件名: {inquiry.title}
■内容:
{inquiry.text}

■日時: {datetime.now(timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M')}
■送信者IP: {request.environ.get('REMOTE_ADDR', 'unknown')}
"""
            mail.send(msg)

            # 🔹 自動返信メール（ユーザー向け）
            auto_reply = Message(
                subject="【渋谷歯科技工所】お問い合わせありがとうございました",
                sender=os.getenv("MAIL_INQUIRY_SENDER"),
                recipients=[inquiry.email]
            )
            auto_reply.body = f"""{inquiry.name} 様

このたびはお問い合わせいただきありがとうございます。
以下の内容で受け付けました。

件名: {inquiry.title}
内容:
{inquiry.text}

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
    if not current_user.is_administrator:
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