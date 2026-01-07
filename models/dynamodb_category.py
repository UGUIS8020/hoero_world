from flask import current_app

def _blog_categories_table():
    return current_app.config["BLOG_CATEGORIES_TABLE"]

def list_blog_categories_all():
    """DynamoDB からカテゴリを全件取得して ID 昇順でソート"""
    table = _blog_categories_table()
    resp = table.scan()
    items = resp.get("Items", [])

    def _id(x):
        try:
            return int(x.get("category_id", 0))
        except Exception:
            return 0

    items.sort(key=_id)
    return items

def category_name_exists(name, exclude_id=None):
    """カテゴリ名が既に存在するかチェック"""
    items = list_blog_categories_all()
    for item in items:
        if item.get("name") == name:
            if exclude_id is None:
                return True
            if int(item.get("category_id", 0)) != exclude_id:
                return True
    return False