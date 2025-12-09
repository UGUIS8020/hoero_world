from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager


# =======================
# DynamoDB 用ログインユーザー
# =======================
class AuthUser(UserMixin):
    """
    Flask-Login が扱う「ログイン中のユーザー」オブジェクト。
    実体は DynamoDB hoero-users の1件。
    """
    def __init__(
        self,
        user_id,
        email=None,
        display_name=None,
        sender_name=None,
        full_name=None,
        phone=None,
        postal_code=None,
        prefecture=None,
        address=None,
        building=None,
        administrator=False,
        password_hash=None,
    ):
        self.user_id = user_id          # = hoero-users.user_id (= email)
        self.email = email
        self.display_name = display_name
        self.sender_name = sender_name
        self.full_name = full_name
        self.phone = phone
        self.postal_code = postal_code
        self.prefecture = prefecture
        self.address = address
        self.building = building
        self.administrator = administrator
        self.password_hash = password_hash

    @property
    def id(self):
        # Flask-Login がセッションに保存する ID
        return self.user_id

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_administrator(self) -> bool:
        return bool(self.administrator)


@login_manager.user_loader
def load_user(user_id: str):
    """
    セッションから user_id (= email) を受け取って、
    DynamoDB hoero-users からユーザーを復元する。
    """
    users_table = current_app.config["HOERO_USERS_TABLE"]

    res = users_table.get_item(Key={"user_id": user_id})
    item = res.get("Item")
    if not item:
        return None

    admin_raw = item.get("administrator", 0)
    if isinstance(admin_raw, Decimal):
        admin_raw = int(admin_raw)
    is_admin = bool(admin_raw)

    return AuthUser(
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


# =======================
# RDS (MySQL) 用のブログ関連モデル
# =======================

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(64))
    sender_name = db.Column(db.String(128))
    full_name = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(64), unique=True, index=True)

    postal_code = db.Column(db.String(8))   # 郵便番号
    prefecture = db.Column(db.String(10))   # 都道府県
    address = db.Column(db.String(100))     # 住所
    building = db.Column(db.String(50))     # 建物名、部屋番号

    password_hash = db.Column(db.String(256))
    administrator = db.Column(db.Boolean, default=False)

    post = db.relationship('BlogPost', backref='author', lazy='dynamic')

    def __init__(self, display_name, sender_name, full_name, phone, email,
                 postal_code, prefecture, address, building,
                 password, administrator=False):
        self.display_name = display_name
        self.sender_name = sender_name
        self.full_name = full_name
        self.phone = phone
        self.email = email
        self.postal_code = postal_code
        self.prefecture = prefecture
        self.address = address
        self.building = building
        self.password = password
        self.administrator = administrator

    def __repr__(self):
        return f"UserName: {self.display_name}"

    def check_password(self, password):
        result = check_password_hash(self.password_hash, password)
        print(f"RDS User パスワード検証: {result}, ハッシュ: {self.password_hash[:20]}...")
        return result

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    @property
    def is_administrator(self):
        return self.administrator

    @property
    def full_address(self):
        parts = [
            f"〒{self.postal_code}" if self.postal_code else "",
            self.prefecture or "",
            self.address or "",
            self.building or "",
        ]
        return " ".join(filter(None, parts))

    def count_posts(self, userid):
        from utils.blog_dynamo import list_posts_by_user
        return len(list_posts_by_user(userid))


class BlogPost(db.Model):
    __tablename__ = 'blog_post'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('blog_category.id'), index=True, nullable=False)

    date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo('Asia/Tokyo')))

    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    summary = db.Column(db.String(140))
    featured_image = db.Column(db.String(140))

    category = db.relationship('BlogCategory', back_populates='posts', lazy='joined')

    def __init__(self, title, text, featured_image, user_id, category_id, summary):
        self.title = title
        self.text = text
        self.featured_image = featured_image
        self.user_id = user_id
        self.category_id = category_id
        self.summary = summary

    def __repr__(self):
        return f"<BlogPost id={self.id} title={self.title!r}>"


class BlogCategory(db.Model):
    __tablename__ = 'blog_category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column('category', db.String(140))

    posts = db.relationship(
        'BlogPost',
        back_populates='category',
        lazy='selectin',
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f"<BlogCategory id={self.id} name={self.name!r}>"

    def count_posts(self):
        from utils.blog_dynamo import list_posts_by_category
        return len(list_posts_by_category(self.id))