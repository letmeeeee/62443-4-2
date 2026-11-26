# Pure bytecode needs matching CPython, not an ARM64 OS or native compiler.
# Pin this image to a tested tag/digest for repeatable production releases.
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
# Repository is bind-mounted at runtime; no source, secrets or license in image.
ENTRYPOINT ["python", "deploy/build_pyc.py"]
