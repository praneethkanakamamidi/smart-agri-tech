import json
import logging

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add additional fields from `extra`, ensuring no conflict with default attributes
        for key, value in record.__dict__.get("extra_fields", {}).items():
            if key not in log_obj:  # Avoid overwriting existing keys
                log_obj[key] = value

        return json.dumps(log_obj)

def get_logger(name):
    """Configures and returns a logger with JSON formatting."""
    logger = logging.getLogger(name)
    if not logger.hasHandlers():  # Avoid adding multiple handlers if called multiple times
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger
