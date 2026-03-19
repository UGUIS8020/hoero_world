import uuid
from datetime import datetime
from decimal import Decimal
from flask import current_app
from boto3.dynamodb.conditions import Attr


# ========== Posts ==========
def _posts_table():
    return current_app.config["STL_POSTS_TABLE"]


def create_stl_post(title, content, user_id,
                    stl_filename=None, stl_file_path=None,
                    youtube_url=None, youtube_id=None, youtube_embed_url=None,
                    image_file_path=None):  # ★追加
    """STL投稿を作成"""
    import uuid
    import datetime
    import time
    
    table = _posts_table()
    post_id = str(uuid.uuid4())
    created_at = datetime.datetime.utcnow().isoformat()
    created_at_ts = int(time.time())
    
    item = {
        "post_id": post_id,
        "user_id": user_id,
        "title": title,
        "content": content,
        "created_at": created_at,
        "created_at_ts": created_at_ts,
    }
    
    if stl_filename:
        item["stl_filename"] = stl_filename
    if stl_file_path:
        item["stl_file_path"] = stl_file_path
        item["gltf_file_path"] = stl_file_path
    
    # YouTube
    if youtube_url:
        item["youtube_url"] = youtube_url
    if youtube_id:
        item["youtube_id"] = youtube_id
    if youtube_embed_url:
        item["youtube_embed_url"] = youtube_embed_url

    # ★画像
    if image_file_path:
        item["image_file_path"] = image_file_path
    
    table.put_item(Item=item)
    return post_id


def get_stl_post_by_id(post_id):
    table = _posts_table()
    response = table.get_item(Key={"post_id": str(post_id)})
    return response.get("Item")


def list_stl_posts(limit=100):
    table = _posts_table()
    response = table.scan()
    items = response.get("Items", [])

    # STL or YouTube がある投稿だけ残す（どちらもない空投稿は除外）
    def has_media(it):
        return bool(it.get("stl_file_path")) or bool(it.get("youtube_id")) or bool(it.get("youtube_url")) or bool(it.get("youtube_embed_url"))

    items = [it for it in items if has_media(it)]

    # created_at_ts が無い古いデータは created_at で補完（安全側）
    def sort_key(x):
        ts = x.get("created_at_ts")
        if ts:
            try:
                return float(ts)
            except:
                pass
        # created_at があればざっくり補完
        ca = x.get("created_at", "")
        try:
            # isoformat の比較用に epoch に寄せる
            import datetime
            return datetime.datetime.fromisoformat(ca.replace("Z","+00:00")).timestamp()
        except:
            return 0.0

    items.sort(key=sort_key, reverse=True)
    return items[:limit]


def delete_stl_post(post_id):
    table = _posts_table()
    table.delete_item(Key={"post_id": str(post_id)})


def paginate_stl_posts(page=1, per_page=5):
    """STL投稿をページネーション付きで取得"""
    table = _posts_table()
    resp = table.scan()
    items = resp.get("Items", [])
    
    # created_at でソート（ISO形式は辞書順でソート可能）
    items = sorted(
        items, 
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )
    
    # ページネーション処理
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]
    
    pages = max(1, (total + per_page - 1) // per_page)
    
    return {
        "items": page_items,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_num": page - 1 if page > 1 else None,
        "next_num": page + 1 if page < pages else None,
    }


# ========== Comments ==========
def _comments_table():
    return current_app.config["STL_COMMENTS_TABLE"]


def create_stl_comment(post_id, user_id, content, parent_comment_id=None):
    table = _comments_table()
    comment_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    item = {
        "comment_id": comment_id,
        "post_id": str(post_id),
        "user_id": str(user_id),
        "content": content,
        "parent_comment_id": parent_comment_id or "",
        "created_at": now.isoformat(),
        "created_at_ts": Decimal(str(now.timestamp())),
    }
    
    table.put_item(Item=item)
    return comment_id


def get_comments_by_post(post_id):
    table = _comments_table()
    response = table.scan(
        FilterExpression=Attr("post_id").eq(str(post_id))
    )
    items = response.get("Items", [])
    items.sort(key=lambda x: float(x.get("created_at_ts", 0)))
    return items


def get_all_comments():
    table = _comments_table()
    response = table.scan()
    return response.get("Items", [])


def delete_comments_by_post(post_id):
    table = _comments_table()
    comments = get_comments_by_post(post_id)
    for comment in comments:
        table.delete_item(Key={"comment_id": comment["comment_id"]})


# ========== Likes ==========
def _likes_table():
    return current_app.config["STL_LIKES_TABLE"]


def create_stl_like(post_id, user_id):
    table = _likes_table()
    like_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    item = {
        "like_id": like_id,
        "post_id": str(post_id),
        "user_id": str(user_id),
        "created_at": now.isoformat(),
    }
    
    table.put_item(Item=item)
    return like_id


def get_like_by_post_and_user(post_id, user_id):
    table = _likes_table()
    response = table.scan(
        FilterExpression=Attr("post_id").eq(str(post_id)) & Attr("user_id").eq(str(user_id))
    )
    items = response.get("Items", [])
    return items[0] if items else None


def delete_stl_like(like_id):
    table = _likes_table()
    table.delete_item(Key={"like_id": str(like_id)})


def get_likes_by_post(post_id):
    table = _likes_table()
    response = table.scan(
        FilterExpression=Attr("post_id").eq(str(post_id))
    )
    return response.get("Items", [])


def get_all_likes():
    table = _likes_table()
    response = table.scan()
    return response.get("Items", [])


def delete_likes_by_post(post_id):
    table = _likes_table()
    likes = get_likes_by_post(post_id)
    for like in likes:
        table.delete_item(Key={"like_id": like["like_id"]})


def update_stl_post(post_id, title, content,
                    stl_filename=None, stl_file_path=None,
                    youtube_url=None, youtube_id=None, youtube_embed_url=None,
                    image_file_path=None):  # ★追加
    """STL投稿を更新"""
    import datetime

    table = _posts_table()

    update_expr = "SET title = :title, content = :content, updated_at = :updated_at"
    expr_values = {
        ":title": title,
        ":content": content,
        ":updated_at": datetime.datetime.utcnow().isoformat()
    }

    if stl_filename:
        update_expr += ", stl_filename = :stl_filename"
        expr_values[":stl_filename"] = stl_filename

    if stl_file_path:
        update_expr += ", stl_file_path = :stl_file_path"
        expr_values[":stl_file_path"] = stl_file_path

    if youtube_url is not None:
        update_expr += ", youtube_url = :youtube_url"
        expr_values[":youtube_url"] = youtube_url

    if youtube_id is not None:
        update_expr += ", youtube_id = :youtube_id"
        expr_values[":youtube_id"] = youtube_id

    if youtube_embed_url is not None:
        update_expr += ", youtube_embed_url = :youtube_embed_url"
        expr_values[":youtube_embed_url"] = youtube_embed_url

    # ★画像の保存（Noneでも更新したいなら is not None のまま）
    if image_file_path is not None:
        update_expr += ", image_file_path = :image_file_path"
        expr_values[":image_file_path"] = image_file_path

    table.update_item(
        Key={"post_id": post_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values
    )