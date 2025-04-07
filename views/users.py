from flask import render_template, url_for, redirect, session, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user
from models.common import User, BlogPost, BlogCategory
from models.users import RegistrationForm, LoginForm, UpdateUserForm
from models.main import BlogSearchForm
from flask import Blueprint
from extensions import db

bp = Blueprint('users', __name__, url_prefix='/users', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None:
            if user.check_password(form.password.data):                
                login_user(user, remember=True)
                next = request.args.get('next')
                if next == None or not next[0] == '/':
                    next = url_for('main.index')
                return redirect(next)
            else:
                flash('パスワードが一致しません')
        else:
            flash('入力されたユーザーは存在しません')

    return render_template('users/login.html', form=form)

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('users.login'))

@bp.route('/register', methods=['GET','POST'])
def register():
    print(current_user)
    form = RegistrationForm()
    if current_user.is_authenticated and not current_user.is_administrator():
        abort(403) 

    if form.validate_on_submit():
        # session['email'] = form.email.data
        # session['username'] = form.username.data
        # session['password'] = form.password.data
        user = User(email=form.email.data, username=form.username.data, password=form.password.data, administrator="0")
        db.session.add(user)
        db.session.commit()
        flash('ユーザーが登録されました')
        return redirect(url_for('users.login'))
    return render_template('users/register.html', form=form)

@bp.route('/user_maintenance')
@login_required
def user_maintenance():
    if not current_user.is_administrator():
        abort(403)
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.id).paginate(page=page, per_page=10)
    return render_template('users/user_maintenance.html', users=users)

@bp.route('/<int:user_id>/account', methods=['GET', 'POST'])
@login_required
def account(user_id):
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id and not current_user.is_administrator():
        abort(403)
    form = UpdateUserForm(user_id)
    if form.validate_on_submit():
        user.username = form.username.data
        user.email = form.email.data
        if form.password.data:
            user.password = form.password.data
        db.session.commit()
        flash('ユーザーアカウントが更新されました')
        return redirect(url_for('users.user_maintenance'))
    elif request.method == 'GET':
        form.username.data = user.username
        form.email.data = user.email
    return render_template('users/account.html', form=form)

@bp.route('/<int:user_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_user(user_id):
    user =User.query.get_or_404(user_id)
    if not current_user.is_administrator():
        abort(403)
    if user.is_administrator():
        flash('管理者は削除できません')
        return redirect(url_for('users.account', user_id=user_id))
    db.session.delete(user)
    db.session.commit()
    flash('ユーザーアカウントが削除されました')
    return redirect(url_for('users.user_maintenance'))

@bp.route('/<int:user_id>/user_posts')
@login_required
def user_posts(user_id):
    form = BlogSearchForm()
    # ユーザーの取得
    user = User.query.filter_by(id=user_id).first_or_404()

    # ブログ記事の取得
    page = request.args.get('page', 1, type=int)
    blog_posts = BlogPost.query.filter_by(user_id=user_id).order_by(BlogPost.id.desc()).paginate(page=page, per_page=10)

    # 最新記事の取得
    recent_blog_posts = BlogPost.query.order_by(BlogPost.id.desc()).limit(5).all()

    # カテゴリの取得
    blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()

    return render_template('users/index_users.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, user=user, form=form)    
