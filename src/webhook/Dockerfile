FROM python:3.12-slim

RUN pip install poetry

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_NO_INTERACTION 1

WORKDIR /app


COPY ./webhook/poetry.lock ./webhook/pyproject.toml ./


RUN poetry config virtualenvs.create false
RUN poetry install --no-root --no-interaction


COPY ./webhook/app ./app
COPY ./webhook/run.py .


EXPOSE 8000

CMD ["python", "run.py"]
