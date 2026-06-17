from flask import (
    render_template, url_for, redirect, session,
    flash, request, abort, current_app  # ← current_app を追加
)

from flask_login import login_user, logout_user, login_required, current_user
from models.users import RegistrationForm, LoginForm, UpdateUserForm
from flask import Blueprint
from extensions import db

from types import SimpleNamespace
from models.common import AuthUser
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
@bp.route('/preregister', methods=['GET', 'POST'])
def preregister():
    if request.method == 'POST':
        clinic_name      = request.form.get('clinic_name', '').strip()
        director_name    = request.form.get('director_name', '').strip()
        phone            = request.form.get('phone', '').strip()
        email            = request.form.get('email', '').strip().lower()
        password         = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # 入力チェック
        if not all([clinic_name, director_name, phone, email, password]):
            flash('すべての項目を入力してください。', 'danger')
            return render_template('users/preregister.html')

        if password != password_confirm:
            flash('パスワードが一致しません。', 'danger')
            return render_template('users/preregister.html')

        if len(password) < 8:
            flash('パスワードは8文字以上で入力してください。', 'danger')
            return render_template('users/preregister.html')

        # メールアドレス重複チェック
        users_table = current_app.config["HOERO_USERS_TABLE"]
        existing = users_table.get_item(Key={"user_id": email}).get("Item")
        if existing:
            flash('このメールアドレスはすでに登録されています。', 'danger')
            return render_template('users/preregister.html')

        # アカウント作成
        from werkzeug.security import generate_password_hash
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "user_id":       email,
            "email":         email,
            "display_name":  clinic_name,
            "sender_name":   clinic_name,
            "full_name":     director_name,
            "phone":         phone,
            "password_hash": generate_password_hash(password),
            "administrator": 0,
            "created_at":    now,
            "updated_at":    now,
        }
        users_table.put_item(Item=item)

        # 管理者への通知メール
        try:
            from extensions import mail
            from flask_mail import Message
            admin_msg = Message(
                subject=f"【新規登録】{clinic_name}",
                recipients=["shibuya8020@gmail.com"],
                body=f"""新規アカウントが登録されました。

【医院名】{clinic_name}
【院長名】{director_name}
【電話番号】{phone}
【メールアドレス】{email}
【登録日時】{now}

--------------------------------
渋谷歯科技工所 自動通知
"""
            )
            mail.send(admin_msg)

            # 登録者への完了メール
            confirm_msg = Message(
                subject="【渋谷歯科技工所】アカウント登録が完了しました",
                recipients=[email],
                body=f"""{clinic_name} {director_name} 様

アカウント登録が完了しました。
以下のメールアドレスとご登録のパスワードでログインできます。

【ログインID（メールアドレス）】{email}

歯科技工物受付システムをすぐにご利用いただけます。

--------------------------------
渋谷歯科技工所
〒343-0845 埼玉県越谷市南越谷4-9-6 新越谷プラザビル203
TEL: 048-961-8151
email: shibuya8020@gmail.com
"""
            )
            mail.send(confirm_msg)
        except Exception as e:
            current_app.logger.error("登録完了メール送信失敗: %s", e)

        flash('アカウント登録が完了しました。ログインしてご利用ください。', 'success')
        return redirect(url_for('users.login'))

    return render_template('users/preregister.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('users.login'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if not current_user.is_authenticated or not current_user.is_administrator:
        abort(403)

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
        # email はログインIDのため更新不可（変更は管理者対応）
        item["full_name"]    = form.full_name.data
        item["sender_name"]  = form.sender_name.data
        item["phone"]        = form.phone.data
        item["postal_code"]  = form.postal_code.data
        item["prefecture"]   = form.prefecture.data
        item["address"]      = form.address.data
        item["building"]     = form.building.data
        if current_user.is_administrator:
            item["itero_clinic_name"] = form.itero_clinic_name.data or ""

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
        form.display_name.data      = item.get("display_name")
        form.email.data             = item.get("email")
        form.full_name.data         = item.get("full_name")
        form.sender_name.data       = item.get("sender_name")
        form.itero_clinic_name.data = item.get("itero_clinic_name", "")
        form.phone.data             = item.get("phone")
        form.postal_code.data       = item.get("postal_code")
        form.prefecture.data        = item.get("prefecture")
        form.address.data           = item.get("address")
        form.building.data          = item.get("building")

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

    dentists = item.get("dentists", [])

    return render_template('users/account.html', form=form, user=user, dentists=dentists)


@bp.route('/dentists/add', methods=['POST'])
@login_required
def dentist_add():
    """歯科医師を追加する（自分のアカウント or 管理者）"""
    target_user_id = request.form.get("target_user_id") or current_user.user_id

    if target_user_id != current_user.user_id and not current_user.is_administrator:
        abort(403)

    name = request.form.get("dentist_name", "").strip()
    if not name:
        flash("歯科医師名を入力してください。")
        return redirect(request.referrer or url_for("users.account_me"))

    users_table = current_app.config["HOERO_USERS_TABLE"]
    res = users_table.get_item(Key={"user_id": target_user_id})
    item = res.get("Item")
    if not item:
        abort(404)

    dentists = item.get("dentists", [])
    if name not in dentists:
        dentists.append(name)
        item["dentists"] = dentists
        users_table.put_item(Item=item)
        flash(f"「{name}」を追加しました。")
    else:
        flash(f"「{name}」はすでに登録されています。")

    if current_user.is_administrator and target_user_id != current_user.user_id:
        return redirect(url_for("users.account", user_id=target_user_id))
    return redirect(url_for("users.account_me"))


@bp.route('/dentists/remove', methods=['POST'])
@login_required
def dentist_remove():
    """歯科医師を削除する（自分のアカウント or 管理者）"""
    target_user_id = request.form.get("target_user_id") or current_user.user_id

    if target_user_id != current_user.user_id and not current_user.is_administrator:
        abort(403)

    name = request.form.get("dentist_name", "").strip()
    if not name:
        abort(400)

    users_table = current_app.config["HOERO_USERS_TABLE"]
    res = users_table.get_item(Key={"user_id": target_user_id})
    item = res.get("Item")
    if not item:
        abort(404)

    dentists = item.get("dentists", [])
    if name in dentists:
        dentists.remove(name)
        item["dentists"] = dentists
        users_table.put_item(Item=item)
        flash(f"「{name}」を削除しました。")

    if current_user.is_administrator and target_user_id != current_user.user_id:
        return redirect(url_for("users.account", user_id=target_user_id))
    return redirect(url_for("users.account_me"))


@bp.route('/<user_id>/account', methods=['GET', 'POST'])
@login_required
def account(user_id):
    if user_id != current_user.user_id and not current_user.is_administrator:
        abort(403)

    users_table = current_app.config["HOERO_USERS_TABLE"]
    res = users_table.get_item(Key={"user_id": user_id})
    item = res.get("Item")
    if not item:
        abort(404)

    form = UpdateUserForm(user_id=user_id)

    if form.validate_on_submit():
        item["display_name"]      = form.display_name.data
        # email はログインIDのため更新不可（変更は管理者対応）
        item["full_name"]         = form.full_name.data
        item["sender_name"]       = form.sender_name.data
        item["itero_clinic_name"] = form.itero_clinic_name.data or ""
        item["phone"]             = form.phone.data
        item["postal_code"]       = form.postal_code.data
        item["prefecture"]        = form.prefecture.data
        item["address"]           = form.address.data
        item["building"]          = form.building.data
        item["updated_at"]        = datetime.now(timezone.utc).isoformat()

        if form.password.data:
            item["password_hash"] = generate_password_hash(form.password.data)

        users_table.put_item(Item=item)
        flash('ユーザーアカウントが更新されました')
        return redirect(url_for('main.clinic_list'))

    elif request.method == 'GET':
        form.display_name.data      = item.get("display_name")
        form.email.data             = item.get("email")
        form.full_name.data         = item.get("full_name")
        form.sender_name.data       = item.get("sender_name")
        form.itero_clinic_name.data = item.get("itero_clinic_name", "")
        form.phone.data             = item.get("phone")
        form.postal_code.data       = item.get("postal_code")
        form.prefecture.data        = item.get("prefecture")
        form.address.data           = item.get("address")
        form.building.data          = item.get("building")

    user = SimpleNamespace(
        user_id=item.get("user_id"),
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

    dentists = item.get("dentists", [])

    return render_template('users/account.html', form=form, user=user, dentists=dentists)
