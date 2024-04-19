from flask import Flask, render_template, url_for, redirect, session, flash, request, abort
from flask_wtf import FlaskForm
from wtforms import ValidationError,StringField, PasswordField,SubmitField
from wtforms.validators import DataRequired, Email, EqualTo
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from pytz import timezone

app = Flask(__name__, static_folder='./templates/images')

app.config['SECRET_KEY'] = 'mysecretkey'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
Migrate(app,db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(64), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    administrator = db.Column(db.String(1))
    post = db.relationship('BlogPost', backref='author', lazy='dynamic')

    def __init__(self, username, email, password, administrator):
        self.username = username
        self.email = email
        self.password = password
        self.administrator = administrator

    def __repr__(self):
        return f"Username: {self.username}"
    
    def check_password(self,password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def password(self):
        raise AttributeError('パスワードは読み取り専用です')
    
    @password.setter
    def password(self,password):
        self.password_hash = generate_password_hash(password)

    def is_administrator(self):
        if self.administrator == "1":
            return 1
        else:
            return 0

    
class BlogPost(db.Model):
    __tablename__ = 'blogposts'

    id = db.Column(db.Integer, primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    date = db.Column(db.DateTime, default=datetime.now(timezone('Asia/Tokyo')))
    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    summary = db.Column(db.String(140))
    featured_image = db.Column(db.String(140))

    def __init__(self, title, text, featured_image,user_id, summary):
        self.title = title
        self.text = text
        self.featured_image = featured_image
        self.user_id = user_id
        self.summary = summary        
    
    def __repr__(self):
        return f"PostID: {self.id},Title: {self.title},Author: {self.author} \n"
    

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    password = PasswordField('password', validators=[DataRequired()])
    submit = SubmitField('ログイン')


class RegistrationForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired()])
    email = StringField('メールアドレス', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    password = PasswordField('パスワード', validators=[DataRequired(), EqualTo('pass_confirm', message='パスワードが一致していません')])
    pass_confirm = PasswordField('パスワード(確認)', validators=[DataRequired()])
    submit = SubmitField('登録')

    def validate_username(self,field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('入力されたユーザー名はすでに使用されています')
        
    def validate_email(self,field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('入力されたメールアドレスはすでに使用されています')
        
class UpdateUserForm(FlaskForm):
    email = StringField("メールアドレス", validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    username = StringField("ユーザー名", validators=[DataRequired()])
    password = PasswordField("パスワード", validators=[EqualTo('pass_confirm', message='パスワードが一致していません')])
    pass_confirm = PasswordField("パスワード(確認)")
    submit = SubmitField('更新')

    def __init__(self,user_id,*args,**kwargs):
        super(UpdateUserForm,self).__init__(*args,**kwargs)
        self.id = user_id

    def validate_email(self,field):
        if User.query.filter(User.id != self.id).filter_by(email=field.data).first():
            raise ValidationError('入力されたメールアドレスはすでに使用されています')

    def validate_username(self,field):
        if User.query.filter(User.id != self.id).filter_by(username=field.data).first():
            raise ValidationError('入力されたユーザー名はすでに使用されています')

@app.errorhandler(403)
def error_403(error):
    return render_template('error_pages/403.html'),403

@app.errorhandler(404)
def error_404(error):
    return render_template('error_pages/404.html'),404

@app.route('/login', methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None:
            if user.check_password(form.password.data):
                login_user(user)
                next = request.args.get('next')
                if next == None or not next[0] == '/':
                    next = url_for('user_maintenance')
                return redirect(next)              
            else:
                flash('パスワード一致しません')
        else:
            flash('入力されたユーザーは存在しません')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
    

@app.route('/register', methods=['GET','POST'])
@login_required
def register(): 
    form = RegistrationForm()
    if not current_user.is_administrator():
        abort(403)
    if form.validate_on_submit():
        # session['email'] = form.email.data
        # session['username'] = form.username.data
        # session['password'] = form.password.data

        user = User(username=form.username.data,email=form.email.data, password=form.password.data, administrator="0")
        db.session.add(user)
        db.session.commit()

        flash('ユーザーが登録されました')
        return redirect(url_for('user_maintenance'))
    return render_template('register.html', form=form)

@app.route('/user_maintenance')
@login_required
def user_maintenance():
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.id).paginate(page=page, per_page=10)
    return render_template('user_maintenance.html', users=users)

@app.route('/<int:user_id>/account',methods=['GET','POST'])
@login_required
def account(user_id):
    user = User.query.get_or_404(user_id)

    if user.id != current_user.id and not current_user.is_administrator():
        abort(403)
    form = UpdateUserForm(user_id)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        if form.password.data:
            user.password = form.password.data
        db.session.commit()
        flash('ユーザー情報が更新されました')
        return redirect(url_for('user_maintenance'))
    elif request.method == 'GET':
        form.email.data = user.email
        form.username.data = user.username
    return render_template('account.html', form=form)

@app.route('/<int:user_id>/delete', methods=['GET','POST'])
@login_required
def delete_user(user_id):
    print("こんにちは")
    user = User.query.get_or_404(user_id)
    if not current_user.is_administrator():
        abort(403)
    if user.is_administrator():
        flash('管理者ユーザーは削除できません')
        return redirect(url_for('account', user_id=user_id))
    db.session.delete(user)
    db.session.commit()
    flash('ユーザーアカウントが削除されました')
    return redirect(url_for('user_maintenance'))


@app.errorhandler(404)
def error_404(error):
    return render_template("error_pages/404.html"),404

@app.route('/')
def home():
    return render_template('index.html', title = 'index.html')

@app.route('/upload')
def upload():
    return render_template('upload.html')

@app.route('/n001211')
def n001211():
    return render_template('n001211.html')

@app.route('/n001217')
def n001217():
    return render_template('n001217.html')

@app.route('/n001220')
def n001220():
    return render_template('n001220.html')

@app.route('/n001221')
def n001221():
    return render_template('n001221.html')

@app.route('/omake')
def omake():
    return render_template('omake.html')

@app.route('/form_test')
def form_test():
    return render_template('form_test.html')

@app.route('/form_test2')
def form_test2():
    return render_template('form_test2.html')

if __name__ == '__main__':
    app.run(debug=True)