from flask import (
    render_template, url_for, redirect, session,
    flash, request, abort, current_app  # ← current_app を追加
)

from flask_login import login_user, logout_user, login_required, current_user
from models.dynamodb_category import list_blog_categories_all
from models.users import RegistrationForm, LoginForm, UpdateUserForm
from models.main import BlogSearchForm
from flask import Blueprint
from extensions import db

from utils.blog_dynamo import list_posts_by_user, list_recent_posts, paginate_posts
from types import SimpleNamespace
from models.common import AuthUser
from decimal import Decimal

from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

bp = Blueprint('users', __name__, url_prefix='/users', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    print(f"Form submitted: {request.method == 'POST'}")
    print(f"Form valid: {form.validate_on_submit()}")

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data

        print(f"Email entered: {email}")

        # DynamoDB hoero-users テーブル
        users_table = current_app.config["HOERO_USERS_TABLE"]

        res = users_table.get_item(Key={"user_id": email})
        item = res.get("Item")
        print(f"DynamoDB item found: {item is not None}")

        if not item:
            flash('入力されたユーザーは存在しません')
            return render_template('users/login.html', form=form)

        from decimal import Decimal
        admin_raw = item.get("administrator", 0)
        if isinstance(admin_raw, Decimal):
            admin_raw = int(admin_raw)
        is_admin = bool(admin_raw)

        user = AuthUser(
            user_id=item["user_id"],
            email=item.get("email"),
            display_name=item.get("display_name"),
            sender_name=item.get("sender_name"),
            full_name=item.get("full_name"),
            phone=item.get("phone"),
            postal_code=item.get("postal_code"),
            prefecture=item.get("prefecture"),
            address=item.get("address"),
            building=item.get("building"),
            administrator=is_admin,
            password_hash=item.get("password_hash"),
        )

        password_check = user.check_password(password)
        print(f"パスワード検証結果: {password_check}")

        if not password_check:
            flash('パスワードが一致しません')
            return render_template('users/login.html', form=form)

        print("DynamoDB のハッシュ検証でログイン成功")
        login_user(user, remember=True)

        next_url = request.args.get('next')
        if not next_url or not next_url.startswith('/'):
            next_url = url_for('main.index')
        return redirect(next_url)

    return render_template('users/login.html', form=form)
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('users.login'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated and not current_user.is_administrator:
        return redirect(url_for('main.index'))

    form = RegistrationForm()

    if form.validate_on_submit():
        table = current_app.config["HOERO_USERS_TABLE"]

        now = datetime.now(timezone.utc).isoformat()
        password_hash = generate_password_hash(form.password.data)

        item = {
            "user_id": form.email.data,      # ← ログインID = email
            "email": form.email.data,
            "display_name": form.display_name.data,
            "sender_name": form.sender_name.data or "",
            "full_name": form.full_name.data or "",
            "phone": form.phone.data or "",
            "postal_code": form.postal_code.data or "",
            "prefecture": form.prefecture.data or "",
            "address": form.address.data or "",
            "building": form.building.data or "",
            "password_hash": password_hash,
            "administrator": 0,
            "created_at": now,
            "updated_at": now,
        }

        table.put_item(Item=item)

        flash('ユーザー登録が完了しました。ログインしてください。', 'success')
        return redirect(url_for('users.login'))

    return render_template('users/register.html', form=form)

@bp.route('/user_maintenance')
@login_required
def user_maintenance():
    if not current_user.is_administrator:
        abort(403)

    # DynamoDB hoero-users テーブル
    users_table = current_app.config["HOERO_USERS_TABLE"]

    # ユーザー数は少ない前提なので、いったん全件 scan でOK
    resp = users_table.scan()
    items = resp.get("Items", [])

    # DynamoDBのitemをテンプレートで扱いやすい形に整形
    cleaned = []
    for it in items:
        admin_raw = it.get("administrator", 0)
        if isinstance(admin_raw, Decimal):
            admin_raw = int(admin_raw)

        # DynamoDB 上では user_id = email を想定
        uid = it.get("user_id")

        # 投稿数を数える関数を、このユーザー専用に持たせる
        def count_posts_for_this_user(target_uid):
            # list_posts_by_user が user_id (ここでは email) を受け取る前提
            return len(list_posts_by_user(target_uid))

        cleaned.append(
            SimpleNamespace(
                # ★ テンプレート互換用に id も持たせる（中身は user_id と同じ）
                id=uid,
                user_id=uid,
                email=it.get("email"),
                display_name=it.get("display_name"),
                full_name=it.get("full_name"),
                phone=it.get("phone"),
                administrator=bool(admin_raw),
                # ★ テンプレートの user.count_posts(user.id) に対応させる
                count_posts=count_posts_for_this_user,
            )
        )

    # 簡易ページネーション（RDSのpaginateっぽいオブジェクトを自前で作る）
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total = len(cleaned)

    start = (page - 1) * per_page
    end = start + per_page
    page_items = cleaned[start:end]

    has_next = end < total
    has_prev = start > 0

    users_page = SimpleNamespace(
        items=page_items,
        page=page,
        per_page=per_page,
        total=total,
        has_next=has_next,
        has_prev=has_prev,
        next_num=page + 1 if has_next else None,
        prev_num=page - 1 if has_prev else None,
        pages=(total + per_page - 1) // per_page if per_page else 1,
    )

    return render_template("users/user_maintenance.html", users=users_page)


@bp.route('/<user_id>/user_posts')
@login_required
def user_posts(user_id):
    form = BlogSearchForm()

    users_table = current_app.config["HOERO_USERS_TABLE"]
    resp = users_table.get_item(Key={"user_id": user_id})
    item = resp.get("Item")
    if not item:
        abort(404)

    user = SimpleNamespace(
        user_id=item["user_id"],
        display_name=item.get("display_name", ""),
        email=item.get("user_id", ""),
        sender_name=item.get("sender_name", ""),
    )

    page = request.args.get('page', 1, type=int)

    # ★ ユーザーの記事（user_id=email 前提）
    user_posts_items = list_posts_by_user(user_id)

    # ★ ここで各記事に「表示用の author_display_name」を付ける
    #    （テンプレが post.author_name を見ているなら、ここで上書きするのもあり）
    enriched = []
    for it in user_posts_items:
        it = dict(it)  # 念のためコピー

        # 最新のユーザー名を優先（users_tableのdisplay_name）
        it["author_name"] = item.get("display_name", it.get("author_name", "Unknown User"))

        enriched.append(it)

    blog_posts = paginate_posts(enriched, page=page, per_page=10)

    blog_categories = list_blog_categories_all()

    recent_items = list_recent_posts(limit=5)
    recent_blog_posts = [
        SimpleNamespace(
            post_id=str(it.get("post_id", "")),   # ★ intをやめる
            title=it.get("title", ""),
            featured_image=it.get("featured_image", ""),
        )
        for it in recent_items
    ]

    return render_template(
        'users/index_users.html',
        blog_posts=blog_posts,
        recent_blog_posts=recent_blog_posts,
        blog_categories=blog_categories,
        user=user,
        form=form,
    )    


@bp.route('/account', methods=['GET', 'POST'])
@login_required
def account_me():
    """
    現在ログイン中ユーザーの情報を、
    DynamoDB hoero-users から読み書きするアカウント編集画面。
    """
    email = getattr(current_user, "email", None)
    if not email:
        flash("ログイン情報にメールアドレスがありません。")
        return redirect(url_for("main.index"))

    # DynamoDB から現在のユーザー情報を取得
    users_table = current_app.config["HOERO_USERS_TABLE"]
    res = users_table.get_item(Key={"user_id": email})
    item = res.get("Item")
    if not item:
        flash("ユーザー情報が見つかりません。")
        return redirect(url_for("main.index"))

    # RDS用フォームをそのまま使う（バリデーションで user_id を使っているなら適宜調整）
    form = UpdateUserForm(user_id=email)

    if form.validate_on_submit():
        # フォームの内容で item を更新
        item["display_name"] = form.display_name.data
        item["email"]        = form.email.data
        item["full_name"]    = form.full_name.data
        item["sender_name"]  = form.sender_name.data
        item["phone"]        = form.phone.data
        item["postal_code"]  = form.postal_code.data
        item["prefecture"]   = form.prefecture.data
        item["address"]      = form.address.data
        item["building"]     = form.building.data

        # パスワードが入力されていたらハッシュ更新
        if form.password.data:
            from werkzeug.security import generate_password_hash
            item["password_hash"] = generate_password_hash(
                form.password.data,
                method="pbkdf2:sha256"
            )

        # DynamoDB に保存
        users_table.put_item(Item=item)

        flash("ユーザーアカウントが更新されました")
        return redirect(url_for("users.account_me"))

    elif request.method == 'GET':
        # 画面初期表示：フォームに現在の値をセット
        form.display_name.data = item.get("display_name")
        form.email.data        = item.get("email")
        form.full_name.data    = item.get("full_name")
        form.sender_name.data  = item.get("sender_name")
        form.phone.data        = item.get("phone")
        form.postal_code.data  = item.get("postal_code")
        form.prefecture.data   = item.get("prefecture")
        form.address.data      = item.get("address")
        form.building.data     = item.get("building")

    # テンプレートは昔と同じように user.xxx を使っているはずなので、
    # SimpleNamespace でそれっぽいオブジェクトを渡してあげる
    user = SimpleNamespace(
        display_name=item.get("display_name"),
        email=item.get("email"),
        full_name=item.get("full_name"),
        sender_name=item.get("sender_name"),
        phone=item.get("phone"),
        postal_code=item.get("postal_code"),
        prefecture=item.get("prefecture"),
        address=item.get("address"),
        building=item.get("building"),
    )

    return render_template('users/account.html', form=form, user=user)

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
