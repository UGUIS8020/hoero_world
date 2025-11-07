from flask import Blueprint

# /news でぶら下げたいなら url_prefix="/news"
bp = Blueprint("news", __name__, url_prefix="/news")

# これが無いとルートが登録されません（超重要）
from . import autotransplant_news