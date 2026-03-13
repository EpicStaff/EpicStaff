# Use base image with python 3.12-slim
FROM python:3.12-slim

# Set work dir
WORKDIR /app/src/webhook

# Install poetry package
RUN pip install poetry

# Set Python env variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \ 
    POETRY_NO_INTERACTION=1 \
    PYTHONPATH=/app

# Install other poetry dependencies
COPY ./webhook/poetry.lock ./webhook/pyproject.toml .
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction && \
    rm -rf /root/.cache

# Copy module code and shared module
COPY ./webhook .
COPY ./shared /app/src/shared

# Expose port 8000
EXPOSE 8000

# Run the module
CMD ["python", "run.py"]
