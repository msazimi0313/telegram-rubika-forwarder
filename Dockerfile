# 1. Start with an official Python image
FROM python:3.11-slim

# 2. Set the working directory
WORKDIR /app

# 3. Install system dependencies (git is needed for pip)
RUN apt-get update && apt-get install -y git

# 4. Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the code
COPY . .

# 6. Run the application
CMD ["python", "final_bot.py"]
