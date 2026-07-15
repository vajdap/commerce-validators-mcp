FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

# stdio transport by default (what MCP clients/inspectors expect);
# set MCP_HTTP=1 (+ MCP_PORT) for remote streamable-HTTP hosting.
CMD ["python3", "server.py"]
