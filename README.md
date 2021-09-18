![build and tests](https://github.com/seanrees/gtfs-upcoming/actions/workflows/build.yml/badge.svg)

# gtfs-upcoming

## What

This consumes a GTFS realtime feed and produces a list of upcoming
buses (and trains, trams, etc.) for a given stops. This list is
served via HTTP in JSON format at /upcoming.json.

/upcoming.json will serve both live (currently operating) and scheduled services
(from the GTFS data). Live data takes precedence over scheduled data for the same
trip. If a stop is near an origin of a service, live data may not yet be
available.

This was developed against the Irish [NTA's GTFS-R feed](https://developer.nationaltransport.ie/api-details#api=gtfsr).

This is part of a personal project for an live upcoming transit display.
The display previously relied on the now-deprecated SmartDublin RTPI service.

## Usage

```sh
% main.py --config=config.ini --env=prod --port=6824 --promport=8000
...
2020/08/23 08:58:09    INFO Starting HTTP server on port 6824
```

Then browse to http://127.0.0.1:6824/upcoming.json

### Sample Output

This output is subject to change.

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

## Build

This project is built with [Bazel](http://bazel.build). If you have bazel,
then building/running is trivial:

```sh
% bazel run :main -- [--config CONFIG] [--env {prod,test}] [--gtfs GTFS] [--port PORT]
```

The BUILD file also defines a Debian (.deb) build target.

## Data and Configuration

### GTFS Data

You will need the GTFS dataset (contains definitions for routes, stops,
stop times, and agencies) in order to interpret the realtime data
correctly. This is available from your GTFS-R provider.

For the Irish NTA, that is [here](https://www.transportforireland.ie/transitData/google_transit_combined.zip).

### config.ini

Server configuration is an INI file and has two sections:

1. NTA section: API keys
1. Upcoming section: Interesting Stops

#### API Keys

This is specific to the Irish NTA. If you are using another provider, you're
going to need to make changes to the code and this section is irrelevant.

```
[NTA]
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
