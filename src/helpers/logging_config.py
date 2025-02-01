import json
import logging
import os

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging.

    This formatter outputs log records as structured JSON objects, which are useful
    for logging in cloud environments or log aggregation systems.

    :param record: The log record to format (from `logging` module).
    :return: A JSON-formatted string containing the log information.
    """
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),  # Timestamp of the log entry
            "name": record.name,  # Logger name
            "level": record.levelname,  # Log level (e.g., INFO, ERROR)
            "message": record.getMessage(),  # The log message
            "module": record.module,  # The module in which the log was created
            "function": record.funcName,  # The function where the log was generated
            "line": record.lineno  # The line number where the log occurred
        }

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add additional fields from `extra`, ensuring no conflict with default attributes
        for key, value in record.__dict__.get("extra_fields", {}).items():
            if key not in log_obj:  # Avoid overwriting existing keys
                log_obj[key] = value

        return json.dumps(log_obj)  # Return the log entry as a JSON string

def get_logger(name):
    """Configures and returns a logger with JSON formatting.

    This function sets up a logger with a custom `JSONFormatter` to produce structured
    JSON logs. The logger is also configured with a stream handler to output logs
    to the console.

    :param name: The name of the logger. Typically, use `__name__` for modular logging.
    :type name: str
    :return: A configured logger with JSON formatting.
    :rtype: logging.Logger
    """
    logger = logging.getLogger(name)
    
    # Avoid adding multiple handlers if called multiple times
    if not logger.hasHandlers():
        logger.setLevel(logging.INFO)  # Set the default log level to INFO
        handler = logging.StreamHandler()  # Log to the console (stdout)
        handler.setFormatter(JSONFormatter())  # Set the custom JSON formatter
        logger.addHandler(handler)  # Add the handler to the logger
        log_dir = 'logs'
        if not os.path.exists(log_dir):  # Ensure the 'logs' directory exists
            os.makedirs(log_dir)  # Create the directory if it doesn't exist
        file_handler = logging.FileHandler(os.path.join(log_dir, 'app.log'))
        file_handler.setFormatter(JSONFormatter())  # Set the custom JSON formatter
        logger.addHandler(file_handler)  # Add the file handler to the logger

    return logger  # Return the configured logger
