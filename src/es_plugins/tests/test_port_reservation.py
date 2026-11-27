import errno
import os
import socket
import time

import pytest
from loguru import logger

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
# on Linux. The reserved sockets carry SO_REUSEADDR, so a socket that carries it too may bind a port
# that is not listening: no plugin can bind at all (bind_refusal), and the kernel picks no port of
# the node's range by itself.
@pytest.mark.linux
@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
@pytest.mark.parametrize("listen", [False, True])
@pytest.mark.parametrize("taken", [False, True])
def test_a_socket_without_so_reuseaddr_cannot_bind_a_reserved_port(reservation, host, listen, taken):
    held, (port, _) = reservation
    if taken:
        held.take(port, placement_id=7)

    assert bind_error(port, listen=listen, host=host) == errno.EADDRINUSE


@pytest.mark.linux
@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
@pytest.mark.parametrize("reuse", [False, True])
def test_no_socket_can_bind_a_port_while_it_listens(reservation, host, reuse):
    held, (port, _) = reservation
    held.take(port, placement_id=7)

    assert bind_error(port, reuse=reuse, listen=False, host=host) == errno.EADDRINUSE


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


# Resetting the queue of a listening socket with shutdown is Linux behaviour.
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


@pytest.mark.linux
def test_a_port_in_use_by_one_placement_is_refused_to_another_until_given_back(reservation):
    held, (port, _) = reservation
    held.take(port, placement_id=7)

    with pytest.raises(PortUnavailableError, match="still in use by placement 7"):
        held.take(port, placement_id=8)
    held.give_back(port, placement_id=8)  # not its port: nothing happens
    with pytest.raises(PortUnavailableError):
        held.take(port, placement_id=8)

    held.give_back(port, placement_id=7)
    held.take(port, placement_id=8)
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


@pytest.fixture
def elsewhere():
    """A listener a plugin could connect its fd 3 to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        yield listener.getsockname()


def as_a_plugin(descriptor: int) -> socket.socket:
    """The reservation socket as a plugin process holds it: the same socket, another descriptor."""
    return socket.socket(fileno=os.dup(descriptor))


def connected_elsewhere(descriptor: int, address) -> None:
    """What a plugin may do with its fd 3: stop it listening and connect it somewhere, then exit."""
    with as_a_plugin(descriptor) as plugin_side:
        plugin_side.shutdown(socket.SHUT_RDWR)
        plugin_side.connect(address)


def serves(port: int) -> bool:
    return connection_error(port) is None


@pytest.mark.linux
def test_a_socket_a_plugin_connected_elsewhere_is_replaced_when_given_back(reservation, elsewhere):
    held, (port, _) = reservation
    descriptor = held.take(port, placement_id=7)
    connected_elsewhere(descriptor, elsewhere)

    held.give_back(port, placement_id=7)

    # Held again, by a socket of its own: nothing else can bind it, and it does not listen.
    assert bind_error(port) == errno.EADDRINUSE
    assert connection_error(port) == errno.ECONNREFUSED
    held.take(port, placement_id=8)
    assert serves(port)


def accepts_from(descriptor: int, port: int) -> bool:
    """Whether a connection to `port` reaches the listening socket `descriptor`."""
    with socket.socket(fileno=os.dup(descriptor)) as listener:
        listener.settimeout(5)
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            served, _ = listener.accept()
            served.close()
    return True


@pytest.mark.linux
def test_a_copy_of_a_given_back_socket_never_serves_the_next_placement(reservation):
    held, (port, _) = reservation
    # What another plugin holds after the placement's process passed it its fd 3.
    copy = as_a_plugin(held.take(port, placement_id=7))
    held.give_back(port, placement_id=7)

    fresh = held.take(port, placement_id=8)

    with pytest.raises(OSError) as refused:
        copy.listen(8)
    assert refused.value.errno == errno.EADDRINUSE
    assert accepts_from(fresh, port)
    with socket.socket(fileno=os.dup(fresh)) as taken:
        assert taken.getsockname() == ("0.0.0.0", port)
        with pytest.raises(OSError) as unconnected:
            taken.getpeername()
        assert unconnected.value.errno == errno.ENOTCONN
    copy.close()


@pytest.mark.linux
def test_a_copy_listening_again_before_the_port_is_taken_keeps_it_unusable_until_closed(reservation):
    held, (port, _) = reservation
    copy = as_a_plugin(held.take(port, placement_id=7))
    held.give_back(port, placement_id=7)
    copy.listen(8)

    with pytest.raises(PortUnavailableError, match=f"port {port} cannot listen: another socket"):
        held.take(port, placement_id=8)
    copy.close()

    fresh = held.take(port, placement_id=8)
    assert accepts_from(fresh, port)


@pytest.mark.linux
def test_a_socket_a_plugin_connected_elsewhere_and_still_holds_does_not_keep_the_port(
    reservation, elsewhere
):
    held, (port, _) = reservation
    plugin_side = as_a_plugin(held.take(port, placement_id=7))
    plugin_side.shutdown(socket.SHUT_RDWR)
    plugin_side.connect(elsewhere)

    held.give_back(port, placement_id=7)
    fresh = held.take(port, placement_id=8)

    assert accepts_from(fresh, port)
    plugin_side.close()


def tcp_states_on(port: int) -> set[str]:
    """The states, as `/proc/net/tcp` spells them, of the IPv4 TCP sockets with local port `port`."""
    with open("/proc/net/tcp") as table:
        rows = [line.split() for line in table.readlines()[1:]]
    return {row[3] for row in rows if int(row[1].rsplit(":", 1)[1], 16) == port}


TCP_TIME_WAIT = "06"


@pytest.mark.linux
def test_a_port_whose_plugin_closed_a_connection_is_taken_again_at_once(reservation):
    held, (port, _) = reservation
    with as_a_plugin(held.take(port, placement_id=7)) as plugin_side:
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        served, _ = plugin_side.accept()
        # The server closes first, as uvicorn does with an idle keep-alive: its end then waits
        # in TIME_WAIT on the plugin's port for a minute.
        served.close()
        assert client.recv(1) == b""
        client.close()
    deadline = time.monotonic() + 5
    while TCP_TIME_WAIT not in tcp_states_on(port) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert TCP_TIME_WAIT in tcp_states_on(port)
    warnings = []
    sink = logger.add(warnings.append, format="{message}", level="WARNING")
    try:
        held.give_back(port, placement_id=7)
        fresh = held.take(port, placement_id=8)
    finally:
        logger.remove(sink)

    assert accepts_from(fresh, port)
    assert warnings == []


@pytest.mark.linux
def test_even_an_unchanged_socket_is_replaced_when_its_port_is_given_back(reservation):
    held, (port, _) = reservation
    served = os.fstat(held.take(port, placement_id=7)).st_ino

    held.give_back(port, placement_id=7)
    fresh = held.take(port, placement_id=8)

    assert os.fstat(fresh).st_ino != served
    assert serves(port)
