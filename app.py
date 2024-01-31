from flask import Flask, render_template,url_for,redirect,session,flash,request
from flask_wtf import FlaskForm
from wtforms import ValidationError,StringField,PasswordField,SubmitField
from wtforms.validators import DataRequired,Email,EqualTo

import os
from flask_migrate import Migrate
from datetime import datetime
from pytz import timezone
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, static_folder='./templates/images')

app.config['SECRET_KEY'] = 'mysecretkey'

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir,'data.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
Migrate(app,db)

from sqlalchemy.engine import Engine
from sqlalchemy import event

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer,primary_key=True)
    username = db.Column(db.String(64),unique=True,index=True)
    email = db.Column(db.String(64),unique=True,index=True)
    password_hash = db.Column(db.String(128))
    administrator = db.Column(db.String(1))
    post = db.relationship('BlogPost',backref='author',lazy='dynamic')

    def __init__(self,username,email,password_hash,administrator):
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.administrator = administrator

    def __repr__(self):
        return f"Username {self.username}"
    
class BlogPost(db.Model):
    __tablename__ = 'blog_post'
    id = db.Column(db.Integer,primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey('users.id'))
    date = db.Column(db.DateTime,default=datetime.now(timezone('Asia/Tokyo')))
    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    summary = db.Column(db.String(140))
    featured_image = db.Column(db.String(140))

    def __init__(self,title,text,featured_image,user_id,summary):
        self.title = title
        self.text = text
        self.featured_image = featured_image
        self.user_id = user_id
        self.summary = summary

    def __repr__(self):
        return f"PostID:{self.id},Title: {self.title}, Author: {self.author}\n"


    # def __repr__(self):
    #     return f"Title {self.title}"

class RegistrationForm(FlaskForm):
    username = StringField('ユーザー名',validators=[DataRequired()])
    email = StringField('メールアドレス', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    email_confirm = StringField('メールアドレス(確認)', validators=[DataRequired(), EqualTo('email', message='メールアドレスが一致しません')])
    password = PasswordField('パスワード', validators=[DataRequired(), EqualTo('pass_confirm', message='パスワードが一致しません')])
    pass_confirm = PasswordField('パスワード(確認)', validators=[DataRequired()])
    submit = SubmitField('登録')

    def validate_username(self,field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('入力されたユーザー名は既に使用されています')
    
    def validate_email(self,field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('入力されたメールアドレスは既に使用されています')
        
class UpdateUserForm(FlaskForm):
    username = StringField('ユーザー名',validators=[DataRequired()])
    email = StringField('メールアドレス', validators=[DataRequired(), Email(massage='正しいメールアドレスを入力してください')])
    password = PasswordField('パスワード', validators=[EqualTo('pass_confirm', message='パスワードが一致しません')]) 
    pass_confirm = PasswordField('パスワード(確認)')
    submit = SubmitField('更新')

    def __init__(self,user_id,*args,**kwargs):
        super(UpdateUserForm,self).__init__(*args,**kwargs)
        self.user_id = user_id


@app.route('/register',methods=['GET','POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        # session['email'] = form.email.data
        # session['username'] = form.username.data
        # session['password'] = form.password.data
        user = User(email=form.email.data, username=form.username.data,password_hash=form.password.data,administrator="0")
        db.session.add(user)
        db.session.commit()


        flash(f'アカウントが作成されました！','success')
        return redirect(url_for('user_maintenance'))
    return render_template('register.html',form=form)

@app.route('/user_maintenance')
def user_maintenance():
    page = request.args.get('page',1,type=int)
    users = User.query.order_by(User.id).paginate(page=page,per_page=10)
    return render_template('user_maintenance.html',users=users)

@app.route('/<int:user_id/account>')
def account(user_id):
    user = User.query.get_or_404(user_id, methods=['GET','POST'])
    form = UpdateUserForm(user_id)
    if form.validate_on_submit():
        user.username = form.username.data
        user.email = form.email.data
        if form.password.data:
            user.password_hash = form.password.data
        db.session.commit()
        flash(f'アカウントが更新されました！','success')
      
        return redirect(url_for('user_maintenance'))
    
    elif request.method == 'GET':
        form.username.data = user.username
        form.email.data = user.email

    return render_template('account.html',form=form)



@app.route('/account')
def account():
    return render_template('account.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.errorhandler(404)
def error_404(error):
    return render_template("error_pages/404.html"),404

@app.route('/')
def home():
    return render_template('index.html', title = 'index.html')

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

if __name__ == '__main__':
    app.run(debug=True)