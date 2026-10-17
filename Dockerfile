FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOME=/home/user

# Create non-root user with UID 1000 for Hugging Face Spaces security & permission standards
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project code and ensure non-root ownership
COPY --chown=user:user . .

USER user

# Expose Hugging Face Space port
EXPOSE 7860

# Start Namma-Kanakku Streamable HTTP server & Counter Screen
CMD ["python", "server.py"]
