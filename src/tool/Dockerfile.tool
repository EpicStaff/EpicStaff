FROM python:3.12.10

WORKDIR /home/user/root/app

RUN pip install --upgrade --no-cache-dir pip setuptools wheel

RUN pip install poetry

COPY ./pyproject.toml .
COPY ./poetry.lock .

ARG PIP_REQUIREMENTS

RUN poetry config virtualenvs.create false 
RUN poetry install --no-root 
RUN poetry add $PIP_REQUIREMENTS
RUN rm -rf /root/.cache

ARG ALIAS_CALLABLE

RUN echo "ALIAS_CALLABLE=$ALIAS_CALLABLE" > ./.env

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
