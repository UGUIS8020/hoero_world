import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from extensions import db, login_manager
from dotenv import load_dotenv
from views.main import index
import sys

load_dotenv()

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return index()

flask_app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024
flask_app.config['SECRET_KEY'] = 'mysecretkey'
basedir = os.path.abspath(os.path.dirname(__file__))
flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
flask_app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
flask_app.config['DEBUG'] = True
os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(flask_app)
login_manager.init_app(flask_app)
Migrate(flask_app, db)

login_manager.login_view = 'users.login'

def localize_callback(*args, **kwargs):
    return 'このページにアクセスするには、ログインが必要です。'
login_manager.localize_callback = localize_callback

from sqlalchemy.engine import Engine
from sqlalchemy import event

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# ✅ ここで stdout に明示的に出力！
sys.stdout.write(f"DEBUG: AWS_REGION = {os.getenv('AWS_REGION')}\n")
sys.stdout.write(f"DEBUG: S3_BUCKET = {os.getenv('S3_BUCKET')}\n")
sys.stdout.flush()

from views.main import bp as main_bp
from views.users import bp as users_bp
from views.error_pages import bp as error_bp
from views.pages import bp as pages_bp

flask_app.register_blueprint(main_bp)
flask_app.register_blueprint(users_bp)
flask_app.register_blueprint(error_bp)
flask_app.register_blueprint(pages_bp)

if __name__ == '__main__':
    flask_app.run(debug=True)



