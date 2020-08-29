load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@pip_deps//:requirements.bzl", "requirement")
load("@rules_pkg//:pkg.bzl", "pkg_tar", "pkg_deb")

py_binary(
    name = "main",
    srcs = ["main.py"],
    deps = [
        ":httpd",
        ":nta",
        ":transit",
        "//gtfs_data:database",
        requirement("prometheus_client")
    ],
)

pkg_tar(
    name = "deb-bin",
    package_dir = "/opt/gtfs-upcoming/bin",
    # This depends on --build_python_zip.
    srcs = [":main"],
    mode = "0755",
)

pkg_tar(
    name = "deb-config-sample",
    package_dir = "/etc/gtfs-upcoming",
    srcs = ["config-sample.ini"],
    mode = "0644",
)

pkg_tar(
    name = "deb-default",
    package_dir = "/etc/default",
    srcs = ["debian/gtfs-upcoming"],
    mode = "0644",
    strip_prefix = "debian/"
)

pkg_tar(
    name = "deb-service",
    package_dir = "/lib/systemd/system",
    srcs = ["debian/gtfs-upcoming.service"],
    mode = "0644",
    strip_prefix = "debian/"
)


pkg_tar(
    name = "deb-update-database",
    package_dir = "/opt/gtfs-upcoming/bin",
    # This depends on --build_python_zip.
    srcs = ["debian/update-database.sh"],
    mode = "0755",
)

pkg_tar(
    name = "deb-update-database-cron",
    package_dir = "/etc/cron.d",
    srcs = ["debian/gtfs-upcoming-update-database"],
    mode = "0755",
    strip_prefix = "debian/"
)

pkg_tar(
    name = "debian-data",
    deps = [
      ":deb-bin",
      ":deb-config-sample",
      ":deb-default",
      ":deb-service",
      ":deb-update-database",
      ":deb-update-database-cron",
    ]
)

pkg_deb(
    name = "main-deb",
    architecture = "all",
    built_using = "bazel",
    data = ":debian-data",
    depends = [
        "python3",
        # For refreshing the GTFS database
        "curl",
        "unzip"
    ],
    postinst = "debian/postinst",
    prerm = "debian/prerm",
    postrm = "debian/postrm",
    description_file = "debian/description",
    maintainer = "Sean Rees <sean at erifax.org>",
    package = "gtfs-upcoming",
    version = "0.0.1",
)


py_library(
    name = "httpd",
    srcs = ["httpd.py"],
    deps = [
        requirement("prometheus_client")
    ]
)

py_library(
    name = "nta",
    srcs = ["nta.py"],
    deps = [
        requirement("prometheus_client")
    ],
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
        requirement("prometheus_client")
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
