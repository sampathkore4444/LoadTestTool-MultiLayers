FROM python:3.11-slim
WORKDIR /app
RUN pip install requests
COPY soak-monitor.py /app/
CMD ["python", "/app/soak-monitor.py"]