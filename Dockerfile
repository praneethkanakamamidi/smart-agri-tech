# Use the official tiangolo/uvicorn-gunicorn-fastapi image with Python 3.10

FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

# Set environment variables for Python to avoid unnecessary bytecode and ensure stdout/stderr are unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /smart-agri-tech

# Copy and install dependencies first to leverage Docker layer caching
COPY ./requirements.txt /smart-agri-tech/

# Install Python dependencies without cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY ./ /smart-agri-tech/

# Ensure the entrypoint script is executable
RUN chmod +x /smart-agri-tech/entrypoint.sh

# Create a non-root user for security, but only if it doesn't exist
RUN if ! id "appuser" &>/dev/null; then \
        addgroup --system appgroup && \
        adduser --system --ingroup appgroup --disabled-password --gecos "" appuser; \
    fi && \
    chown -R appuser:appgroup /smart-agri-tech

# Switch to the created non-root user
USER appuser

# Expose the port the app will run on (default for FastAPI is 8000)
EXPOSE ${BACKEND_PORT}

# Set the entrypoint to the entrypoint script
ENTRYPOINT ["/smart-agri-tech/entrypoint.sh"]

# Set the default command to run Uvicorn with FastAPI app
CMD ["sh", "-c", "uvicorn main:smart_agri_tech_app --host 0.0.0.0 --port $BACKEND_PORT --reload"]
