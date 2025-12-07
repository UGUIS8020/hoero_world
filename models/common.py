from datetime import datetime
from pytz import timezone
from zoneinfo import ZoneInfo
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin
from extensions import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(64))
    sender_name = db.Column(db.String(128))
    full_name = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(64), unique=True, index=True)
    
    # 住所情報
    postal_code = db.Column(db.String(8))  # 郵便番号
    prefecture = db.Column(db.String(10))  # 都道府県
    address = db.Column(db.String(100))    # 住所
    building = db.Column(db.String(50))    # 建物名、部屋番号
    
    password_hash = db.Column(db.String(256))  # ハッシュ長を増やす
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
        # パスワード検証時のデバッグ出力を追加
        result = check_password_hash(self.password_hash, password)
        print(f"パスワード検証: {result}, ハッシュ: {self.password_hash[:20]}...")
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
        """完全な住所を返すプロパティ"""
        parts = [
            f"〒{self.postal_code}" if self.postal_code else "",
            self.prefecture or "",
            self.address or "",
            self.building or ""
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

    # ⚠ ここは「評価時刻固定」にならないよう callable にする
    date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo('Asia/Tokyo')))

    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    summary = db.Column(db.String(140))
    featured_image = db.Column(db.String(140))

    # ← 唯一の関係として統一。backref は使わず back_populates を採用
    category = db.relationship('BlogCategory', back_populates='posts', lazy='joined')

    # （必要なら）
    # user = db.relationship('User', back_populates='posts')

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
    name = db.Column('category', db.String(140))  # 列名はcategoryのまま、属性名はnameに変更すると衝突が減ります

    # 片側は posts、相手側プロパティは category に統一
    posts = db.relationship(
        'BlogPost',
        back_populates='category',
        lazy='selectin',                 # or 'dynamic' が必要なら後述
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f"<BlogCategory id={self.id} name={self.name!r}>"

    # インスタンスメソッドなら id を引数に取らず self.id を使う
    def count_posts(self):
        from utils.blog_dynamo import list_posts_by_category
        return len(list_posts_by_category(self.id))

    
