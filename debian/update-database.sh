#!/bin/sh
#
# Re-download the NTA GTFS database and restart gtfs-upcoming if the data has
# changed upstream.
#

url=https://www.transportforireland.ie/transitData/google_transit_combined.zip
cachedir=/var/cache/gtfs

# Create the directory if we need it.
if [ ! -d ${cachedir} ]; then
  mkdir -p ${cachedir}
fi


# Check diffs.
tmp=$(mktemp)
trap "rm -f ${tmp}" EXIT

curl -s --head ${url} -o ${tmp}
newlm=$(grep -i last-modified ${tmp})
newcl=$(grep -i content-length ${tmp})

overwrite=0

if [ -f ${cachedir}/.lastmodified ]; then
  oldlm=$(cat ${cachedir}/.lastmodified)
  if [ "${oldlm}" != "${newlm}" ]; then
    overwrite=1
  fi
else
  # Unconditionally overwrite if no data.
  overwrite=1
fi

if [ -f ${cachedir}/.lastlength ]; then
  oldcl=$(cat ${cachedir}/.lastlength)
  if [ "${oldcl}" != "${newcl}" ]; then
    overwrite=1
  fi
else
  # Unconditionally overwrite if no data.
  overwrite=1
fi


if [ ${overwrite} = 1 ]; then
  cd ${cachedir}
  curl -o data.zip -s ${url}
  unzip -o -q data.zip
  rm -f data.zip
  echo $newlm > .lastmodified
  echo $newcl > .lastlength

  if [ "$(systemctl is-active gtfs-upcoming)" = "active" ]; then
    systemctl restart gtfs-upcoming
  fi
fi
