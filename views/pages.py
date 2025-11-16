from flask import Blueprint, render_template, current_app
from flask import request, current_app
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import feedparser
from urllib.parse import quote_plus
from hashlib import sha256
from datetime import datetime
import time
import json
import base64
import requests
from bs4 import BeautifulSoup   
from dateutil.parser import parse as iso
from dateutil import tz



bp = Blueprint('pages', __name__, url_prefix='/pages', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/root_replica')
def root_replica():
    
    return render_template('pages/root_replica.html')

@bp.route('/root_replica_case')
def root_replica_case():
    
    return render_template('pages/root_replica_case.html')

@bp.route('/root_replica_info')
def root_replica_info():
    
    return render_template('pages/root_replica_info.html')

@bp.route('/root_replica_qa')
def root_replica_qa():
    
    return render_template('pages/root_replica_qa.html')

@bp.route('/zirconia')
def zirconia():
    
    return render_template('pages/zirconia.html')

@bp.route('/combination_checker')
def combination_checker():
    
    return render_template('pages/combination_checker.html')

@bp.route('/missing_teeth_nation')
def missing_teeth_nation():
    
    return render_template('pages/missing_teeth_nation.html')

@bp.route('/news')
def news():
    
    return render_template('pages/news.html')

# --- helper: DynamoDB が datetime を受け取れないため ISO 文字列に揃える ---
def _ensure_iso(v):
    from datetime import datetime, date, timezone
    if v is None:
        return None
    if isinstance(v, datetime):
        # naiveならUTC付与、awareならUTCへ変換
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        else:
            v = v.astimezone(timezone.utc)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(v)

# --- helper: DynamoDB に渡す辞書を安全化（datetime→ISO 文字列 など） ---
def _dynamodb_sanitize(v):
    from datetime import datetime, date, timezone
    # datetime -> ISO
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        else:
            v = v.astimezone(timezone.utc)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    # date -> ISO(00:00Z)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)\
               .strftime("%Y-%m-%dT%H:%M:%SZ")
    # dict -> 再帰
    if isinstance(v, dict):
        return {k: _dynamodb_sanitize(v2) for k, v2 in v.items()}
    # list/tuple -> 再帰
    if isinstance(v, (list, tuple)):
        return type(v)(_dynamodb_sanitize(x) for x in v)
    # set は SS として扱うなら set(str,…) に、面倒なら list へ
    if isinstance(v, set):
        return list(_dynamodb_sanitize(x) for x in v)
    # それ以外はそのまま/文字列化
    return v
