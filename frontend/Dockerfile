# Use the official Python image
FROM python:3.10-slim

WORKDIR /app
# Install Python dependencies
COPY requirements.txt .

RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the files
COPY . .

CMD python3 frontend.py
