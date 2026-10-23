#!/bin/sh
# Explicit operator job entry; installs/enables no schedule or credentials.
# ROOT APPROVAL [CONFIRMED_DELIVERY_POLICY PRIVATE_SECRET_FILE]
set -eu
if [ "$#" -ne 2 ] && [ "$#" -ne 4 ]; then
  echo 'usage: production_hourly.sh ROOT APPROVAL [DELIVERY_POLICY SECRET_FILE]' >&2
  exit 2
fi
board-clank-hourly --root "$1" --approval "$2" once
if [ "$#" -eq 4 ]; then
  board-clank-discord deliver --root "$1" --approval "$2" --policy "$3" --secret-file "$4"
fi
