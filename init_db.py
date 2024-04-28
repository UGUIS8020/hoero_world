from company_blog import db
from company_blog.models import User

from app import app

with app.app_context():
    # db.drop_all()  # すべてのテーブルを削除
    db.create_all()  # データベーススキーマを再作成

    # password = "123"
    # password_hash = generate_password_hash(password) 
    user1 =User(username="Admin_User",email="admin_user@test.com", password="123", administrator="1")
    db.session.add(user1)
    db.session.commit()

    user1 =User(username="AAABBB01",email="aaabbb01@test.com", password="123", administrator="0")
    db.session.add(user1)
    db.session.commit()

    user1 =User(username="AAABBB02",email="aaabbb02@test.com", password="123", administrator="0")
    db.session.add(user1)
    db.session.commit()
    
    user1 =User(username="AAABBB03",email="aaabbb03@test.com", password="123", administrator="0")
    db.session.add(user1)
    db.session.commit()