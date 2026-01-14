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

with connection.cursor(pymysql.cursors.DictCursor) as cursor:
    cursor.execute("SELECT id, title, stl_filename, stl_file_path, gltf_file_path FROM stl_posts LIMIT 5")
    posts = cursor.fetchall()
    
    print("RDSのstl_postsテーブルの内容:")
    print("="*80)
    for post in posts:
        print(f"ID: {post['id']}")
        print(f"  title: {post['title']}")
        print(f"  stl_filename: {post['stl_filename']}")
        print(f"  stl_file_path: {post['stl_file_path']}")
        print(f"  gltf_file_path: {post['gltf_file_path']}")
        print()

connection.close()