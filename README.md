# gtfs-upcoming

## What

This consumes a GTFS realtime feed and produces a list of upcoming
buses (and trains, trams, etc.) for a given stops. This list is
served via HTTP in JSON format at /upcoming.json.

This was developed against the Irish [NTA's GTFS-R feed](https://developer.nationaltransport.ie/api-details#api=gtfsr).

This is part of a personal project for an live upcoming transit display.
The display previously relied on the now-deprecated SmartDublin RTPI service.

## Example

```sh
% main.py --config=config.ini --env=prod --port=6824
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
         "route":"7",
         "route_type":"BUS",
         "headsign":"Bride's Glen Bus Stop - Mountjoy Square Nth",
         "direction":"1",
         "dueTime":"20:57:01",
         "dueInSeconds":17.0
      },
      {
         "route":"7A",
         "route_type":"BUS",
         "headsign":"Loughlinstown Wood Estate - Mountjoy Square Nth",
         "direction":"1",
         "dueTime":"21:10:33",
         "dueInSeconds":829.0
      }
   ]
}
```

## Build

This project is built with [Bazel](http://bazel.build). If you have bazel,
then building/running is trivial:

```sh
% bazel run :main -- [--config CONFIG] [--env {prod,test}] [--gtfs GTFS] [--port PORT]
```

### Without bazel

It is *presently* possible to run without bazel. To do so:

```sh
% pip3 install gtfs-realtime-bindings
% ./main.py [--config CONFIG] [--env {prod,test}] [--gtfs GTFS] [--port PORT]
```

## GTFS Data

You will need the GTFS dataset (contains definitions for routes, stops,
stop times, and agencies) in order to interpret the realtime data
correctly. This is available from your GTFS-R provider.
