FROM python:3.12-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY app/ ./app/
COPY david-molizane.html ./

# Install Python dependencies
RUN pip install --no-cache-dir .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
