load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@pip_deps//:requirements.bzl", "requirement")

py_binary(
    name = "main",
    srcs = ["main.py"],
    deps = [
        ":httpd",
        ":nta",
        ":transit",
        "//gtfs_data:database",
    ],
)

py_library(
    name = "httpd",
    srcs = ["httpd.py"]
)

py_library(
    name = "nta",
    srcs = ["nta.py"],
)

py_library(
    name = "aapipfix",
    srcs = ["aapipfix.py"]
)

py_library(
    name = "transit",
    srcs = ["transit.py"],
    deps = [
        ":aapipfix",
        "//gtfs_data:database",
        requirement("gtfs-realtime-bindings"),
    ],
)

py_test(
    name = "transit_test",
    srcs = ["transit_test.py"],
    deps = [
        ":aapipfix",
        ":transit",
        "//gtfs_data:database",
        requirement("protobuf"),
        requirement("gtfs-realtime-bindings"),
    ],
    data = [
        "testdata/gtfsv1-sample.json",
        "//gtfs_data:exported_testdata"
    ]
)
