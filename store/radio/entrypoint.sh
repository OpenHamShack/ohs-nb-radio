#!/bin/sh
# Radio's store form: SDRplay's API service, then the server.
#
# SDRplay's API is two halves: a service that owns the receiver's USB
# device, and the library a client loads (shack_sdr's binding; or
# SoapySDRPlay3 in an image that still carries it), which talks to the service
# through shared memory. They must share a /dev/shm, so the service runs
# here in the container rather than on the controller (which only stages
# SDRplay's files as a host library and runs nothing of theirs itself).
# It runs as the container's user: the controller's udev rule for the RSP
# (Host -> Hardware, 1df7:3030 to plugdev) and podman's keep-groups give
# that user the device.
#
# Then `exec`, so the server is the container's first process and gets the
# stop signal itself, exactly as when it was the ENTRYPOINT: its shutdown
# (unkey, close the sockets, release the broker's claims) is timed against
# the module's stop_timeout (GUIDE 5), and a shell in between would have to
# forward the signal and wait, with its own way to get that wrong. The
# service is left to die with the container: it holds nothing that needs a
# clean stop, and the next start resets the receiver.
#
# Without an SDRplay plugged in the service idles; a missing service (a
# controller without the host library) only means no RSP will open, and
# Radio says why ("Ask your controller's administrator to install
# SDRplay's API").
set -eu

# Where the service comes from: the controller's host library when the
# administrator installed one (RADIO-SDR-PLAN 6.3: $SHACK_HOSTLIBS/sdrplay-api,
# /opt/hostlibs/sdrplay-api, mounted read-only by the platform). An image
# built with SHACK_STORE_DROP_SDRPLAY=0 still carries its own copy in
# /usr/local, used only when the controller has none.
#
# The service and the library a client loads must be the same version, so
# when the host's is there the library is taken from beside it too:
# shack_sdr's SDRplay binding looks there first by itself, and
# LD_LIBRARY_PATH puts it before /usr/local/lib for SoapySDRPlay3 in such
# an older-style image.
#
# No SHACK_HOSTLIBS at all means a controller older than host libraries
# (platform beta.9), which ignored the manifest's host_libraries and
# mounted nothing: said here for the log, and by the app in its state and
# status page ("Update the controller to use SDRplay radios and DAB+",
# ohscore/hostlibs.py). Everything else works; nothing here fails on it.
if [ -z "${SHACK_HOSTLIBS:-}" ]; then
    echo "SHACK_HOSTLIBS is not set: this controller predates host libraries, so no SDRplay RSP or DAB+ (update the controller)" >&2
fi
API="${SHACK_HOSTLIBS:-/opt/hostlibs}/sdrplay-api"
if [ -e "$API/libsdrplay_api.so.3" ]; then
    export LD_LIBRARY_PATH="$API${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
SVC=""
for c in "$API/sdrplay_apiService" /usr/local/bin/sdrplay_apiService; do
    if [ -x "$c" ]; then SVC=$c; break; fi
done
if [ -n "$SVC" ]; then
    "$SVC" &
    svc=$!
    # The service is ready to answer within a second of starting; the
    # server's first open comes later than that anyway (it reads its
    # config and starts its threads first), and a first open that still
    # fails is retried by the server like any radio that will not open.
    sleep 1
    kill -0 "$svc" 2>/dev/null || echo "sdrplay_apiService exited at once: no SDRplay receiver will open" >&2
fi

exec python3 -m ohsradio --server "$@"
