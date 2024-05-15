from flask import render_template, Blueprint

bp = Blueprint('error_pages', __name__, template_folder='templates', static_folder='static')

@bp.app_errorhandler(403)
def error_403(error):
    return render_template('error_pages/403.html'), 403

@bp.app_errorhandler(404)
def error_404(error):
    return render_template('error_pages/404.html'), 404