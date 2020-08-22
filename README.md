# gtfs-upcoming

## What

This consumes a GTFS realtime feed and produces a list of upcoming
buses (and trains, trams, etc.) for a given stops.

This was developed against the Irish [NTA's GTFS-R feed](https://developer.nationaltransport.ie/api-details#api=gtfsr).

This is part of a personal project for an live upcoming transit display.
The display previously relied on the now-deprecated SmartDublin RTPI service.
I intend to add a simple JSON-over-HTTP component to this code in future.

## Example

```sh
% main.py --config=config.ini --env=prod
...
Upcoming(route='18', route_type='BUS', headsign='Sandymount - Palmerstown', destination='Hollyville Lawn, stop 4357', direction='1', due=datetime.time(13, 47))
Upcoming(route='18', route_type='BUS', headsign='Sandymount - Palmerstown', destination='Hollyville Lawn, stop 4357', direction='1', due=datetime.time(14, 7))
```

## Build

This project is built with [Bazel](http://bazel.build). If you have bazel,
then building/running is trivial:

```sh
% bazel run :main -- [--config CONFIG] [--env {prod,test}] [--gtfs GTFS]
```

### Without bazel

It is *presently* possible to run without bazel. To do so:

```sh
% pip3 install gtfs-realtime-bindings
% ./main.py [--config CONFIG] [--env {prod,test}] [--gtfs GTFS]
```

## GTFS Data

You will need the GTFS dataset (contains definitions for routes, stops,
stop times, and agencies) in order to interpret the realtime data
correctly. This is available from your GTFS-R provider.
