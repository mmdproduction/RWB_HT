FROM python:3.12-slim
WORKDIR /checks
COPY scripts/tests.py scripts/app-spec.json ./
COPY scripts/integration_checks.py ./
USER 65534:65534
CMD ["python", "/checks/tests.py"]
