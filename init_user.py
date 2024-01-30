from app import db,User
from app import app

with app.app_context():
    
    db.drop_all()
    db.create_all()

    user01 = User('admin_user01','admin_user01@test.com','1111',"1")
    user02 = User('test_user01','test_user01@test.com','1111',"0")

    db.session.add_all([user01,user02])

    db.session.commit()

    print(user01.id)
    print(user02.id)