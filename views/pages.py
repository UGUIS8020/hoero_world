from flask import Blueprint, render_template

bp = Blueprint('pages', __name__, url_prefix='/pages', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/root_replica')
def root_replica():
    
    return render_template('pages/root_replica.html')