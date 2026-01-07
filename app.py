import os
import sys
import boto3

from flask import Flask
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

from extensions import login_manager, mail  # db, migrate を削除
from utils.common_utils import setup_scheduled_cleanup

# 1) .env を最初にロード
load_dotenv(dotenv_path="/var/www/hoero_world/.env")

# 2) Flask アプリ生成
flask_app = Flask(__name__)

# ===== 基本設定 =====
IS_PROD = (os.getenv("FLASK_ENV") == "production") or (os.getenv("ENV") == "prod") or (os.getenv("DEBUG") == "0")

if IS_PROD and not os.getenv('SECRET_KEY'):
    raise RuntimeError("SECRET_KEY is required in production")

flask_app.config['SECRET_KEY'] = (
    os.getenv('SECRET_KEY') if IS_PROD else os.getenv('SECRET_KEY', 'dev-secret-key')
)

flask_app.config['DEBUG'] = (os.getenv('DEBUG', '1') == '1') and not IS_PROD
flask_app.config['MAIL_DEBUG'] = False
flask_app.config['WTF_CSRF_TIME_LIMIT'] = 10800
flask_app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024

# CSRF
csrf = CSRFProtect()
csrf.init_app(flask_app)

# アップロードフォルダ
basedir = os.path.abspath(os.path.dirname(__file__))
flask_app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)

# メール設定
flask_app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
flask_app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 465))
flask_app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'True') == 'True'
flask_app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'False') == 'True'
flask_app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
flask_app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
flask_app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# DynamoDB設定
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

flask_app.config["AWS_REGION"] = AWS_REGION
flask_app.config["DENTAL_TABLE"] = dynamodb.Table(os.getenv("DENTAL_TABLE_NAME", "dental-news"))
flask_app.config["BLOG_POSTS_TABLE"] = dynamodb.Table(os.getenv("BLOG_POSTS_TABLE_NAME", "hoero-blog-posts"))
flask_app.config["HOERO_USERS_TABLE"] = dynamodb.Table(os.getenv("HOERO_USERS_TABLE_NAME", "hoero-users"))
flask_app.config["INQUIRY_TABLE"] = dynamodb.Table(os.getenv("INQUIRY_TABLE_NAME", "hoero-inquiry"))
flask_app.config["BLOG_CATEGORIES_TABLE"] = dynamodb.Table(os.getenv("BLOG_CATEGORIES_TABLE_NAME", "hoero-blog-categories"))
flask_app.config["STL_POSTS_TABLE"] = dynamodb.Table(os.getenv("STL_POSTS_TABLE_NAME", "hoero-stl-posts"))
flask_app.config["STL_COMMENTS_TABLE"] = dynamodb.Table(os.getenv("STL_COMMENTS_TABLE_NAME", "hoero-stl-comments"))
flask_app.config["STL_LIKES_TABLE"] = dynamodb.Table(os.getenv("STL_LIKES_TABLE_NAME", "hoero-stl-likes"))

# 拡張初期化
login_manager.init_app(flask_app)
mail.init_app(flask_app)

login_manager.login_view = 'users.login'
login_manager.localize_callback = lambda *args, **kwargs: 'このページにアクセスするには、ログインが必要です。'

# 定期処理
with flask_app.app_context():
    setup_scheduled_cleanup(flask_app)

# Blueprint登録
from views.main import bp as main_bp
from views.users import bp as users_bp
from views.error_pages import bp as error_bp
from views.pages import bp as pages_bp
from views.stl_board import bp as stl_board_bp
from views.sub_account import bp as sub_account_bp
from views.oralscan import bp as oralscan_bp
from views.news import bp as news_bp

flask_app.register_blueprint(main_bp)
flask_app.register_blueprint(users_bp)
flask_app.register_blueprint(error_bp)
flask_app.register_blueprint(pages_bp)
flask_app.register_blueprint(stl_board_bp)
flask_app.register_blueprint(sub_account_bp)
flask_app.register_blueprint(oralscan_bp)
flask_app.register_blueprint(news_bp)

if __name__ == "__main__":
    flask_app.run(debug=True)