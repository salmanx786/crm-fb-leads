from flask import Flask
from workers import wsgi

app = Flask(__name__)


@app.get("/")
def index():
    return {"message": "Hello from Flask"}


@app.get("/health")
def health():
    return {"status": "ok"}


Default = wsgi.entrypoint(app)
