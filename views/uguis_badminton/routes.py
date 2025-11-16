from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from . import uguis_badminton_bp
from .uguis_badminton_utils import get_schedules_with_formatting
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, jsonify, current_app
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, ValidationError
from datetime import datetime
import random
from flask import render_template, url_for, flash
from . import uguis_badminton_bp
from flask import request, jsonify
from flask_login import login_required, current_user
from botocore.exceptions import ClientError
from flask_caching import Cache
import logging
import os
import pytz
import boto3
from datetime import timedelta
from .forms import LoginForm, User, UpdateUserForm, TempRegistrationForm
import time
from urllib.parse import urlparse, urljoin

from dotenv import load_dotenv

# log = logging.getLogger('werkzeug')
# log.setLevel(logging.WARNING)
# logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Flask-Login用
login_manager = LoginManager()
cache = Cache()

def create_app():
    """アプリケーションの初期化と設定"""
    try:        
        load_dotenv()
        
        # Flaskアプリケーションの作成
        app = Flask(__name__)               
        
        # Secret Keyの設定
        app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24))
        
          # セッションの永続化設定を追加
        app.config.update(
            PERMANENT_SESSION_LIFETIME = timedelta(days=30),  # セッション有効期限
            SESSION_PERMANENT = True,  # セッションを永続化
            SESSION_TYPE = 'filesystem',  # セッションの保存方式
            SESSION_COOKIE_SECURE = False,  
            SESSION_COOKIE_HTTPONLY = True,  # JavaScriptからのアクセスを防止
            SESSION_COOKIE_SAMESITE = 'Lax'  # クロスサイトリクエスト制限
        )
        
        # キャッシュの設定と初期化
        app.config['CACHE_TYPE'] = 'SimpleCache'
        app.config['CACHE_DEFAULT_TIMEOUT'] = 600
        app.config['CACHE_THRESHOLD'] = 900
        app.config['CACHE_KEY_PREFIX'] = 'uguis_'

        # 既存のcacheオブジェクトを初期化
        cache.init_app(app)
    
        logger.info("Cache initialized with SimpleCache")                 
       

        # AWS認証情報の設定
        aws_credentials = {
            'aws_access_key_id': os.getenv("AWS_ACCESS_KEY_ID"),
            'aws_secret_access_key': os.getenv("AWS_SECRET_ACCESS_KEY"),
            'region_name': os.getenv("AWS_REGION", "us-east-1")
        }

        # 必須環境変数のチェック
        required_env_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET", "TABLE_NAME_USER", "TABLE_NAME_SCHEDULE","TABLE_NAME_BOARD"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

         # 必須環境変数をFlaskの設定に追加
        app.config["S3_BUCKET"] = os.getenv("S3_BUCKET", "default-bucket-name")
        app.config["AWS_REGION"] = os.getenv("AWS_REGION")
        app.config['S3_LOCATION'] = f"https://{app.config['S3_BUCKET']}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/"
        print(f"S3_BUCKET: {app.config['S3_BUCKET']}")  # デバッグ用      

        # AWSクライアントの初期化
        app.s3 = boto3.client('s3', **aws_credentials)
        app.dynamodb = boto3.resource('dynamodb', **aws_credentials)

        # DynamoDBテーブルの設定
        app.table_name = os.getenv("TABLE_NAME_USER")
        app.table_name_board = os.getenv("TABLE_NAME_BOARD")
        app.table_name_schedule = os.getenv("TABLE_NAME_SCHEDULE")
        app.table = app.dynamodb.Table(app.table_name)
        app.table_board = app.dynamodb.Table(app.table_name_board)
        app.table_schedule = app.dynamodb.Table(app.table_name_schedule)

        # Flask-Loginの設定
        login_manager.init_app(app)
        login_manager.session_protection = "strong"
        login_manager.login_view = 'login'
        login_manager.login_message = 'このページにアクセスするにはログインが必要です。'

        # DynamoDBテーブルの初期化（init_tablesの実装が必要）
        # init_tables()

        logger.info("Application initialized successfully")
        return app

    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")
        raise

def tokyo_time():
    return datetime.now(pytz.timezone('Asia/Tokyo'))

