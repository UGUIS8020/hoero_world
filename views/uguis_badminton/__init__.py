from flask import Blueprint

uguis_badminton_bp = Blueprint(
    'uguis_badminton', 
    __name__, 
    url_prefix='/uguis_badminton'
)

from . import routes