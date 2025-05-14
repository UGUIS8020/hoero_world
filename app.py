import os
import sys
from flask import Flask
from flask_migrate import Migrate
from extensions import db, migrate, login_manager, mail
from dotenv import load_dotenv
from utils.common_utils import setup_scheduled_cleanup
from flask_wtf.csrf import CSRFProtect

load_dotenv()

flask_app = Flask(__name__)

csrf = CSRFProtect()
csrf.init_app(flask_app) 

flask_app.config['DEBUG'] = True
flask_app.config['WTF_CSRF_TIME_LIMIT'] = 10800  # 1時間（3600秒）
flask_app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024
flask_app.config['SECRET_KEY'] = 'mysecretkey'

basedir = os.path.abspath(os.path.dirname(__file__))
flask_app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
flask_app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')

# メール設定
flask_app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
flask_app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 465))
flask_app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'True') == 'True'
flask_app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
flask_app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
flask_app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
flask_app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager.init_app(flask_app)

db.init_app(flask_app)
migrate.init_app(flask_app, db)

mail.init_app(flask_app) 

login_manager.login_view = 'users.login'

def localize_callback(*args, **kwargs):
    return 'このページにアクセスするには、ログインが必要です。'
login_manager.localize_callback = localize_callback


# テーブル作成コード
from models.common import *

with flask_app.app_context():
    db.create_all()


from sqlalchemy.engine import Engine
from sqlalchemy import event

with flask_app.app_context():
    setup_scheduled_cleanup(flask_app)

# ここで stdout に明示的に出力！
sys.stdout.write(f"DEBUG: AWS_REGION = {os.getenv('AWS_REGION')}\n")
sys.stdout.write(f"DEBUG: BUCKET_NAME = {os.getenv('BUCKET_NAME')}\n")
sys.stdout.flush()

from views.main import bp as main_bp
from views.users import bp as users_bp
from views.error_pages import bp as error_bp
from views.pages import bp as pages_bp
from views.stl_board import bp as stl_board_bp 

flask_app.register_blueprint(main_bp)
flask_app.register_blueprint(users_bp)
flask_app.register_blueprint(error_bp)
flask_app.register_blueprint(pages_bp)
flask_app.register_blueprint(stl_board_bp)

if __name__ == '__main__':
    flask_app.run(debug=True)



