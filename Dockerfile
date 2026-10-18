# GridironIQ platform image — runs the warehouse build, the Dagster graph, and evals.
FROM python:3.11-slim

# Build tools for any wheels that need compiling (duckdb, pyarrow ship wheels, but
# be safe), plus git for dbt deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY gridiron ./gridiron
RUN pip install --no-cache-dir -e ".[warehouse,orchestration]"

# Then the rest of the project (dbt project, orchestration, scripts).
COPY . .

# Data (SQLite/DuckDB/parquet) is NOT baked into the image — mount it at runtime:
#   docker run -v "$PWD/data:/app/data" -p 3000:3000 gridironiq
ENV DAGSTER_HOME=/app/.dagster_home
RUN mkdir -p /app/.dagster_home

EXPOSE 3000

# Default: launch the Dagster UI (asset graph, runs, schedule) on all interfaces.
CMD ["dagster", "dev", "-f", "orchestration/definitions.py", "-h", "0.0.0.0", "-p", "3000"]
