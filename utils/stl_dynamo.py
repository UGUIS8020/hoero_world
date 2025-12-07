import uuid
from datetime import datetime
from decimal import Decimal
from flask import current_app
from boto3.dynamodb.conditions import Attr


# ========== Posts ==========
def _posts_table():
    return current_app.config["STL_POSTS_TABLE"]


def create_stl_post(title, content, user_id, stl_filename=None, stl_file_path=None, gltf_file_path=None):
    table = _posts_table()
    post_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    item = {
        "post_id": post_id,
        "title": title or "Untitled",
        "content": content or "",
        "user_id": str(user_id),
        "stl_filename": stl_filename or "",
        "stl_file_path": stl_file_path or "",
        "gltf_file_path": gltf_file_path or "",
        "created_at": now.isoformat(),
        "created_at_ts": Decimal(str(now.timestamp())),
    }
    
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
    
    # stl_file_pathがあるものだけフィルタ
    items = [it for it in items if it.get("stl_file_path")]
    
    # created_at_ts で降順ソート
    items.sort(key=lambda x: float(x.get("created_at_ts", 0)), reverse=True)
    return items[:limit]


def delete_stl_post(post_id):
    table = _posts_table()
    table.delete_item(Key={"post_id": str(post_id)})


def paginate_stl_posts(page=1, per_page=5):
    items = list_stl_posts(limit=1000)
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if total > 0 else 1,
        "has_prev": page > 1,
        "has_next": end < total,
        "prev_num": page - 1 if page > 1 else None,
        "next_num": page + 1 if end < total else None,
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