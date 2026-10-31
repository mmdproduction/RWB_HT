FROM python:3.12-slim
WORKDIR /checks
COPY scripts/tests.py scripts/app-spec.json ./
COPY scripts/domain_checks.py scripts/domain-acceptance.json ./
USER 65534:65534
CMD ["python", "/checks/tests.py"]
