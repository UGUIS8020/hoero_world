from flask import render_template, url_for, redirect, session, flash, request, abort
from flask_login import login_user, logout_user, login_required, current_user
from models.common import User, BlogPost
from models.dynamodb_category import list_blog_categories_all
from models.users import RegistrationForm, LoginForm, UpdateUserForm
from models.main import BlogSearchForm
from flask import Blueprint
from extensions import db

from utils.blog_dynamo import list_posts_by_user, list_recent_posts, paginate_posts
from types import SimpleNamespace

bp = Blueprint('users', __name__, url_prefix='/users', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    print(f"Form submitted: {request.method == 'POST'}")
    print(f"Form valid: {form.validate_on_submit()}")
    
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        print(f"Email entered: {form.email.data}")
        print(f"User found: {user is not None}")
        
        if user is not None:
            # ハッシュパスワード検証を使用
            password_check = user.check_password(form.password.data)
            print(f"パスワード検証結果: {password_check}")
            
            if password_check:
                print("ハッシュ検証でログイン成功")
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

@bp.route('/register', methods=['GET', 'POST'])
def register():
    # 管理者チェック部分も修正済み
    if current_user.is_authenticated and not current_user.is_administrator:
        return redirect(url_for('main.index'))
    
    form = RegistrationForm()
    
    if form.validate_on_submit():
        user = User(
            display_name=form.display_name.data,
            sender_name=form.sender_name.data,
            full_name=form.full_name.data,
            phone=form.phone.data,
            email=form.email.data,
            postal_code=form.postal_code.data,
            prefecture=form.prefecture.data,
            address=form.address.data,
            building=form.building.data,
            password=form.password.data
        )
        
        db.session.add(user)
        db.session.commit()
        flash('ユーザー登録が完了しました。ログインしてください。', 'success')
        return redirect(url_for('users.login'))
    
    return render_template('users/register.html', form=form)

@bp.route('/user_maintenance')
@login_required
def user_maintenance():
    if not current_user.is_administrator:
        abort(403)
    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.id).paginate(page=page, per_page=10)
    return render_template('users/user_maintenance.html', users=users)

@bp.route('/<int:user_id>/account', methods=['GET', 'POST'])
@login_required
def account(user_id):
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id and not current_user.is_administrator:
        abort(403)
    form = UpdateUserForm(user_id)
    if form.validate_on_submit():
        # 基本情報の更新
        user.display_name = form.display_name.data
        user.email = form.email.data
        user.full_name = form.full_name.data
        user.sender_name = form.sender_name.data
        user.phone = form.phone.data
        
        # 住所情報の更新
        user.postal_code = form.postal_code.data
        user.prefecture = form.prefecture.data
        user.address = form.address.data
        user.building = form.building.data
        
        # パスワードの更新（入力があれば）
        if form.password.data:
            user.password = form.password.data
            
        db.session.commit()
        flash('ユーザーアカウントが更新されました')
        return redirect(url_for('users.user_maintenance'))
    elif request.method == 'GET':
        # フォームに現在の値をセット
        form.display_name.data = user.display_name
        form.email.data = user.email
        form.full_name.data = user.full_name
        form.sender_name.data = user.sender_name
        form.phone.data = user.phone
        form.postal_code.data = user.postal_code
        form.prefecture.data = user.prefecture
        form.address.data = user.address
        form.building.data = user.building
        
    return render_template('users/account.html', form=form, user=user)

@bp.route('/<int:user_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_user(user_id):
    user =User.query.get_or_404(user_id)
    if not current_user.is_administrator:
        abort(403)
    if user.is_administrator:
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

    # DynamoDB からブログ記事を取得
    page = request.args.get('page', 1, type=int)
    user_posts_items = list_posts_by_user(user_id)
    blog_posts = paginate_posts(user_posts_items, page=page, per_page=10)

    # 最新記事
    recent_items = list_recent_posts(limit=5)
    recent_blog_posts = [
        SimpleNamespace(
            post_id=int(it.get("post_id")),
            title=it.get("title", ""),
            featured_image=it.get("featured_image", ""),
        )
        for it in recent_items
    ]

    # カテゴリの取得
    blog_categories = list_blog_categories_all()

    return render_template('users/index_users.html', blog_posts=blog_posts, recent_blog_posts=recent_blog_posts, blog_categories=blog_categories, user=user, form=form)    
