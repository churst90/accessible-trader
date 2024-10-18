def bind_focus_events(accessibility_manager, widget):
    """
    Bind focus-related events to the widget for accessibility purposes.
    
    :param accessibility_manager: The AccessibilityManager instance that handles focus announcements.
    :param widget: The widget to bind focus events to.
    """
    widget.bind("<FocusIn>", accessibility_manager.on_focus_in)


def bind_key_navigation_events(widget, key_action_handler, navigation_map):
    """
    Bind navigation keys (such as Left, Right, Up, Down) to the widget.
    
    :param widget: The widget to bind keys to.
    :param key_action_handler: The function that will handle the key actions (e.g., chart navigation).
    :param navigation_map: A dictionary where the key is the event (e.g., '<Left>') and the value is the action name (e.g., 'previous_datapoint').
    """
    for key_event, action_name in navigation_map.items():
        widget.bind(key_event, lambda event, action=action_name: key_action_handler(action))


def bind_combobox_navigation_events(accessibility_manager, combobox):
    """
    Bind navigation events specific to a Combobox widget for announcing selection changes.
    
    :param accessibility_manager: The AccessibilityManager instance that handles navigation announcements.
    :param combobox: The Combobox widget to bind events to.
    """
    combobox.bind("<Up>", accessibility_manager.on_combobox_navigation)
    combobox.bind("<Down>", accessibility_manager.on_combobox_navigation)
    combobox.bind("<<ComboboxSelected>>", accessibility_manager.on_combobox_selection)


def subscribe_to_events(event_bus, subscriptions):
    """
    Helper function to subscribe to events in the EventBus.
    
    :param event_bus: The EventBus instance.
    :param subscriptions: A dictionary where keys are event names and values are callback methods.
    """
    for event_name, callback in subscriptions.items():
        event_bus.subscribe(event_name, callback)
