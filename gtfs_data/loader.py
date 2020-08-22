import collections
import csv
import logging

from typing import AbstractSet, Dict, List, MutableSet

# Some NTA data files have a single unprintable character upfront; this will cause
# DictReader to include that character in the key for the first field.
BROKEN_CHARACTER = '\ufeff'


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
  ret = []
  discard = 0
  keep = keep or {}

  with open(filename, newline='') as f:
    # If a broken character is present, read it out of the buffer. If not
    # seek back.
    first = f.read(1)
    if first != BROKEN_CHARACTER:
      f.seek(0)

    reader = csv.DictReader(f)

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

  logging.debug('Loaded "%s": %d rows loaded, %d discarded (filtering on=%s)',
    filename, len(ret), discard, keep.keys())

  return ret
