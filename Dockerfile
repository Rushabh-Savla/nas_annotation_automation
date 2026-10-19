FROM python:3.12-slim

# Install system dependencies, security updates, and rclone
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    rclone \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create application non-root user and group
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Install Python requirements from admin_webpage submodule
COPY admin_webpage/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code from submodules and scripts
COPY admin_webpage/controller /app/controller
COPY admin_webpage/sync_worker /app/sync_worker
COPY annotator_app/annotator_agent /app/annotator_agent
COPY admin_webpage/alembic /app/alembic
COPY admin_webpage/alembic.ini /app/
COPY scripts /app/scripts

# Set permissions
RUN chown -R appuser:appgroup /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "controller.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
