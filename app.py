from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "CPL Instructor App is running ✅"

# Azure/Gunicorn uses `app:app` (file:variable)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
