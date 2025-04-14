from flask import Blueprint, render_template

bp = Blueprint('main', __name__, url_prefix='/main', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/root_replica')
def root_eplica():
    
    return render_template('pages/rootr_eplica.html')