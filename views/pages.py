from flask import Blueprint, render_template

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

@bp.route('/zirconia')
def zirconia():
    
    return render_template('pages/zirconia.html')

@bp.route('/combination_checker')
def combination_checker():
    
    return render_template('pages/combination_checker.html')

@bp.route('/missing_teeth_nation')
def missing_teeth_nation():
    
    return render_template('pages/missing_teeth_nation.html')
