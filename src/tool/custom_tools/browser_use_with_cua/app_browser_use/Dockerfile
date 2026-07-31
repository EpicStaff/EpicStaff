FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    DISPLAY=:99 \
    VNC_GEOMETRY=1600x900 \
    VNC_PASS=secret \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg \
    xvfb x11vnc xfce4 xfce4-goodies x11-apps \
    dbus-x11 xdg-utils fonts-liberation locales \
    libnss3 libxss1 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i 's/# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

RUN useradd -ms /bin/bash appuser && \
    echo "appuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER appuser
WORKDIR /home/appuser

ENV PATH="/home/appuser/.local/bin:${PATH}"

RUN mkdir -p /home/appuser/work 
WORKDIR /home/appuser/work 

RUN x11vnc -storepasswd "${VNC_PASS}" /home/appuser/.vncpass

COPY --chown=appuser:appuser requirements.txt /home/appuser/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /home/appuser/requirements.txt && \
    pip install --no-cache-dir playwright

RUN python -m playwright install chromium

WORKDIR /work

EXPOSE 5900 8080

COPY --chown=appuser:appuser entrypoint.sh /home/appuser/entrypoint.sh
RUN chmod +x /home/appuser/entrypoint.sh

ENV MCP_HOST=0.0.0.0 MCP_PORT=8080
ENTRYPOINT ["/home/appuser/entrypoint.sh"]
CMD ["python", "-u", "fast_mcp_server.py"]