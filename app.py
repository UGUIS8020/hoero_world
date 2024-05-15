import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

flask_app = Flask(__name__)

flask_app.config['SECRET_KEY'] = 'mysecretkey'
basedir = os.path.abspath(os.path.dirname(__file__))
flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(flask_app)
Migrate(flask_app, db)

login_manager = LoginManager()
login_manager.init_app(flask_app)
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

from main.views import bp as main_bp
from users.views import bp as users_bp
from error_pages.handlers import bp as error_bp

flask_app.register_blueprint(main_bp, url_prefix='/main')
flask_app.register_blueprint(users_bp, url_prefix='/users')
flask_app.register_blueprint(error_bp, url_prefix='/error')


if __name__ == '__main__':
    flask_app.run(debug=True)


