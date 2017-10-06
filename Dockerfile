FROM centos

MAINTAINER Hubert Asamer

RUN yum -y update && yum -y install epel-release && yum -y update && yum -y install python-pip jq java gdal gdal-python && pip install --upgrade pip  && pip install awscli certifi

COPY bin /root/bin
COPY tools /root/tools

WORKDIR /root

CMD ["bin/in_s3_env", "tools/sentinel-3/tiler/sentinel3tiler.py"]