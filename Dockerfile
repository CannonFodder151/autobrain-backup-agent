FROM python:3.12-alpine
WORKDIR /opt/agent
COPY agent.py .
USER 65534
ENTRYPOINT ["python3", "agent.py"]
