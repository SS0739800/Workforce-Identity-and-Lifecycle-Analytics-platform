#!/bin/bash
# Runs on the EC2 instance, as root, from the extracted release (see the UserData in template.yaml).
# Builds the image, migrates the database, loads the synthetic data on first start, and (re)starts
# the API and Streamlit containers. Safe to run again: `aws_deploy.py push` does exactly that.
#
# Do not add `set -x`: it would print the database password and API keys into the logs.
set -euo pipefail
source /etc/workforce.env
cd "$(dirname "$0")/../.."

# Read an SSM parameter; empty if it doesn't exist (the AI keys are optional).
param() {
  aws ssm get-parameter --region "$AWS_REGION" --name "$PARAM_PREFIX/$1" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || true
}

echo "Writing the API environment file"
umask 077
cat > /opt/workforce/api.env <<EOF
DATABASE_URL=postgresql+psycopg://$DB_USER:$(param db-password)@$DB_HOST:5432/$DB_NAME
GROQ_API_KEY=$(param groq-api-key)
GEMINI_API_KEY=$(param gemini-api-key)
LOG_LEVEL=INFO
EOF
umask 022

echo "Downloading the generated CSV files"
mkdir -p /opt/workforce/data/raw
aws s3 sync --region "$AWS_REGION" --delete "s3://$BUCKET/raw/" /opt/workforce/data/raw/

echo "Building the image"
docker build --tag workforce:latest .
docker network inspect workforce >/dev/null 2>&1 || docker network create workforce

# Container output goes to CloudWatch Logs, one stream per container.
logs() {
  echo --log-driver awslogs --log-opt "awslogs-region=$AWS_REGION" --log-opt "awslogs-group=$LOG_GROUP" \
    --log-opt "awslogs-stream=$1"
}

echo "Migrating the database and loading data if it is empty"
docker run --rm --network workforce --env-file /opt/workforce/api.env $(logs jobs) \
  workforce:latest alembic upgrade head
docker run --rm --network workforce --env-file /opt/workforce/api.env $(logs jobs) \
  --volume /opt/workforce/data:/app/data:ro \
  workforce:latest python scripts/load_data.py --if-empty

echo "Starting the API and the console"
docker rm --force workforce-api workforce-streamlit >/dev/null 2>&1 || true
docker run --detach --name workforce-api --restart unless-stopped --network workforce \
  --env-file /opt/workforce/api.env --publish 8000:8000 $(logs api) \
  workforce:latest
# The console only needs the API's address; it gets no database password or API keys.
docker run --detach --name workforce-streamlit --restart unless-stopped --network workforce \
  --env API_BASE_URL=http://workforce-api:8000 --publish 8501:8501 $(logs streamlit) \
  workforce:latest streamlit run streamlit_app/app.py --server.address=0.0.0.0 --server.port=8501

for attempt in $(seq 1 30); do
  if curl --silent --fail http://localhost:8000/health >/dev/null; then
    echo "API healthy"
    docker image prune --force >/dev/null
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy; see the 'api' stream in the $LOG_GROUP log group" >&2
exit 1
