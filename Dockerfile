# Use Python 3.11 slim as base image
FROM python:3.11-slim-bookworm

# Install curl for Bun installation
RUN apt-get update && apt-get install -y curl unzip && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 ffmpeg libavcodec-dev libavformat-dev libswscale-dev libavdevice-dev && rm -rf /var/lib/apt/lists/*

# Install Bun
RUN curl -fsSL https://bun.sh/install | bash && mv ~/.bun/bin/bun /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy Python requirements and install dependencies
COPY requirements.txt .
COPY app ./app
RUN python -m venv venv && venv/bin/pip install --upgrade pip && venv/bin/pip install -r requirements.txt

# Copy Python .env file
COPY .env .

# Copy MentraApp and install dependencies
COPY MentraApp ./MentraApp
WORKDIR /app/MentraApp
RUN bun install
COPY MentraApp/.env .

# Go back to root
WORKDIR /app

# Expose ports
EXPOSE 8000 3000

# Create startup script
RUN echo '#!/bin/bash\n\
source venv/bin/activate\n\
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &\n\
cd MentraApp && bun run dev &\n\
wait' > start.sh && chmod +x start.sh

# Run the startup script
CMD ["./start.sh"]