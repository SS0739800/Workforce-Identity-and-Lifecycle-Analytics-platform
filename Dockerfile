# One image for the API, the Streamlit console and the one-off jobs (migrations, data load).
# The default command starts the API; the console and jobs pass their own command.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY streamlit_app ./streamlit_app
COPY .streamlit ./.streamlit

# Run as an unprivileged user. Generated CSVs are mounted at /app/data when needed.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000 8501
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
