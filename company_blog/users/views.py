from flask import render_template, url_for, redirect, session, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user
from company_blog import db
from company_blog.models import User
from company_blog.users.forms import LoginForm, RegistrationForm, UpdateUserForm
from flask import Blueprint

users = Blueprint('users', __name__)

@users.route('/login', methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None:
            if user.check_password(form.password.data):
                login_user(user)
                next = request.args.get('next')
                if next == None or not next[0] == '/':
                    next = url_for('users.user_maintenance')
                return redirect(next)              
            else:
                flash('パスワード一致しません')
        else:
            flash('入力されたユーザーは存在しません')
    return render_template('users/login.html', form=form)

@users.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('users.login'))
    

@users.route('/register', methods=['GET','POST'])
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
        return redirect(url_for('users.user_maintenance'))
    return render_template('users/register.html', form=form)

@users.route('/user_maintenance')
@login_required
def user_maintenance():
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.id).paginate(page=page, per_page=10)
    return render_template('users/user_maintenance.html', users=users)

@users.route('/<int:user_id>/account',methods=['GET','POST'])
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
        return redirect(url_for('users.user_maintenance'))
    elif request.method == 'GET':
        form.email.data = user.email
        form.username.data = user.username
    return render_template('users/account.html', form=form)

@users.route('/<int:user_id>/delete', methods=['GET','POST'])
@login_required
def delete_user(user_id):
    print("こんにちは")
    user = User.query.get_or_404(user_id)
    if not current_user.is_administrator():
        abort(403)
    if user.is_administrator():
        flash('管理者ユーザーは削除できません')
        return redirect(url_for('users.account', user_id=user_id))
    db.session.delete(user)
    db.session.commit()
    flash('ユーザーアカウントが削除されました')
    return redirect(url_for('users.user_maintenance'))


@users.errorhandler(404)
def error_404(error):
    return render_template("users/error_pages/404.html"),404

@users.route('/')
def home():
    return render_template('users/index.html', title = 'index.html')

@users.route('/upload')
def upload():
    return render_template('users/upload.html')

@users.route('/n001211')
def n001211():
    return render_template('users/n001211.html')

@users.route('/n001217')
def n001217():
    return render_template('users/n001217.html')

@users.route('/n001220')
def n001220():
    return render_template('users/n001220.html')

@users.route('/n001221')
def n001221():
    return render_template('users/n001221.html')

@users.route('/omake')
def omake():
    return render_template('users/omake.html')

@users.route('/form_test')
def form_test():
    return render_template('users/form_test.html')

@users.route('/form_test2')
def form_test2():
    return render_template('users/form_test2.html')
