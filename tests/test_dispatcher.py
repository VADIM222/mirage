import threading

from mirage.dispatcher import Dispatcher


def test_queued_completion_holds_instance_until_acknowledged():
    dispatcher = Dispatcher(workers=1)
    delivered = threading.Event()
    results = []
    def complete(*args):
        results.append(args)
        delivered.set()
    try:
        assert dispatcher.submit("farm", lambda cancelled: 42, complete)
        assert delivered.wait(3)
        assert dispatcher.busy("farm")
        assert not dispatcher.submit("farm", lambda cancelled: 99, complete)
        dispatcher.cancel("farm")
        assert not dispatcher.acknowledge(results[0][0], results[0][1])
        assert not dispatcher.busy("farm")
    finally:
        dispatcher.shutdown()
