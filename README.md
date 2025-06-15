![build and tests](https://github.com/seanrees/gtfs-upcoming/actions/workflows/build.yml/badge.svg)

# gtfs-upcoming

## What

This is a backend HTTP service that consumes a GTFS Schedule and GTFS Realtime
feed, and produces a simple time-ordered list of upcoming services and when they're
due.

### Sample Output

This is from `/upcoming.json`:

```
{
   "current_timestamp":1598471804,
   "upcoming":[
      {
         "trip_id":"ABCDEF",
         "route":"7",
         "route_type":"BUS",
         "headsign":"Bride's Glen Bus Stop - Mountjoy Square Nth",
         "direction":"1",
         "dueTime":"20:57:01",
         "dueInSeconds":17.0,
         "source": "LIVE",
      },
      {
         "trip_id":"GHIJKL",
         "route":"7A",
         "route_type":"BUS",
         "headsign":"Loughlinstown Wood Estate - Mountjoy Square Nth",
         "direction":"1",
         "dueTime":"21:10:33",
         "dueInSeconds":829.0,
         "source": "SCHEDULE"
      }
   ]
}
```

This was developed against the Irish [NTA's GTFS-R feed](https://developer.nationaltransport.ie/api-details#api=gtfsr)
and the [VicRoads Data Exchange GTFS-R feed](https://data-exchange.vicroads.vic.gov.au/api-details#api=vehicle-position-trip-update-opendata&operation=metro-bus-trip-updates).

## Usage

You will need GTFS Schedule data and configuration file first. See _Data and Configuration_ below for more.

```sh
% gtfs-upcoming -- --config vicroads/metrotrain.ini --env metrotrain --provider vicroads --gtfs vicroads/2 --port 6824
2025/06/12 15:59:48 [                 gtfs_upcoming.main 124634004029568]       INFO Starting up
2025/06/12 15:59:48 [                 gtfs_upcoming.main 124634004029568]       INFO Reading "vicroads/metrotrain.ini"
2025/06/12 15:59:48 [                 gtfs_upcoming.main 124634004029568]       INFO Configured loader with 16 threads, 100000 rows per chunk
2025/06/12 15:59:48 [                 gtfs_upcoming.main 124634004029568]       INFO Loading GTFS data sources from "vicroads/2"
2025/06/12 15:59:48 [                 gtfs_upcoming.main 124634004029568]       INFO Restricting data sources to 1 interesting stops
2025/06/12 15:59:49 [                 gtfs_upcoming.main 124634004029568]       INFO Load complete.
2025/06/12 15:59:49 [       gtfs_upcoming.realtime.fetch 124634004029568]       INFO VicRoads/PTV, env=metrotrain, url=https://data-exchange-api.vicroads.vic.gov.au/opendata/v1/gtfsr/metrotrain-tripupdates
2025/06/12 15:59:49 [                 gtfs_upcoming.main 124634004029568]       INFO Starting HTTP server on port 6824
```

Then browse to http://localhost:6824/upcoming.json to see.

### Endpoints

Endpoint | Arguments | Notes
-------- | --------- | -----
/upcoming.json | _(none)_ | Shows real-time & scheduled data if Interesting Stops provided.
/upcoming.json | ?stop=123&stop=456 | Shows real-time & scheduled data for stops 123 and 456
/live.json | _(none)_ | Shows just real-time data if Interesting Stops provided
/live.json | ?stop=123&stop=456 | Shows just real-time data for stops 123 and 456
/scheduled.json | _(none)_ | Shows just scheduled data if Interesting Stops provided
/scheduled.json | ?stop=123&stop=456 | Shows just scheduled data for stops 123 and 456
/debugz | _(none)_ | Debug endpoint for GTFS API calls
:8000 | _(none)_ | Prometheus metrics, if --promport is specified

## Run and Build

This project is built with [Hatch](https://hatch.pypa.io/latest/). This is a change made in
June 2025, previously the project was built with Bazel.

```sh
% hatch run gtfs-upcoming -- [--config CONFIG] [--gtfs GTFS] [--port PORT] [--provider {nta,vicroads}] [--env {prod,test,metrotrain,tram}] 
```

To build a wheel (e.g; to install with `pip`) use this. The `whl` file will emit into the `dist/` directory.
```sh
% hatch build
```

## Docker
An experimental Dockerfile can be used. It builds from local sources. It requires a volume mount that includes
the GTFS Schedule data (e.g; `trips.txt`, `routes.txt`) _and_ your `config.ini`.

The Dockerfile also expects 2 environment variables if you want to override `--provider` and/or `--env`. Use
`GTFS_PROVIDER` and `GTFS_ENVIRONMENT` respectively.

To build:
```sh
% docker build . --tag gtfs-upcoming
```

Example run:

```sh
% docker run -v path-to-gtfs-and-config:/gtfs -e GTFS_PROVIDER=vicroads -e GTFS_ENVIRONMENT=metrotrain -p 6824:6824 -p 6825:6825 gtfs-upcoming
```

## Data and Configuration

### GTFS Data

You will need the GTFS schedule dataset (contains definitions for routes, stops,
stop times, and agencies) in order to interpret the realtime data
correctly. This is available from your GTFS-R provider.

For the Irish NTA, that is [here](https://www.transportforireland.ie/transitData/google_transit_combined.zip).
For VicRoads/PTV, that is [here](https://data.ptv.vic.gov.au/downloads/gtfs.zip).

These datasets can change, sometimes quite a bit, at unpredictable intervals. It's recommended
to setup a regular refresh -- once a week has worked well for me.

### config.ini

There is a sample config in `sample-config.ini`. 

Server configuration is an INI file and has two sections:

1. ApiKeys section: API keys
1. Upcoming section: Interesting Stops

#### API Keys

```
[ApiKeys]
  PrimaryApiKey =
  SecondaryApiKey =
```

#### (Optional) Interesting Stop Ids

This is _optional_. If specified: gtfs-upcoming will only keep trip and stop
data for the interesting stops. All other trip information will be discarded
at load time.

This is particularly useful for running on low-memory devices (e.g; a
Raspberry Pi). Keeping ~4 nearby stops means the process runs in about ~60M,
versus ~400M for the entire GTFS database.

```
[Upcoming]
  InterestingStopIds = 700000000229,700000000240
```

If you are running on very small hardware with multiple cores, `--loader_multiprocess_model=process`
will likely speed up GTFS database loading proportional to the number of cores you have.