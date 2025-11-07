# /var/www/hoero_world/scripts/run_autotrans_collect.py
# -*- coding: utf-8 -*-
import os, sys, json, importlib, pkgutil, traceback
from types import ModuleType

os.chdir("/var/www/hoero_world")
sys.path.insert(0, "/var/www/hoero_world")

# ---- Flaskアプリのロード ----
flask_app = None
try:
    app_mod: ModuleType = importlib.import_module("app")
except Exception as e:
    print(json.dumps({"ok": False, "error": f"import app failed: {e}"}, ensure_ascii=False)); raise

create_app = getattr(app_mod, "create_app", None)
if callable(create_app):
    flask_app = create_app()
else:
    from flask import Flask
    for name in ["app", "application", "server"] + list(dir(app_mod)):
        try:
            obj = getattr(app_mod, name)
        except Exception:
            continue
        if isinstance(obj, Flask):
            flask_app = obj; break
if flask_app is None:
    print(json.dumps({"ok": False, "error": "Flask app instance not found in app.py"}, ensure_ascii=False)); raise SystemExit(1)

# ---- collector 取得（環境変数で指定可）----
def get_collector():
    mod_name = os.getenv("NEWS_COLLECTOR_MODULE")  # 例: views.pages
    fn_name  = os.getenv("NEWS_COLLECTOR_FUNC", "collect_autotransplant_news")
    if mod_name:
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, fn_name, None)
            if callable(fn): return fn, f"{mod_name} (env)"
            return None, f"{mod_name}.{fn_name} が見つかりません"
        except Exception as e:
            return None, f"環境変数で指定モジュールの import 失敗: {e}"

    # 自動検出（views 配下）
    try:
        pkg = importlib.import_module("views")
    except Exception:
        return None, "views パッケージが見つかりません（views/ に __init__.py を置いてください）"
    for m in pkgutil.iter_modules(pkg.__path__):
        name = f"views.{m.name}"
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn): return fn, name
    return None, f"{fn_name} を持つモジュールが見つかりませんでした"

if __name__ == "__main__":
    collector, where = get_collector()
    if not callable(collector):
        print(json.dumps({"ok": False, "error": where}, ensure_ascii=False)); raise SystemExit(1)

    with flask_app.app_context():
        try:
            ret = collector()
            # 返り値を柔軟に解釈
            total = None
            results = None
            if isinstance(ret, tuple):
                # (total, results) or (total,)
                if len(ret) >= 1: total = ret[0]
                if len(ret) >= 2: results = ret[1]
            elif isinstance(ret, dict):
                # {"total": X, ...}
                total = ret.get("total")
                results = ret
            elif isinstance(ret, int):
                total = ret
            else:
                # 不明な型
                results = {"return_type": type(ret).__name__}

            print(json.dumps({"ok": True, "from": where, "total": total, "results": results}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "from": where, "error": str(e), "trace": traceback.format_exc()}, ensure_ascii=False)); raise
