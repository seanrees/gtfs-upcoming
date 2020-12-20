load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")
load("@pip_deps//:requirements.bzl", "requirement")

py_library(
    name = "loader",
    srcs = ["loader.py"],
    visibility = [
        "//:__pkg__",
    ],
)

py_test(
    name = "loader_test",
    srcs = ["loader_test.py"],
    data = [
        "testdata/agency.txt",
        "testdata/calendar.txt",
    ],
    deps = [
        ":loader",
    ],
)

py_library(
    name = "database",
    srcs = ["database.py"],
    visibility = [
        "//:__pkg__",
    ],
    deps = [
        ":loader",
        requirement("prometheus_client")
    ],
)

filegroup(
    name = "exported_testdata",
    srcs = glob(["testdata/*"]),
    visibility = [
        "//:__pkg__",
    ],
)

py_test(
    name = "database_test",
    srcs = ["database_test.py"],
    data = [
        ":exported_testdata",
    ],
    deps = [
        ":database",
    ],
)
