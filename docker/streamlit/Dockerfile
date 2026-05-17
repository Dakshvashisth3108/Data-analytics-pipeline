# syntax=docker/dockerfile:1
# =============================================================================
# Streamlit dashboard image — HCM Analytics conversational UI
# =============================================================================
# This image runs ONLY the Streamlit front-end. It deliberately EXCLUDES the
# Spark / Kafka pipeline: the dashboard reads the pipeline's *output*
# (Gold parquet + the Chroma vector index), not its source code.
#
# Ollama is NOT inside this image. It keeps running on the host machine.
# The container reaches it through Docker's special DNS name
# `host.docker.internal` (see NL2SQL__OLLAMA__BASE_URL below).
#
# Build (from the project root):
#     docker build -f docker/streamlit/Dockerfile -t hcm-analytics-streamlit .
# =============================================================================

FROM python:3.13-slim

LABEL org.opencontainers.image.title="hcm-analytics-streamlit"
LABEL org.opencontainers.image.description="Conversational HCM analytics dashboard (Streamlit)"

# --- runtime environment ----------------------------------------------------
# PYTHONUNBUFFERED      logs stream out immediately (no buffering)
# PYTHONDONTWRITEBYTECODE  no .pyc clutter in the image
# HF_HOME               where the baked embedding model is cached
# NL2SQL__OLLAMA__BASE_URL  the project's config loader maps this env var to
#                       configs/app.yaml -> nl2sql.ollama.base_url. Inside a
#                       container "localhost" is the container itself, so we
#                       point it at the HOST via host.docker.internal.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.hf_cache \
    NL2SQL__OLLAMA__BASE_URL=http://host.docker.internal:11434

WORKDIR /app

# --- system packages --------------------------------------------------------
# curl            — used by the HEALTHCHECK instruction below
# build-essential — safety net: a compiler for any pip dependency that lacks
#                   a prebuilt wheel for python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl build-essential \
 && rm -rf /var/lib/apt/lists/*

# --- CPU-only PyTorch -------------------------------------------------------
# sentence-transformers depends on torch. The DEFAULT torch wheel bundles
# CUDA GPU libraries (~2 GB). This container has no GPU, so we install the
# CPU-only build (~200 MB) from PyTorch's dedicated wheel index FIRST.
# The next pip step then sees torch already satisfied and won't re-pull it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# --- Python dependencies ----------------------------------------------------
# Copied + installed BEFORE the app code so Docker can cache this layer:
# editing application code won't trigger a dependency reinstall.
COPY docker/streamlit/requirements-streamlit.txt ./requirements-streamlit.txt
RUN pip install --no-cache-dir -r requirements-streamlit.txt

# --- pre-bake the embedding model -------------------------------------------
# Downloads sentence-transformers/all-MiniLM-L6-v2 (~80 MB) INTO the image.
# Result: the first chat query is instant and the running container needs
# no internet access for embeddings.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# --- application code -------------------------------------------------------
# Only the packages the dashboard imports at runtime. producer/ bronze/
# silver/ gold/ schemas/ are intentionally NOT copied — the dashboard reads
# their parquet output, mounted as a volume, not their Python code.
COPY configs/             ./configs/
COPY utils/               ./utils/
COPY embeddings/          ./embeddings/
COPY nl2sql/              ./nl2sql/
COPY router/              ./router/
COPY streamlit_dashboard/ ./streamlit_dashboard/

# --- Streamlit server config + container startup script ---------------------
COPY docker/streamlit/config.toml ./.streamlit/config.toml
COPY docker/streamlit/startup.py  ./startup.py

# --- non-root user (security best practice) ---------------------------------
# Running as root inside a container is a needless risk. uid 10001 is a
# stable, unprivileged id; it owns /app so it can write logs + the HF cache.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

# --- networking -------------------------------------------------------------
# Streamlit serves on 8501. EXPOSE documents the port; you still publish it
# at run time with -p 8501:8501.
EXPOSE 8501

# --- health probe -----------------------------------------------------------
# Streamlit exposes /_stcore/health. Docker flips the container between
# "starting" -> "healthy" / "unhealthy" based on this command.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# --- launch -----------------------------------------------------------------
# startup.py runs environment validation (Ollama reachable? data mounted?)
# and then exec's the Streamlit server so it becomes the main process.
CMD ["python", "startup.py"]
