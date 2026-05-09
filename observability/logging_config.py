# logging_config.py
import logging
import logging.handlers
import json
import queue
import sys


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def setup_logging():
    log_queue = queue.Queue(-1)

    file_handler = logging.handlers.RotatingFileHandler(
        "app.log", maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setFormatter(JSONFormatter())

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter())

    queue_handler = logging.handlers.QueueHandler(log_queue)

    listener = logging.handlers.QueueListener(
        log_queue, file_handler, stdout_handler, respect_handler_level=True
    )
    listener.start()

    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.INFO)

    logging.getLogger("database").setLevel(logging.WARNING)
    logging.getLogger("voice_client").setLevel(logging.DEBUG)
    logging.getLogger("wrapper").setLevel(logging.INFO)

    return listener