@uguis_badminton_bp.route('/login', methods=['GET', 'POST'])
def login():

    if current_user.is_authenticated:
        return redirect(url_for('uguis_badminton.index')) 

    # form = LoginForm(dynamodb_table=app.table)
    form = LoginForm()
    if form.validate_on_submit():
        try:            
            # メールアドレスでユーザーを取得
            response = current_app.table.query(
                IndexName='email-index',
                KeyConditionExpression='email = :email',
                ExpressionAttributeValues={
                    ':email': form.email.data.lower()
                }
            )
            
            items = response.get('Items', [])
            user_data = items[0] if items else None
            
            if not user_data:
                current_app.logger.warning(f"No user found for email: {form.email.data}")
                flash('メールアドレスまたはパスワードが正しくありません。', 'error')
                return render_template('uguis_badminton/login.html', form=form)           

            try:
                user = User(
                    user_id=user_data['user#user_id'],
                    display_name=user_data['display_name'],
                    user_name=user_data['user_name'],
                    furigana=user_data.get('furigana', None),
                    email=user_data['email'],
                    password_hash=user_data['password'],
                    gender=user_data['gender'],
                    date_of_birth=user_data.get('date_of_birth', None),
                    post_code=user_data.get('post_code', None),
                    address=user_data.get('address',None),
                    phone=user_data.get('phone', None),
                    guardian_name=user_data.get('guardian_name', None),  
                    emergency_phone=user_data.get('emergency_phone', None), 
                    badminton_experience=user_data.get('badminton_experience', None),
                    administrator=user_data['administrator'],
                    organization=user_data.get('organization', 'other')
                    
                    
                )
                                
            except KeyError as e:
                current_app.logger.error(f"Error creating user object: {str(e)}")
                flash('ユーザーデータの読み込みに失敗しました。', 'error')
                return render_template('uguis_badminton/login.html', form=form)

            if not hasattr(user, 'check_password'):
                current_app.logger.error("User object missing check_password method")
                flash('ログイン処理中にエラーが発生しました。', 'error')
                return render_template('uguis_badminton/login.html', form=form)

            if user.check_password(form.password.data):
                session.permanent = True  # セッションを永続化
                login_user(user, remember=True)  # 常にremember=Trueに設定
                
                flash('ログインに成功しました。', 'success')
                
                next_page = request.args.get('next')
                if not next_page or not is_safe_url(next_page):
                    next_page = url_for('index')
                return redirect(next_page)            
                        
            current_app.logger.warning(f"Invalid password attempt for email: {form.email.data}")
            time.sleep(random.uniform(0.1, 0.3))
            flash('メールアドレスまたはパスワードが正しくありません。', 'error')
                
        except Exception as e:
            current_app.logger.error(f"Login error: {str(e)}")
            flash('ログイン処理中にエラーが発生しました。', 'error')
    
    return render_template('uguis_badminton/login.html', form=form)

