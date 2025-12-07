import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import current_app

class InquiryDDB:
    @staticmethod
    def create(name, email, title, text):
        table = current_app.config["INQUIRY_TABLE"]
        inquiry_id = str(uuid.uuid4())
        item = {
            "id": inquiry_id,
            "name": name,
            "email": email,
            "title": title,
            "text": text,
            "date": datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
            "timestamp": int(datetime.now().timestamp())
        }
        table.put_item(Item=item)
        return item

    @staticmethod
    def get_all(limit=100):
        table = current_app.config["INQUIRY_TABLE"]
        response = table.scan()
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return items[:limit]

    @staticmethod
    def get_by_id(inquiry_id):
        table = current_app.config["INQUIRY_TABLE"]
        response = table.get_item(Key={"id": inquiry_id})
        return response.get("Item")

    @staticmethod
    def delete(inquiry_id):
        table = current_app.config["INQUIRY_TABLE"]
        table.delete_item(Key={"id": inquiry_id})

    @staticmethod
    def paginate(page=1, per_page=10):
        items = InquiryDDB.get_all(limit=1000)
        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            "items": items[start:end],
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
            "has_prev": page > 1,
            "has_next": end < total,
            "prev_num": page - 1 if page > 1 else None,
            "next_num": page + 1 if end < total else None,
        }