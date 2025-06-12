from __future__ import annotations

import concurrent.futures
import csv
import io
import logging
import threading
from collections.abc import Set as AbstractSet

logger = logging.getLogger(__name__)


# Some NTA data files have a single unprintable character upfront; this will cause
# DictReader to include that character in the key for the first field.
BROKEN_CHARACTER = '\ufeff'

# Module-level tunables
MaxThreads = 4
MaxRowsPerChunk = 100000

class BufferedExecutor:
  """Creates and wraps a ProcessPoolExecutor to limit the number of futures in flight.

  Each future acquires a semaphore on creation, and releases it upon completion. The
  semaphore is set to max_workers*2-1 to allow for queued work to be ready for the next
  worker.

  The use in this module is intended to provide some back-pressure on reading the
  input file; if we create futures much faster than we can process them, we will
  potentially overwhelm memory on a small system with lots of StringIOs.
  """
  def __init__(self, max_workers:int=0):
    self._pool = concurrent.futures.ProcessPoolExecutor(max_workers=max_workers)
    self._sem = threading.Semaphore(value=max_workers*2-1)

  def submit(self, *args, **kwargs):
    self._sem.acquire()
    f = self._pool.submit(*args, **kwargs)
    f.add_done_callback(lambda _: self._sem.release())
    return f


def loadChunk(io: io.StringIO, keep: dict[str, AbstractSet[str]] | None = None) -> tuple[list[dict[str,str]], int]:
  """Worker code for LoadParallel.

  Args:
    io: a StringIO to read from
    keep: same as in LoadParallel

  Returns:
    A tuple containing a list of dict[str, str] for each row matching keep,
    and an integer for each discarded row.
  """
  ret = []
  discard = 0
  keep = keep or {}

  reader = csv.DictReader(io)

  for row in reader:
    match = True
    for k, acceptable_values in keep.items():
      if row[k] not in acceptable_values:
        match = False
        break

    if match:
      ret.append(row)
    else:
      discard += 1

  return ret, discard


def Load(filename: str, keep: dict[str, AbstractSet[str]] | None = None) -> list[dict[str,str]]:
  """Loads GTFS package data from a given file.

  Args:
    filename: relative or absolute path to a GTFS txt data file
    keep: an allow list keys and allowable values. If there are multiple keys, then each
      row read much have an acceptable value for each key.

  Returns:
    A list of dict[str,str] for each row matching keep.

  Raises:
    FileNotFoundError if filename isn't present.
  """
  keep = keep or {}
  pool = BufferedExecutor(max_workers=MaxThreads)
  futures = []

  # We will read MaxRowsPerChunk into a StringIO, then pass it to a worker
  # to parse the CSV.
  with open(filename) as f:
    # If a broken character is present, read it out of the buffer. If not
    # seek back.
    first = f.read(1)
    if first != BROKEN_CHARACTER:
      f.seek(0)

    # Includes fieldnames.
    header = f.readline()
    count = 0
    accum = io.StringIO()

    for line in f:
      if count % MaxRowsPerChunk == 0:
        if accum.tell() > 0:
          accum.seek(0)
          futures.append(pool.submit(loadChunk, accum, keep))

        accum = io.StringIO()
        accum.write(header)
        count = 0

      accum.write(line)
      count += 1

    # Clear out any remaining lines.
    if accum.tell() > 0:
      accum.seek(0)
      futures.append(pool.submit(loadChunk, accum, keep))

  ret = []
  discard = 0
  for ft in futures:
    r, d = ft.result()
    ret += r
    discard += d

  logger.debug('Loaded "%s": %d rows loaded, %d discarded (filtering on=%s)',
    filename, len(ret), discard, keep.keys())

  return ret
