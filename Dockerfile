# pull official base image
FROM python:3.10.10-slim-buster

RUN apt-get update && apt-get install libpq-dev gcc -y

# install dependencies
WORKDIR /usr/src/app
COPY ./requirements.txt /usr/src/app/requirements.txt
RUN python3 -m pip install -r requirements.txt --no-cache-dir

# copy project
COPY . /usr/src/app/

# set environment variables
ENV HOST_NAME vortex
ENV PYTHONPATH /usr/src/app