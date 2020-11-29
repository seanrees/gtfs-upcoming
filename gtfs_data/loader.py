import collections
import concurrent.futures
import csv
import logging
import io
import os

from typing import AbstractSet, Dict, List, MutableSet, Tuple

# Some NTA data files have a single unprintable character upfront; this will cause
# DictReader to include that character in the key for the first field.
BROKEN_CHARACTER = '\ufeff'


def loadChunk(io: io.StringIO, keep: Dict[str, AbstractSet[str]]=None) -> Tuple[List[Dict[str,str]], int]:
  """Worker code for LoadParallel.

  Args:
    io: a StringIO to read from
    keep: same as in LoadParallel

  Returns:
    A tuple containing a list of Dict[str, str] for each row matching keep,
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


def Load(filename: str, keep: Dict[str, AbstractSet[str]]=None) -> List[Dict[str,str]]:
  """Loads GTFS package data from a given file.

  Args:
    filename: relative or absolute path to a GTFS txt data file
    keep: an allow list keys and allowable values. If there are multiple keys, then each
      row read much have an acceptable value for each key.

  Returns:
    A list of Dict[str,str] for each row matching keep.

  Raises:
    FileNotFoundError if filename isn't present.
  """
  # Tunables: the workers are very CPU-bound.
  workers = os.cpu_count()
  linesPerChunk = 100000

  pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
  futures = []

  keep = keep or {}

  # We will read linesPerChunk into a StringIO, then pass it to a worker
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
      if count % linesPerChunk == 0:
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

  # Collect future results.
  ret = []
  discard = 0
  for ft in futures:
    r, d = ft.result()
    ret += r
    discard += d

  logging.debug('Loaded "%s": %d rows loaded, %d discarded (filtering on=%s)',
    filename, len(ret), discard, keep.keys())

  return ret
