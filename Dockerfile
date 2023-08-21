ARG BUILD_FROM=alpine
FROM $BUILD_FROM

ARG GTFS_UPCOMING_ZIP_URL=https://github.com/seanblanchfield/gtfs-upcoming/archive/refs/heads/main.zip
ARG TFI_GTFS_ZIP=https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip

# Install requirements for add-on
RUN \
  apk add --no-cache \
    python3 \
    py3-pip \
    wget \
    unzip

WORKDIR /app

# Get the GTFS Upcoming python app and install dependencies
RUN wget $GTFS_UPCOMING_ZIP_URL
RUN unzip main.zip
RUN rm main.zip
RUN mv gtfs-upcoming-main/* .
RUN python3 -m pip install -r requirements.txt

# Get the TFI GTFS Realtime data
RUN wget $TFI_GTFS_ZIP
RUN unzip GTFS_Realtime.zip -d GTFS_Realtime

ENTRYPOINT [ "python3", "main.py" ]
