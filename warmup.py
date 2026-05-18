import os
import time
import urllib.request
import urllib.error
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("warmup")

def make_request():
    port = os.getenv('PORT', '8080')
    webhook_url = os.getenv('WEBHOOK_URL')

    if webhook_url:
        url = webhook_url.rstrip('/') + '/ping'
        logger.info(f"Pinging external webhook URL: {url}")
    else:
        url = f'http://127.0.0.1:{port}/ping'
        logger.info(f"Pinging local health endpoint: {url}")

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Warmup-Bot/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            logger.info(f"Ping successful. Status code: {status}")
    except urllib.error.URLError as e:
        logger.error(f"Ping failed: {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error during ping: {e}")

if __name__ == "__main__":
    logger.info("Starting warmup service...")
    time.sleep(15)

    while True:
        make_request()
        time.sleep(25 * 60)
