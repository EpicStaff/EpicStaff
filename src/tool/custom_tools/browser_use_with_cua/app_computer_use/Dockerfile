FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

# системні залежності (Chromium/Playwright/Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    xfce4 xfce4-goodies x11vnc xvfb xdotool x11-apps sudo \
    ca-certificates curl git pkg-config build-essential gcc g++ make \
    dbus-x11 xdg-utils fonts-liberation \
    libnss3 libxss1 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    libsm6 libxext6 libxrender1 libxi6 libxtst6 libxcb1 \
    libjpeg62-turbo-dev zlib1g-dev libpng-dev libfreetype6-dev \
 && apt-get remove -y light-locker xfce4-screensaver xfce4-power-manager || true \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

COPY requirements.txt /work/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir --prefer-binary -r /work/requirements.txt

# 4) non-root
RUN useradd -ms /bin/bash myuser \
 && echo "myuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# 5) окремий шлях для браузерів + права
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir -p /ms-playwright && chown -R myuser:myuser /ms-playwright

USER myuser
WORKDIR /home/myuser

# 6) Встановлюємо Chromium під myuser
RUN python -m playwright install chromium

ENV DISPLAY=browser_use:99
EXPOSE 9091

CMD ["bash","-lc","cd /work && python -u fast_mcp_server.py"]
