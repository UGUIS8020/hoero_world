import os
import sys
import boto3

from flask import Flask
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect

from extensions import db, migrate, login_manager, mail
from utils.common_utils import setup_scheduled_cleanup

# 1) .env を最初にロード
load_dotenv(dotenv_path="/var/www/hoero_world/.env")

# 2) Flask アプリ生成
flask_app = Flask(__name__)

# ===== ここから基本設定（1回だけ） =====
# ===== ここから基本設定（1回だけ） =====
IS_PROD = (os.getenv("FLASK_ENV") == "production") or (os.getenv("ENV") == "prod") or (os.getenv("DEBUG") == "0")

if IS_PROD and not os.getenv('SECRET_KEY'):
    raise RuntimeError("SECRET_KEY is required in production")

flask_app.config['SECRET_KEY'] = (
    os.getenv('SECRET_KEY') if IS_PROD else os.getenv('SECRET_KEY', 'dev-secret-key')
)

flask_app.config['DEBUG'] = (os.getenv('DEBUG', '1') == '1') and not IS_PROD
flask_app.config['MAIL_DEBUG'] = False
flask_app.config['WTF_CSRF_TIME_LIMIT'] = 10800  # 秒
flask_app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024

# CSRF は SECRET_KEY 設定後に init
csrf = CSRFProtect()
csrf.init_app(flask_app)

# DB 接続
basedir = os.path.abspath(os.path.dirname(__file__))
flask_app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)
flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
flask_app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)

# 4) メール設定
flask_app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
flask_app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 465))
flask_app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'True') == 'True'
flask_app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'False') == 'True'
flask_app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
flask_app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
flask_app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# ★ 5) DynamoDB テーブル設定（ここでまとめてやる）
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
DENTAL_TABLE_NAME = os.getenv("DENTAL_TABLE_NAME", "dental-news")
BLOG_POSTS_TABLE_NAME = os.getenv("BLOG_POSTS_TABLE_NAME", "hoero-blog-posts")
HOERO_USERS_TABLE_NAME = os.getenv("HOERO_USERS_TABLE_NAME", "hoero-users")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

flask_app.config["AWS_REGION"] = AWS_REGION
flask_app.config["DENTAL_TABLE"] = dynamodb.Table(DENTAL_TABLE_NAME)
flask_app.config["BLOG_POSTS_TABLE_NAME"] = BLOG_POSTS_TABLE_NAME
flask_app.config["BLOG_POSTS_TABLE"] = dynamodb.Table(BLOG_POSTS_TABLE_NAME)
flask_app.config["HOERO_USERS_TABLE"] = dynamodb.Table(HOERO_USERS_TABLE_NAME)

# デバッグ出力
sys.stdout.write(f"DEBUG: AWS_REGION = {AWS_REGION}\n")
sys.stdout.write(f"DEBUG: BUCKET_NAME = {os.getenv('BUCKET_NAME')}\n")
sys.stdout.write(f"DEBUG: DENTAL_TABLE_NAME = {DENTAL_TABLE_NAME}\n")
sys.stdout.write(f"DEBUG: BLOG_POSTS_TABLE_NAME = {BLOG_POSTS_TABLE_NAME}\n")
sys.stdout.flush()

# 6) 拡張初期化
login_manager.init_app(flask_app)
db.init_app(flask_app)
migrate.init_app(flask_app, db)
mail.init_app(flask_app)

login_manager.login_view = 'users.login'
def localize_callback(*args, **kwargs):
    return 'このページにアクセスするには、ログインが必要です。'
login_manager.localize_callback = localize_callback

# 7) DB作成や定期処理
from models.common import *  # noqa
with flask_app.app_context():
    db.create_all()
    setup_scheduled_cleanup(flask_app)

# 8) Blueprint 登録
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
