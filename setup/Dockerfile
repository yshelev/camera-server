FROM python:3.11-slim

RUN apt-get update && apt-get install -y docker.io
RUN pip install --no-cache-dir python-dotenv

COPY . .

CMD ["python", "setup.py"]