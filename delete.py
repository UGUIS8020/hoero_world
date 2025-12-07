from app import flask_app, db

with flask_app.app_context():
    db.session.execute(db.text("DROP TABLE IF EXISTS inquiry"))
    db.session.commit()
    print("inquiry テーブルを削除しました")