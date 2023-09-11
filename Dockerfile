FROM python:3.11.3
RUN pip install pyserial paho-mqtt PyYAML
ADD teleinfo.py .
ADD config.yml .
CMD ["python", "./teleinfo.py"] 