FROM ubuntu:14.04
MAINTAINER Leif Johansson <leifj@sunet.se>
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections
RUN apt-get -q update
RUN apt-get -y upgrade
RUN apt-get -y install python python-dev python-pip libyaml-dev git
ADD sunet-pages-api /usr/src/sunet-pages-api
WORKDIR /usr/src/sunet-pages-api
RUN python setup.py install
RUN pip install pyconfig
RUN pip install flask
RUN pip install gunicorn
RUN pip install workerpool
RUN pip install gitpython
RUN pip install pyyaml
WORKDIR /usr/src/sunet-pages-api
RUN python setup.py develop
RUN apt-get -y clean
RUN apt-get -y autoclean
ENV SUNET_PAGES_CONFIG "/etc/sunet-pages.yaml"
ENTRYPOINT gunicorn --timeout 300 --bind 0.0.0.0:5000 wsgi
