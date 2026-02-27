FROM python:3.12-slim

# Set environment variables to ensure output is immediately flushed
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies required for building and running
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    git \
    make \
    \
 && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy pyproject.toml and other project metadata for dependency installation
COPY pyproject.toml ./

# Upgrade pip and install dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install .

# Copy entire project
COPY . .

# Expose any ports if needed (optional)

# Default command to run the standalone script
CMD ["python", "test273.py"]