@uguis_badminton_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            current_time = datetime.now().isoformat()
            hashed_password = generate_password_hash(form.password.data, method='pbkdf2:sha256')
            user_id = str(uuid.uuid4())          

            table = current_app.dynamodb.Table(app.table_name) 
            posts_table = current_app.dynamodb.Table('posts')  # 投稿用テーブル

            # メールアドレスの重複チェック用のクエリ
            email_check = table.query(
                IndexName='email-index',
                KeyConditionExpression='email = :email',
                ExpressionAttributeValues={
                    ':email': form.email.data
                }
            )

            if email_check.get('Items'):
                current_app.logger.warning(f"Duplicate email registration attempt: {form.email.data}")
                flash('このメールアドレスは既に登録されています。', 'error')
                return redirect(url_for('signup'))         

            current_app.table.put_item(
                Item={
                    "user#user_id": user_id,                    
                    "address": form.address.data,
                    "administrator": False,
                    "created_at": current_time,
                    "date_of_birth": form.date_of_birth.data.strftime('%Y-%m-%d'),
                    "display_name": form.display_name.data,
                    "email": form.email.data,
                    "furigana": form.furigana.data,
                    "gender": form.gender.data,
                    "password": hashed_password,
                    "phone": form.phone.data,
                    "post_code": form.post_code.data,
                    "updated_at": current_time,
                    "user_name": form.user_name.data,
                    "guardian_name": form.guardian_name.data,
                    "emergency_phone": form.emergency_phone.data,
                    "badminton_experience": form.badminton_experience.data,
                    "organization": form.organization.data,
                    # プロフィール用の追加フィールド
                    "bio": "",  # 自己紹介
                    "profile_image_url": "",  # プロフィール画像URL
                    "followers_count": 0,  # フォロワー数
                    "following_count": 0,  # フォロー数
                    "posts_count": 0  # 投稿数
                },
                ConditionExpression='attribute_not_exists(#user_id)',
                ExpressionAttributeNames={ "#user_id": "user#user_id"
                }
            )

            posts_table.put_item(
                Item={
                    'PK': f"USER#{user_id}",
                    'SK': 'TIMELINE#DATA',
                    'user_id': user_id,
                    'created_at': current_time,
                    'updated_at': current_time,
                    'last_post_time': None
                }
            )           
            

            # ログ出力を詳細に
            current_app.logger.info(f"New user created - ID: {user_id}, Organization: {form.organization.data}, Email: {form.email.data}")
            
            # 成功メッセージ
            flash('アカウントが作成されました！ログインしてください。', 'success')
            return redirect(url_for('login'))
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            current_app.logger.error(f"DynamoDB error - Code: {error_code}, Message: {error_message}")
            
            if error_code == 'ConditionalCheckFailedException':
                flash('このメールアドレスは既に登録されています。', 'error')
            elif error_code == 'ValidationException':
                flash('入力データが無効です。', 'error')
            elif error_code == 'ResourceNotFoundException':
                flash('システムエラーが発生しました。', 'error')
                app.logger.critical(f"DynamoDB table not found: {app.table_name}")
            else:
                flash('アカウント作成中にエラーが発生しました。', 'error')
                
            return redirect(url_for('signup'))
        
        except Exception as e:
            current_app.logger.error(f"Unexpected error during signup: {str(e)}", exc_info=True)
            flash('予期せぬエラーが発生しました。時間をおいて再度お試しください。', 'error')
            return redirect(url_for('signup'))
            
    # フォームのバリデーションエラーの場合
    if form.errors:
        current_app.logger.warning(f"Form validation errors: {form.errors}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{form[field].label.text}: {error}', 'error')
    
    return render_template('uguis_badminton/signup.html', form=form) 

# セキュアなリダイレクト先かを確認する関数
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@uguis_badminton_bp.route("/", methods=['GET'])
@uguis_badminton_bp.route("/index", methods=['GET'])
def index():
   try:      
       schedules = get_schedules_with_formatting()
       
       image_files = [
           'uguis_badminton/images/top001.jpg',
           'uguis_badminton/images/top002.jpg',
           'uguis_badminton/images/top003.jpg',
           'uguis_badminton/images/top004.jpg',
           'uguis_badminton/images/top005.jpg'           
       ]
       
       selected_image = random.choice(image_files)
       
       return render_template("uguis_badminton/index.html",
                            schedules=schedules,
                            selected_image=selected_image,
                            current_user={'is_authenticated': False, 'id': None},
                            canonical=url_for('uguis_badminton.index', _external=True))
       
   except Exception as e:        
       return render_template("uguis_badminton/index.html", 
                            schedules=[], 
                            selected_image='uguis_badminton/images/top001.jpg',
                            current_user={'is_authenticated': False, 'id': None})

# 必要に応じて他のルートも追加
@uguis_badminton_bp.route('/about')
def about():
    return render_template('uguis_badminton/about.html')

@uguis_badminton_bp.route("/bad_manager")
def bad_manager():
    return render_template("uguis_badminton/bad_manager.html")

@uguis_badminton_bp.route('/schedules')
def get_schedules():
    schedules = get_schedules_with_formatting()
    return jsonify(schedules)

@uguis_badminton_bp.app_template_filter('format_date')
def format_date(value):
    """日付を 'MM/DD' 形式にフォーマット"""
    try:
        date_obj = datetime.fromisoformat(value)  # ISO 形式から日付オブジェクトに変換
        return date_obj.strftime('%m/%d')        # MM/DD フォーマットに変換
    except ValueError:
        return value  # 変換できない場合はそのまま返す
    
@uguis_badminton_bp.route('/schedule/<string:schedule_id>/join', methods=['POST'])
@login_required
def join_schedule(schedule_id):
    try:
        # リクエストデータの取得
        data = request.get_json()
        date = data.get('date')

        if not date:
            current_app.logger.warning(f"'date' is not provided for schedule_id={schedule_id}")
            return jsonify({'status': 'error', 'message': '日付が不足しています。'}), 400

        # スケジュールの取得
        schedule_table = current_app.dynamodb.Table(current_app.table_name_schedule)
        response = schedule_table.get_item(
            Key={
                'schedule_id': schedule_id,
                'date': date
            }
        )
        schedule = response.get('Item')
        if not schedule:
            return jsonify({'status': 'error', 'message': 'スケジュールが見つかりません。'}), 404

        # 参加者リストの更新
        participants = schedule.get('participants', [])
        if current_user.id in participants:
            participants.remove(current_user.id)
            message = "参加をキャンセルしました"
            is_joining = False
        else:
            participants.append(current_user.id)
            message = "参加登録が完了しました！"
            is_joining = True

        # DynamoDB の更新
        schedule_table.update_item(
            Key={
                'schedule_id': schedule_id,
                'date': date
            },
            UpdateExpression="SET participants = :participants, participants_count = :count",
            ExpressionAttributeValues={
                ':participants': participants,
                ':count': len(participants)
            }
        )

        # キャッシュのリセット
        cache.delete_memoized(get_schedules_with_formatting)

        # 成功レスポンス
        return jsonify({
            'status': 'success',
            'message': message,
            'is_joining': is_joining,
            'participants': participants,
            'participants_count': len(participants)
        })

    except ClientError as e:
        current_app.logger.error(f"DynamoDB ClientError: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'データベースエラーが発生しました。'}), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error in join_schedule: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': '予期しないエラーが発生しました。'}), 500
    
# プロフィール表示用
@uguis_badminton_bp.route('/user/<string:user_id>')
def user_profile(user_id):
    try:
        table = current_app.dynamodb.Table(current_app.table_name)
        response = table.get_item(Key={'user#user_id': user_id})
        user = response.get('Item')

        if not user:
            abort(404)

        # 投稿データの取得を追加
        posts_table = current_app.dynamodb.Table('posts')
        posts_response = posts_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ':pk': f"USER#{user_id}",
                ':sk_prefix': 'METADATA#'
            }
        )
        posts = posts_response.get('Items', [])

        return render_template('user_profile.html', user=user, posts=posts)

    except Exception as e:
        current_app.logger.error(f"Error loading profile: {str(e)}")
        flash('プロフィールの読み込み中にエラーが発生しました', 'error')
        return redirect(url_for('index'))
