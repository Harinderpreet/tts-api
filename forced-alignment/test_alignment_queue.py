"""Admission order, overload, timeout and failure cleanup without loading a model."""

from concurrent.futures import ThreadPoolExecutor
import time
import unittest

from alignment_queue import AlignmentQueue, QueueTimeoutError, ServiceBusyError


class QueueTests(unittest.TestCase):
    def wait_for_queue(self, queue, count):
        deadline = time.monotonic() + 2
        while queue.snapshot()["queued_requests"] != count:
            if time.monotonic() >= deadline:
                self.fail("Caller did not join the queue")
            time.sleep(.001)

    def test_fifo_and_queue_capacity(self):
        queue = AlignmentQueue(1, 2, 5)
        order = []

        def request(number):
            with queue.slot():
                self.assertEqual(queue.snapshot()["active_requests"], 1)
                order.append(number)

        with ThreadPoolExecutor(max_workers=2) as pool:
            with queue.slot():
                first = pool.submit(request, 1)
                self.wait_for_queue(queue, 1)
                second = pool.submit(request, 2)
                self.wait_for_queue(queue, 2)
                with self.assertRaises(ServiceBusyError):
                    with queue.slot():
                        self.fail("A full queue admitted another request")
            first.result(timeout=2)
            second.result(timeout=2)
        self.assertEqual(order, [1, 2])
        self.assertEqual(queue.snapshot(), {"active_requests": 0, "queued_requests": 0})

    def test_timeout_removes_waiter_and_failure_releases_worker(self):
        queue = AlignmentQueue(1, 1, .02)
        with queue.slot():
            with self.assertRaises(QueueTimeoutError):
                with queue.slot():
                    self.fail("Busy worker admitted another request")
            self.assertEqual(queue.snapshot(), {"active_requests": 1, "queued_requests": 0})
        with self.assertRaisesRegex(RuntimeError, "failed"):
            with queue.slot():
                raise RuntimeError("failed")
        with queue.slot():
            self.assertEqual(queue.snapshot()["active_requests"], 1)

    def test_two_workers_and_no_waiting(self):
        queue = AlignmentQueue(2, 0, 5)
        with queue.slot(), queue.slot():
            self.assertEqual(queue.snapshot()["active_requests"], 2)
            with self.assertRaises(ServiceBusyError):
                with queue.slot():
                    self.fail("Admitted a third worker")

    def test_invalid_configuration(self):
        for args in ((0, 1, 5), (1, -1, 5), (1, 1, 0), (1, 1, float("inf"))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                AlignmentQueue(*args)


if __name__ == "__main__":
    unittest.main()
