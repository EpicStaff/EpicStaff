import errno
import socket

import pytest

from es_plugins.agent.port_reservation import (
    PortReservation,
    PortReservationError,
    PortUnavailableError,
)
from tests.helpers import free_port, free_ports


@pytest.fixture
def reservation():
    ports = free_ports(2)
    held = PortReservation(ports)
    held.reserve()
    yield held, ports
    held.close()


def bind_error(port: int, *, reuse: bool = False, listen: bool = True, host: str = "0.0.0.0"):
    """The errno another socket gets binding `port` (and listening on it), or None if it can."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        if reuse:
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            other.bind((host, port))
            if listen:
                other.listen(1)
        except OSError as error:
            return error.errno
    return None


# BSD lets a socket with SO_REUSEADDR bind a specific address under a wildcard one; the node runs
# on Linux, where nothing may share a port with a socket bound without SO_REUSEADDR.
@pytest.mark.linux
@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("listen", [False, True])
def test_no_other_socket_can_bind_a_reserved_port_listening_or_not(
    reservation, host, reuse, listen
):
    _, (port, unused) = reservation

    assert bind_error(unused, reuse=reuse, listen=listen, host=host) == errno.EADDRINUSE


def connection_error(port: int):
    """The errno connecting to `port` gives, or None when something accepts the connection."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            return None
    except OSError as error:
        return error.errno


@pytest.mark.linux
def test_only_a_taken_port_accepts_connections(reservation):
    held, (port, unused) = reservation

    held.take(port, placement_id=7)

    assert connection_error(port) is None
    assert connection_error(unused) == errno.ECONNREFUSED


# Stopping a listening socket with shutdown, keeping its port, is Linux behaviour.
@pytest.mark.linux
def test_a_port_given_back_refuses_connections_and_stays_held(reservation):
    held, (port, _) = reservation
    held.take(port, placement_id=7)
    queued = socket.create_connection(("127.0.0.1", port), timeout=5)

    held.give_back(port, placement_id=7)

    # A connection still queued for the old plugin is reset: the next one never accepts it.
    with pytest.raises(ConnectionResetError):
        queued.recv(1)
    queued.close()
    assert connection_error(port) == errno.ECONNREFUSED
    assert bind_error(port) == errno.EADDRINUSE
    assert bind_error(port, reuse=True) == errno.EADDRINUSE


@pytest.mark.linux
def test_a_port_in_use_by_one_placement_is_refused_to_another_until_given_back(reservation):
    held, (port, _) = reservation
    descriptor = held.take(port, placement_id=7)

    with pytest.raises(PortUnavailableError, match="still in use by placement 7"):
        held.take(port, placement_id=8)
    held.give_back(port, placement_id=8)  # not its port: nothing happens
    with pytest.raises(PortUnavailableError):
        held.take(port, placement_id=8)

    held.give_back(port, placement_id=7)
    assert held.take(port, placement_id=8) == descriptor
    assert connection_error(port) is None


def test_taking_a_port_again_for_the_same_placement_gives_the_same_descriptor(reservation):
    held, (port, _) = reservation

    assert held.take(port, placement_id=7) == held.take(port, placement_id=7)


def test_a_port_the_node_does_not_hold_is_refused(reservation):
    held, _ = reservation

    with pytest.raises(PortUnavailableError, match="is not one of this node's ports"):
        held.take(free_port(), placement_id=7)


def test_a_port_that_cannot_be_bound_stops_the_reservation_and_frees_the_others():
    first, taken = free_ports(2)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as squatter:
        squatter.bind(("0.0.0.0", taken))
        squatter.listen(1)
        reservation = PortReservation([first, taken])

        with pytest.raises(PortReservationError, match=f"port {taken} of the node's range"):
            reservation.reserve()

    assert bind_error(first) is None


def test_closing_frees_every_port(reservation):
    held, ports = reservation
    held.take(ports[0], placement_id=7)

    held.close()

    assert [bind_error(port) for port in ports] == [None, None]
