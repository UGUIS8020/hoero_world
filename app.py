from flask import Flask, render_template

app = Flask(__name__, static_folder='./templates/images')

@app.route('/')
def home():
    return render_template('index.html', title = 'index.html')

@app.route('/n001211')
def n001211():
    return render_template('n001211.html')

@app.route('/n001217')
def n001217():
    return render_template('n001217.html')

@app.route('/n001220')
def n001220():
    return render_template('n001220.html')

@app.route('/n001221')
def n001221():
    return render_template('n001221.html')

@app.route('/omake')
def omake():
    return render_template('omake.html')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/account')
def account():
    return render_template('account.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/user_maintenance')
def luser_maintenance():
    return render_template('user_maintenance.html')

@app.route("/user")
def user():
    user_list = [
        ["1","渋谷 正彦", "taro@test.com", "1"],
        ["2","佐藤 花子", "hanako@test.com", "0"],
        ["3","鈴木 太郎", "yoshitaka@test.com", "0"]
    ]
    return render_template("user.html",users=user_list)

@app.errorhandler(404)
def error_404(error):
    return render_template("error_pages/404.html"),404

if __name__ == '__main__':
    app.run(debug=True)