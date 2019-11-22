FROM debian:stable
MAINTAINER Leif Johansson <leifj@sunet.se>
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections
RUN apt-get -q update
RUN apt-get -y upgrade
RUN apt-get -y install python3 python3-dev python3-pip libyaml-dev git libltdl7
ADD sunet-pages-api /usr/src/sunet-pages-api
WORKDIR /usr/src/sunet-pages-api
RUN python3 setup.py install
RUN pip3 install pyconfig flask gunicorn workerpool gitpython pyyaml docker
WORKDIR /usr/src/sunet-pages-api
RUN python3 setup.py develop
RUN apt-get -y clean
RUN apt-get -y autoclean
ENV SUNET_PAGES_CONFIG "/etc/sunet-pages.yaml"
ENV SUNET_PAGES_AUTH_COOKIE ""
ENTRYPOINT gunicorn --timeout 300 --bind 0.0.0.0:5000 wsgi
