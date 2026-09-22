from app import broker, config


class FakeChannel:
    def __init__(self):
        self.exchanges = []
        self.queues = []
        self.bindings = []

    def exchange_declare(self, exchange, exchange_type, durable):
        self.exchanges.append((exchange, exchange_type, durable))

    def queue_declare(self, queue, durable, arguments=None):
        self.queues.append((queue, durable, arguments))

    def queue_bind(self, queue, exchange, routing_key=None):
        self.bindings.append((queue, exchange, routing_key))


def test_topology_declares_topic_and_dead_letter_exchanges():
    channel = FakeChannel()
    broker.declare_topology(channel)
    assert (config.EXCHANGE, "topic", True) in channel.exchanges
    assert (config.DLX, "fanout", True) in channel.exchanges


def test_topology_declares_all_durable_queues():
    channel = FakeChannel()
    broker.declare_topology(channel)
    assert {item[0] for item in channel.queues} == {*config.QUEUES, config.DLQ}
    assert all(item[1] for item in channel.queues)


def test_main_queues_dead_letter_to_dlx():
    channel = FakeChannel()
    broker.declare_topology(channel)
    main = [item for item in channel.queues if item[0] in config.QUEUES]
    assert all(item[2] == {"x-dead-letter-exchange": config.DLX} for item in main)


def test_topic_bindings_match_configuration():
    channel = FakeChannel()
    broker.declare_topology(channel)
    actual = {(queue, key) for queue, exchange, key in channel.bindings
              if exchange == config.EXCHANGE}
    expected = {(queue, key) for queue, keys in config.QUEUES.items() for key in keys}
    assert actual == expected


def test_message_properties_are_persistent_and_traceable():
    props = broker.message_properties(attempt=2, original_rk="order.created",
                                      order_id="ORD-123")
    assert props.delivery_mode == 2
    assert props.message_id == "ORD-123"
    assert props.headers == {"x-attempt": 2,
                             "x-original-routing-key": "order.created"}
