FROM python:3.12-slim

# ---- ENV ----
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    DISPLAY=:99 \
    VNC_GEOMETRY=1600x900 \
    VNC_PASS=secret \
    PYTHONUNBUFFERED=1 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080 \
    START_TOOL=browser \
    CUA_USE_LOCAL=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# ---- System deps ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg \
    xvfb x11vnc xfce4 xfce4-goodies x11-apps \
    dbus-x11 xdg-utils fonts-liberation locales \
    libnss3 libxss1 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    xdotool imagemagick \
    chromium \
  && rm -rf /var/lib/apt/lists/*

# ---- Install uv (gives uvx) ----
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN ln -s /root/.local/bin/uvx /usr/local/bin/uvx || true

# ---- Locale ----
RUN sed -i 's/# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen

# ---- Workdir ----
WORKDIR /app

# ---- VNC password (root) ----
RUN x11vnc -storepasswd "${VNC_PASS}" /root/.vncpass

# ---- Python deps ----
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir playwright && \
    uvx playwright install chromium --with-deps

# ---- App code ----
COPY . /app
RUN chmod +x /app/restart.sh
RUN chmod +x /app/entrypoint.sh

# ---- Ports ----
EXPOSE 5900 8080

# ---- Entrypoint / Cmd ----
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-u", "fast_mcp_server.py"]
