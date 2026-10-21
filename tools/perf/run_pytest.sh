#!/bin/bash
# usage: a12_t.sh <logname> <pytest args...>
cd /opt/spectrek_fsp/work/ag_a12/w
L=/opt/spectrek_fsp/work/ag_a12/logs; mkdir -p $L
n=$1; shift
docker run --rm --name a12-$n --user 0 -v $PWD:/w -w /w/backend --memory 1200m --cpus 1 -e DATABASE_URL=sqlite:////tmp/t.db -e LLM_DISABLED=true -e DEV_MODE=true -e MARKET_MODE_REPORT=/w/mm_leaks.json spectrek_fsp-api:integ python -m pytest -q -p no:cacheprovider "$@" > $L/$n.log 2>&1
tail -40 $L/$n.log
