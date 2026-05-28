from flask import Blueprint, render_template

bp = Blueprint('hoero', __name__, url_prefix='/hoero')

@bp.route('/mokei001')
def mokei001():
    return render_template('hoero/mokei001.html')

@bp.route('/mokei002')
def mokei002():
    return render_template('hoero/mokei002.html')

@bp.route('/cast')
def cast():
    return render_template('hoero/cast.html')

@bp.route('/kennma')
def kennma():
    return render_template('hoero/kennma.html')

@bp.route('/tekigo')
def tekigo():
    return render_template('hoero/tekigo.html')
