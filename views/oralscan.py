"""
views/oralscan.py
Oral Scan Data 自動ログイン機能のBlueprint
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
import threading
from datetime import datetime
import os

# ボット関数をインポート
from utils.oralscan_bot import run_oralscan_login

# Blueprintの作成
bp = Blueprint('oralscan', __name__, url_prefix='/oralscan')

# ボットのステータスを保存
bot_status = {
    'is_running': False,
    'last_run': None,
    'last_result': None,
    'message': ''
}


def admin_required(f):
    """
    管理者権限が必要なルートを保護するデコレータ
    Flask-Loginと既存の認証システムを使用
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        # 管理者チェック（current_userのadministrator属性を確認）
        if not current_user.administrator:
            flash('管理者権限が必要です', 'error')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/')
@bp.route('/admin')
@admin_required
def admin():
    """Oral Scan 自動化管理画面"""
    return render_template('oralscan/admin.html', status=bot_status)


@bp.route('/run-bot', methods=['POST'])
@admin_required
def run_bot():
    """
    Oral Scanログインボットを実行
    """
    if bot_status['is_running']:
        return jsonify({
            'success': False,
            'message': '既にボットが実行中です'
        })
    
    # バックグラウンドでボットを実行
    def run_bot_thread():
        bot_status['is_running'] = True
        bot_status['message'] = '実行中...'
        
        try:
            # headless=True でサーバー環境で動作
            success = run_oralscan_login(headless=True, keep_browser_open=False)
            bot_status['last_result'] = 'success' if success else 'failed'
            bot_status['message'] = 'ログインに成功し、症例一覧に移動しました' if success else 'ログインに失敗しました'
        except Exception as e:
            bot_status['last_result'] = 'error'
            bot_status['message'] = f'エラー: {str(e)}'
        finally:
            bot_status['is_running'] = False
            bot_status['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    thread = threading.Thread(target=run_bot_thread)
    thread.daemon = True  # メインスレッド終了時に自動終了
    thread.start()
    
    return jsonify({
        'success': True,
        'message': 'ボットの実行を開始しました'
    })


@bp.route('/status')
@admin_required
def get_status():
    """
    ボットのステータスを取得（AJAX用）
    """
    return jsonify(bot_status)


@bp.route('/test')
@admin_required
def test():
    """
    テストページ（開発用）
    """
    return jsonify({
        'status': 'ok',
        'message': 'Oral Scan Blueprint is working!',
        'bot_status': bot_status
    })