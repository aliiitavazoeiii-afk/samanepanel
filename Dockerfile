FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY daily_sales_service ./daily_sales_service
RUN useradd -m -u 10001 app && mkdir /data && chown app:app /data
USER app
EXPOSE 8018
CMD ["uvicorn","daily_sales_service.app:app","--host","0.0.0.0","--port","8018","--proxy-headers"]
