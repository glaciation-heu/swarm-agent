FROM python:3.12-slim

WORKDIR /code

# Install curl and clean up unnecessary files to keep the image small
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY poetry.lock pyproject.toml ./

RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --without dev,test \
    && rm -rf $(poetry config cache-dir)/{cache,artifacts}

COPY ./app /code/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
