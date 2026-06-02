from flask import Flask, render_template, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/greeting')
def greeting():
    return jsonify({'message': 'Hello from the backend!', 'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True)
