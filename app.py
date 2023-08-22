from flask import Flask, render_template

app = Flask(__name__, static_folder='./templates/images')

@app.route('/')
def home():
    return render_template('index.html', title = 'index.html')

if __name__ == '__main__':
    app.run(host="0.0.0.0")