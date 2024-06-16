from app import db
from models.common import User

# db.drop_all()
db.create_all()

user1 = User(email="admin_user@test.com", username="Admin User", password="123", administrator="1")
db.session.add(user1)
db.session.commit()