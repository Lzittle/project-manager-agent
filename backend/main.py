from fastapi import FastAPI
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title=os.getenv("APP_NAME"))

@app.get("/health")
def health_check():
    return {"status":"ok","app_name":os.getenv("APP_NAME")}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST","0.0.0.0"),
        port=int(os.getenv("APP_PORT",8000))
    )