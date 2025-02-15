# Use the official tiangolo/uvicorn-gunicorn-fastapi image with Python 3.10
FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/smart-agri-tech

# Set working directory
WORKDIR /smart-agri-tech

# Copy and install dependencies first
COPY ./requirements.txt /smart-agri-tech/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY ./ /smart-agri-tech/

# Ensure the entrypoint script is executable
RUN chmod +x /smart-agri-tech/entrypoint.sh

# Create non-root user if not exists
RUN if ! id "appuser" &>/dev/null; then \
        addgroup --system appgroup && \
        adduser --system --ingroup appgroup --disabled-password --gecos "" appuser; \
    fi && \
    chown -R appuser:appgroup /smart-agri-tech /usr/local/lib/python*

# Switch to the created non-root user
USER appuser

# Expose backend port
EXPOSE ${BACKEND_PORT}

# Set the entrypoint
ENTRYPOINT ["/smart-agri-tech/entrypoint.sh"]

# Run FastAPI app
CMD ["sh", "-c", "uvicorn main:smart_agri_tech_app --host 0.0.0.0 --port $BACKEND_PORT --reload"]
