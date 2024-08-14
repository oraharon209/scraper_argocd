# Use the official Python image
FROM python:3.10-slim

# Install necessary system dependencies
RUN apt-get update && apt-get install -y curl gnupg

# Install Helm
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Create necessary directories
RUN mkdir -p /app/.kube

# Copy the kube config file into the Docker image
COPY ./admin.conf /app/.kube/admin.conf

# Set environment variables
ENV KUBECONFIG=/app/.kube/admin.conf

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the files
COPY . .

CMD python3 backend.py
