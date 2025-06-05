
from flask import Blueprint, render_template

bp = Blueprint('sub_account', __name__, url_prefix='/sub_account')

@bp.route('/')
def sub_account_dashboard():
    # サブアカウント用ダッシュボードなど
    return render_template('sub_account/dashboard.html')