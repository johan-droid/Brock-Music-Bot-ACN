# health_check.py
import urllib.request
import sys
import json


def check_health(url="http://localhost:8080/health"):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if response.status == 200:
                print(json.dumps({"status": "success", "data": data}))
                sys.exit(0)
            else:
                print(json.dumps({"status": "failed", "data": data}))
                sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    check_health()
