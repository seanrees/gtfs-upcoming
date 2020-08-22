import site
import sys

def _fix_pip_paths():
  """Workaround for a overlapping subtree pip modules.

  Bazel's pip_install() installs each pip in their own directory.
  This doesn't play well if >1 pip have overlapping module paths
  (e.g; one provides foo/bar and the other provides foo/baz). The first
  one loaded "owns" foo/*; which causes imports in the other tree to fail.

  We depend on gtfs-realtime-transit and protobuf, both provide their
  modules underneath google/. This module notices when these libraries
  are provided via PYTHONPATH and loads them independently to workaround
  this issue.
  """
  libs = ['gtfs_realtime_bindings', 'protobuf']

  for path in sys.path:
    for l in libs:
      if l in path:
        site.addsitedir(path)

_fix_pip_paths()
