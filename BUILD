load("@pypi//:requirements.bzl", "requirement")
load("@rules_pkg//:pkg.bzl", "pkg_deb", "pkg_tar")
load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@rules_python//python:pip.bzl", "compile_pip_requirements")

compile_pip_requirements(
    name = "requirements",
    src = "requirements.in",
    requirements_txt = "requirements_lock.txt",
    requirements_windows = "requirements_windows.txt",
)

py_binary(
    name = "main",
    srcs = ["main.py"],
    deps = [
        ":fetch",
        ":httpd",
        ":transit",
        "//gtfs_data:database",
        requirement("prometheus_client"),
    ],
)

pkg_tar(
    name = "deb-bin",
    # This depends on --build_python_zip.
    srcs = [":main"],
    mode = "0755",
    package_dir = "/opt/gtfs-upcoming/bin",
)

pkg_tar(
    name = "deb-config-sample",
    srcs = ["config-sample.ini"],
    mode = "0644",
    package_dir = "/etc/gtfs-upcoming",
)

pkg_tar(
    name = "deb-default",
    srcs = ["debian/gtfs-upcoming"],
    mode = "0644",
    package_dir = "/etc/default",
)

pkg_tar(
    name = "deb-service",
    srcs = ["debian/gtfs-upcoming.service"],
    mode = "0644",
    package_dir = "/lib/systemd/system",
)

pkg_tar(
    name = "deb-update-database",
    # This depends on --build_python_zip.
    srcs = ["debian/update-database.sh"],
    mode = "0755",
    package_dir = "/opt/gtfs-upcoming/bin",
)

pkg_tar(
    name = "deb-update-database-cron",
    srcs = ["debian/gtfs-upcoming-update-database.sample"],
    mode = "0755",
    package_dir = "/etc/cron.d",
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
    ],
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
        "unzip",
    ],
    description_file = "debian/description",
    maintainer = "Sean Rees <sean at erifax.org>",
    package = "gtfs-upcoming",
    postinst = "debian/postinst",
    postrm = "debian/postrm",
    prerm = "debian/prerm",
    version = "1.0.1",
)

py_library(
    name = "httpd",
    srcs = ["httpd.py"],
    deps = [
        requirement("prometheus_client"),
    ],
)

py_library(
    name = "fetch",
    srcs = ["fetch.py"],
    deps = [
        requirement("prometheus_client"),
    ],
)

py_library(
    name = "transit",
    srcs = ["transit.py"],
    deps = [
        "//gtfs_data:database",
        requirement("gtfs-realtime-bindings"),
        requirement("prometheus_client"),
        requirement("six"),
    ],
)

py_test(
    name = "transit_test",
    srcs = ["transit_test.py"],
    data = [
        "testdata/gtfsv1-sample-onetrip.json",
        "testdata/gtfsv1-sample-twotrips.json",
        "//gtfs_data:exported_testdata",
    ],
    deps = [
        ":transit",
        "//gtfs_data:database",
        requirement("protobuf"),
        requirement("gtfs-realtime-bindings"),
    ],
)
