FROM python:3-slim

ARG BUILD_DIR="/build/gtfs-upcoming"

WORKDIR ${BUILD_DIR}
COPY . .

RUN pip install hatch
RUN hatch build
RUN pip install dist/*.whl

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

# We don't need the build artefacts
RUN rm -fr ${BUILD_DIR}

EXPOSE 6824
EXPOSE 6825
VOLUME /gtfs

ENV GTFS_PROVIDER="nta"
ENV GTFS_ENVIRONMENT="prod"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]