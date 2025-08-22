# 1. Start with an official Python image
FROM python:3.11

# 2. Set the working directory in the container
WORKDIR /app

# 3. Install system dependencies, including ffmpeg
RUN apt-get update && apt-get install -y ffmpeg git

# 4. Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application code
COPY . .

# 6. Command to run the application
CMD ["python", "final_bot.py"]
