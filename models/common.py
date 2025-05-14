from datetime import datetime
from pytz import timezone
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
        return BlogPost.query.filter_by(user_id=userid).count()

class BlogPost(db.Model):
    __tablename__ = 'blog_post'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    category_id = db.Column(db.Integer, db.ForeignKey('blog_category.id'))
    date = db.Column(db.DateTime, default=datetime.now(timezone('Asia/Tokyo')))
    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    summary = db.Column(db.String(140))
    featured_image = db.Column(db.String(140))

    def __init__(self, title, text, featured_image, user_id, category_id, summary):
        self.title = title
        self.text = text
        self.featured_image = featured_image
        self.user_id = user_id
        self.category_id = category_id
        self.summary = summary

    def __repr__(self):
        return f"PostID: {self.id}, Title: {self.title}, Author: {self.author} \n"

class BlogCategory(db.Model):
    __tablename__ = 'blog_category'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(140))
    posts = db.relationship('BlogPost', backref='blogcategory', lazy='dynamic')

    def __init__(self, category):
        self.category = category
    
    def __repr__(self):
        return f"CategoryID: {self.id}, CategoryName: {self.category} \n"

    def count_posts(self, id):
        return BlogPost.query.filter_by(category_id=id).count()

class Inquiry(db.Model):
    __tablename__ = 'inquiry'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64))
    email = db.Column(db.String(64))
    title = db.Column(db.String(140))
    text = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.now(timezone('Asia/Tokyo')))

    def __init__(self, name, email, title, text):
        self.name = name
        self.email = email
        self.title = title
        self.text = text

    def __repr__(self):
        return f"InquiryID: {self.id}, Name: {self.name}, Text: {self.text} \n"
    
class STLPost(db.Model):
    __tablename__ = 'stl_posts'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=True)
    stl_filename = db.Column(db.String(255), nullable=True)
    stl_file_path = db.Column(db.String(255), nullable=True)  
    gltf_file_path = db.Column(db.String(255), nullable=True)      
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # リレーションシップ
    author = db.relationship('User', backref=db.backref('stl_posts', lazy='dynamic'))

class STLComment(db.Model):
    __tablename__ = 'stl_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    post_id = db.Column(db.Integer, db.ForeignKey('stl_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('stl_comments.id'), nullable=True)
    
    # リレーションシップ
    post = db.relationship('STLPost', backref=db.backref('comments', lazy='dynamic'))
    author = db.relationship('User', backref=db.backref('stl_comments', lazy='dynamic'))
    parent_comment = db.relationship('STLComment', remote_side=[id], backref='replies')

class STLLike(db.Model):
    __tablename__ = 'stl_likes'
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('stl_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # リレーションシップ
    post = db.relationship('STLPost', backref=db.backref('likes', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('stl_likes', lazy='dynamic'))
    
    def __repr__(self):
        return f'<STLPost {self.title}>'