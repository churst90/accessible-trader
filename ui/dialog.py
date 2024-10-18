import tkinter as tk
from tkinter import ttk
import asyncio
from utils import bind_focus_events, bind_combobox_navigation_events

class Dialog(tk.Frame):
    def __init__(self, parent, title, fields_config, event_bus, accessibility_manager, buttons_config=None, is_toplevel=False, bg_color="black"):
        if is_toplevel:
            super().__init__(tk.Toplevel(parent))  # Create a top-level window if necessary
            self.master.title(title)
            self.master.geometry("400x300")
            self.master.configure(bg=bg_color)
            self.master.grab_set()  # Make the dialog modal
            self.master.focus_force()  # Bring the window to the foreground
        else:
            super().__init__(parent)
            self.configure(bg=bg_color)

        self.event_bus = event_bus
        self.accessibility_manager = accessibility_manager
        self.fields = {}  # Dictionary to hold input fields
        self.buttons = {}  # Dictionary to hold buttons

        # Create the fields and layout
        self.create_fields(fields_config)
        self.grid(sticky=tk.NSEW)

        # Create the buttons
        if buttons_config:
            self.create_buttons(buttons_config)

        # Bind focus events for accessibility using the new utility
        self.bind_focus_events()

    def create_fields(self, fields_config):
        """
        Create input fields (text entry, dropdowns, etc.) based on the provided configuration.

        :param fields_config: List of dictionaries with field configuration.
        """
        for idx, field in enumerate(fields_config):
            label_text = field['label']
            label = ttk.Label(self, text=label_text, background=self["bg"], foreground="white")
            label.grid(row=idx, column=0, padx=10, pady=5, sticky="w")
            self.accessibility_manager.bind_focus_change(label)

            if field['type'] == 'entry':
                # Create a text entry field
                entry = ttk.Entry(self)
                entry.insert(0, field.get('default', ''))
                entry.grid(row=idx, column=1, padx=10, pady=5, sticky="ew")
                self.fields[field['name']] = entry
                self.accessibility_manager.bind_focus_change(entry)  # Bind focus change for Entry widgets

            elif field['type'] == 'dropdown':
                # Create a combobox dropdown field
                dropdown = ttk.Combobox(self, values=field.get('values', []), state="normal")
                dropdown.grid(row=idx, column=1, padx=10, pady=5, sticky="ew")
                self.fields[field['name']] = dropdown
                self.accessibility_manager.bind_combobox_navigation(dropdown)  # Bind focus change and selection events

            elif field['type'] == 'text':
                # Create a text label for read-only display
                text_label = ttk.Label(self, text=field.get('default', ''), background=self["bg"], foreground="white")
                text_label.grid(row=idx, column=1, padx=10, pady=5, sticky="ew")
                self.fields[field['name']] = text_label
                self.accessibility_manager.bind_focus_change(text_label)

        self.grid_columnconfigure(1, weight=1)

    def create_buttons(self, buttons_config):
        """
        Create buttons based on the provided configuration.

        :param buttons_config: List of dictionaries with button configuration.
        """
        for idx, button in enumerate(buttons_config):
            button_text = button['text']
            button_action = button['action']  # Function to call when button is pressed
            btn = ttk.Button(self, text=button_text, command=lambda action=button_action: self.on_button_press(action))
            btn.grid(row=len(self.fields) + idx, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
            self.buttons[button['name']] = btn

            # Bind focus events for accessibility
            self.accessibility_manager.bind_focus_change(btn)

    def on_button_press(self, action):
        """
        Handle the button press action. The action will be an async function or event to handle.
        :param action: The function to execute on button press.
        """
        asyncio.run(action())

    def bind_focus_events(self):
        """Bind focus change events for accessibility for all fields and buttons."""
        for widget in self.fields.values():
            self.accessibility_manager.bind_focus_change(widget)
        for button in self.buttons.values():
            self.accessibility_manager.bind_focus_change(button)

    def set_field_value(self, field_name, value):
        """
        Set the value of a specific field by name.

        :param field_name: The name of the field.
        :param value: The value to set.
        """
        if field_name in self.fields:
            widget = self.fields[field_name]
            if isinstance(widget, ttk.Entry):
                widget.delete(0, tk.END)
                widget.insert(0, value)
            elif isinstance(widget, ttk.Combobox):
                widget.set(value)
            elif isinstance(widget, ttk.Label):
                widget.config(text=value)

    def get_field_value(self, field_name):
        """
        Get the value of a specific field by name.

        :param field_name: The name of the field.
        :return: The value of the field.
        """
        if field_name in self.fields:
            widget = self.fields[field_name]
            if isinstance(widget, ttk.Entry):
                return widget.get()
            elif isinstance(widget, ttk.Combobox):
                return widget.get()
            elif isinstance(widget, ttk.Label):
                return widget.cget("text")
        return None

    def set_focus(self, field_name):
        """
        Set focus on a specific field by name.

        :param field_name: The name of the field.
        """
        if field_name in self.fields:
            self.fields[field_name].focus_set()

    def reset_fields(self):
        """
        Reset all input fields to their default values.
        """
        for field_name, widget in self.fields.items():
            if isinstance(widget, ttk.Entry):
                widget.delete(0, tk.END)
            elif isinstance(widget, ttk.Combobox):
                widget.set('')


# Example usage:
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Dialog Test")

    # Sample configuration for fields
    fields = [
        {'name': 'name', 'label': 'Name', 'type': 'entry', 'default': 'John Doe'},
        {'name': 'age', 'label': 'Age', 'type': 'entry', 'default': '30'},
        {'name': 'gender', 'label': 'Gender', 'type': 'dropdown', 'values': ['Male', 'Female', 'Other']},
        {'name': 'info', 'label': 'Info', 'type': 'text', 'default': 'This is a sample dialog.'}
    ]

    # Sample buttons
    buttons = [
        {'name': 'ok_button', 'text': 'OK', 'action': lambda: print("OK button pressed")},
        {'name': 'cancel_button', 'text': 'Cancel', 'action': lambda: print("Cancel button pressed")}
    ]

    # Create and show the dialog
    dialog = Dialog(root, "Sample Dialog", fields, None, None, buttons_config=buttons, is_toplevel=False)
    dialog.pack(expand=True, fill=tk.BOTH)

    root.mainloop()
