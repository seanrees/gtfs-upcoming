load("@pypi//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")

py_library(
    name = "loader",
    srcs = ["loader.py"],
    visibility = [
        "//:__pkg__",
    ],
)

py_test(
    name = "loader_test",
    size = "small",
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
        requirement("prometheus_client"),
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
    size = "small",
    srcs = ["database_test.py"],
    data = [
        ":exported_testdata",
    ],
    deps = [
        ":database",
    ],
)
