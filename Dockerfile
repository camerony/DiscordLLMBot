FROM python:3.12-slim
WORKDIR /app
RUN mkdir -p /data && chmod 777 /data
RUN pip install --no-cache-dir discord.py aiohttp
COPY bot.py .
COPY rag.py .
CMD ["python", "-u", "bot.py"]
