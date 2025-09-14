# syntax=docker/dockerfile:1

# Use a lightweight official Python image as the base
FROM python:3.11-slim as runtime

# Install the Python dependencies required by the monitor script.  The
# packages `watchdog` and `requests` provide cross‑platform file system
# watching and HTTP client capabilities respectively.

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create a non‑root user to run the application for better security
RUN useradd --create-home appuser

# Set the working directory inside the container
WORKDIR /app

# Copy the monitoring script into the image
COPY monitor.py ./monitor.py


# Expose no ports; this container only makes outbound HTTP requests

# Ensures Python output isn’t buffered, so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Switch to the non‑root user
USER appuser

# By default run the monitoring script
ENTRYPOINT ["python", "./monitor.py"]