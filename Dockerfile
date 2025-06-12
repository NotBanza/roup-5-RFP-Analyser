# Use an official, stable Python runtime
FROM python:3.9-slim

# Set environment variables for better logging and no .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Install system dependencies that some Python packages might need
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Install the Python dependencies from your curated list
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Tell Docker that the container will listen on this port
EXPOSE 8000

# Make the startup script executable
RUN chmod +x /app/startup.sh

# The command to run your app is now handled by the startup command in Azure config
# We can leave the CMD here as a fallback for local testing
CMD ["/app/startup.sh"]