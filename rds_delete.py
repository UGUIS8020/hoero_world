# rds_truncate_blog.py
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

connection = pymysql.connect(
    host='127.0.0.1',
    port=3307,
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)

try:
    with connection.cursor() as cursor:
        # 外部キー制約を一時的にオフ
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

        # ① 先に子テーブル（blog_post）を空にする
        cursor.execute("TRUNCATE TABLE blog_post")

        # ② 親テーブル（blog_category）も空にする
        cursor.execute("TRUNCATE TABLE blog_category")

        # 外部キー制約を元に戻す
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

    connection.commit()
    print("blog_post と blog_category のレコードをすべて削除しました。")

finally:
    connection.close()
