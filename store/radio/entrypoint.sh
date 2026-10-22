#!/bin/sh
# Radio's store form: SDRplay's API service, then the server.
#
# SDRplay's API is two halves: a service that owns the receiver's USB
# device, and the library SoapySDRPlay3 loads, which talks to the service
# through shared memory. They must share a /dev/shm, so the service runs
# here in the container rather than on the controller (which then needs
# nothing installed for an RSP; the same choice as SIGINT's image on shack).
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
# Without an SDRplay plugged in the service idles; a missing service (an
# image built without the SDRplay files) only means no RSP will open.
set -eu

if [ -x /usr/local/bin/sdrplay_apiService ]; then
    /usr/local/bin/sdrplay_apiService &
    svc=$!
    # The service is ready to answer within a second of starting; the
    # server's first open comes later than that anyway (it reads its
    # config and starts its threads first), and a first open that still
    # fails is retried by the server like any radio that will not open.
    sleep 1
    kill -0 "$svc" 2>/dev/null || echo "sdrplay_apiService exited at once: no SDRplay receiver will open" >&2
fi

exec python3 -m ohsradio --server "$@"
