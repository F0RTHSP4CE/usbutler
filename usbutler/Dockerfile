# Single-stage build
FROM python:3.12-slim

# Set environment variables
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV PATH="/app/.venv/bin:$PATH"

# Install system dependencies (both build and runtime)
RUN apt-get update && apt-get install -y \
    # Required for pyscard (smart card library)
    usbutils \
    libpcsclite-dev \
    libpcsclite1 \
    pcscd \
    pcsc-tools \
    python3-pyscard \
    # Required for libgpiod (GPIO control)
    libgpiod-dev \
    # Build tools
    gcc \
    g++ \
    make \
    pkg-config \
    swig \
    # Process supervisor and USB monitoring
    supervisor \
    udev \
    # sqlite3 for database management
    sqlite3 \
    # Clean up
    && rm -rf /var/lib/apt/lists/* \
    && apt-get autoremove -y \
    && apt-get clean

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser

# Set working directory
WORKDIR /app

# Create application directories early
RUN mkdir -p /app/data

# Copy uv configuration files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev

# Ensure application files and virtualenv are owned by appuser
RUN chown -R appuser:appuser /app

# Copy application code
COPY --chown=appuser:appuser . .

# Create supervisord configuration
RUN mkdir -p /etc/supervisor/conf.d /var/log/supervisor

# Create supervisord config file
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Make scripts executable
RUN chmod +x /app/scripts/udev_monitor.sh /app/scripts/reconnect_reader.sh

# Expose port (adjust if your app uses a different port)
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
# Default command to run supervisord (as root to manage both processes)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
