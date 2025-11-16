from flask import current_app
from decimal import Decimal
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr
import time

def _table():
    return current_app.config["BLOG_POSTS_TABLE"]

def _dt_to_utc(dt: datetime | None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    return dt.isoformat(), Decimal(str(dt.timestamp()))

def create_blog_post_in_dynamo(
    user_id: int,
    title: str,
    text: str,
    summary: str | None,
    featured_image: str | None,
    author_name: str | None,
    category_id: int | None,
    category_name: str | None,
):
    table = _table()

    post_id = int(time.time() * 1000)  # ミリ秒タイムスタンプで一意ID

    now = datetime.now(timezone.utc)
    iso, ts = _dt_to_utc(now)

    item = {
        "post_id": str(post_id),
        "user_id": str(user_id),
        "title": title or "",
        "text": text or "",
        "summary": summary or "",
        "featured_image": featured_image or "",
        "author_name": author_name or "",
        "category_id": str(category_id) if category_id is not None else "",
        "category_name": category_name or "",
        "date": iso,
        "created_at_ts": ts,
    }

    item = {k: v for k, v in item.items() if v is not None}

    table.put_item(Item=item)
    return post_id

def list_recent_posts(limit: int = 50):
    table = _table()
    resp = table.scan()
    items = resp.get("Items", [])

    def _key(x):
        v = x.get("created_at_ts", 0)
        if isinstance(v, Decimal):
            return float(v)
        try:
            return float(v)
        except Exception:
            return 0.0

    items.sort(key=_key, reverse=True)
    return items[:limit]

def get_post_by_id(post_id: int):
    table = _table()
    resp = table.scan(
        FilterExpression=Attr("post_id").eq(str(post_id))
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return items[0]