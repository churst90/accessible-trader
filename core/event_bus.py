import asyncio
import logging
from collections import defaultdict

class EventBus:
    """A simple event bus for managing subscriptions and publishing events."""

    def __init__(self):
        self._subscribers = defaultdict(list)
        self._queue = asyncio.Queue()  # Create an asyncio Queue for event processing
        self._task = None  # Task will be created when the event loop is running

    def start(self, loop):
        print("EventBus: Starting the event bus...")
        """Start the event processing task when the event loop is running."""
        if not self._task:
            # Create the task directly as the loop should already be running
            self._task = loop.create_task(self._process_queue())
        else:
            print("EventBus: Task is already running.")

    def subscribe(self, event_name, callback):
        print(f"EventBus: Subscription added - Event: {event_name}, Callback: {callback}")
        """Subscribe to an event by providing the event name and a callback function."""
        if not callable(callback):
            raise ValueError("The callback must be callable.")
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name, callback):
        print(f"EventBus: Subscription removed - Event: {event_name}, Callback: {callback}")
        """Unsubscribe a callback from an event."""
        if event_name in self._subscribers:
            self._subscribers[event_name].remove(callback)
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]

    async def publish(self, event_name, *args, **kwargs):
        print(f"EventBus: Publishing event - Event: {event_name}, Args: {args}, Kwargs: {kwargs}")
        """Publish an event asynchronously by adding it to the queue."""
        await self._queue.put((event_name, args, kwargs))  # Add event to the queue

    async def _process_queue(self):
        print("EventBus: Starting to process event queue...")
        """Process events from the queue asynchronously."""
        while True:
            try:
                print("EventBus: Waiting for the next event...")
                event_name, args, kwargs = await self._queue.get()
                print(f"EventBus: Event received - Event: {event_name}")
                await self._dispatch(event_name, *args, **kwargs)
                self._queue.task_done()
            except asyncio.CancelledError:
                print("EventBus: Task was cancelled.")
                break

    async def _dispatch(self, event_name, *args, **kwargs):
        print(f"EventBus: Dispatching event - Event: {event_name}, Args: {args}, Kwargs: {kwargs}")
        """Dispatch events to the subscribed callbacks."""
        callbacks = self._subscribers.get(event_name, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    print(f"EventBus: Awaiting coroutine callback for event: {event_name}")
                    await callback(*args, **kwargs)
                else:
                    print(f"EventBus: Calling regular function callback for event: {event_name}")
                    callback(*args, **kwargs)
            except Exception as e:
                logging.error(f"EventBus: Error in callback for event '{event_name}': {e}")

    async def async_publish(self, event_name, *args, **kwargs):
        print(f"EventBus: Asynchronously publishing event - Event: {event_name}")
        """Helper function to publish events asynchronously."""
        await self.publish(event_name, *args, **kwargs)

    def cleanup(self):
        print("EventBus: Cleaning up - Canceling the event processing task and clearing subscriptions.")
        """Clean up all event subscriptions and cancel the queue processing task."""
        self._subscribers.clear()
        if self._task:
            print("EventBus: Canceling the task.")
            self._task.cancel()
            self._task = None
