#!/bin/sh
date
curl -s http://192.168.0.9/temp | jq ".temp"
curl -s 'http://192.168.0.10/relay/0' | jq ".ison"
echo ""
