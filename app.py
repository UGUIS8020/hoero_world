from flask import Flask, render_template

app = Flask(__name__, static_folder='./templates/images')

@app.route('/')
def home():
    return render_template('index.html', title = 'index.html')

@app.route('/n001211')
def n001211():
    return render_template('n001211.html')

if __name__ == '__main__':
    app.run(host="0.0.0.0")