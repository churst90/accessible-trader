import tkinter as tk
from tkinter import ttk
import asyncio

class Dialog(tk.Frame):
    def __init__(self, parent, title, fields_config, event_bus, accessibility_manager, is_toplevel=False, bg_color="black"):
        if is_toplevel:
            super().__init__(tk.Toplevel(parent))
            self.master.title(title)
            self.master.geometry("400x300")
            self.master.configure(bg=bg_color)
            self.master.grab_set()  # Make the dialog modal
        else:
            super().__init__(parent)
            self.configure(bg=bg_color)

        self.event_bus = event_bus
        self.accessibility_manager = accessibility_manager
        self.fields = {}
        self.label_widget_mapping = {}

        self.create_fields(fields_config)
        if is_toplevel:
            self.create_buttons()

        self.grid(sticky=tk.NSEW)
        self.bind_focus_events()

    def create_fields(self, fields_config):
        """Create fields based on the configuration provided."""
        for idx, field in enumerate(fields_config):
            label_text = field['label']
            label = ttk.Label(self, text=label_text, background=self["bg"], foreground="white")
            label.grid(row=idx, column=0, padx=10, pady=5, sticky="w")

            if field['type'] == 'entry':
                entry = ttk.Entry(self)
                entry.insert(0, field.get('default', ''))
                entry.grid(row=idx, column=1, padx=10, pady=5, sticky="ew")
                self.fields[field['name']] = entry
                self.label_widget_mapping[entry] = label_text

            elif field['type'] == 'dropdown':
                # Use 'normal' state to allow typing in the dropdown
                dropdown = ttk.Combobox(self, values=field.get('values', []), state="normal")
                dropdown.grid(row=idx, column=1, padx=10, pady=5, sticky="ew")
                self.fields[field['name']] = dropdown
                self.label_widget_mapping[dropdown] = label_text

                # Bind the combobox to handle navigation and announce the selection
                self.bind_combobox_navigation(dropdown)

        self.grid_columnconfigure(1, weight=1)

    def bind_combobox_navigation(self, combobox):
        """Bind the combobox navigation to announce selection changes."""
        combobox.bind("<Up>", self.on_combobox_navigation)
        combobox.bind("<Down>", self.on_combobox_navigation)
        combobox.bind("<<ComboboxSelected>>", self.on_combobox_selection)
        combobox.bind("<KeyRelease>", self.on_combobox_navigation)  # Allow typing to narrow down the selection

    def on_combobox_navigation(self, event):
        combobox = event.widget
        current_selection = combobox.get()
        self.accessibility_manager.speak(f"Selected: {current_selection}")

    def on_combobox_selection(self, event):
        combobox = event.widget
        current_selection = combobox.get()
        self.accessibility_manager.speak(f"Combobox: {self.label_widget_mapping[combobox]} selection changed to {current_selection}")

    def create_button(self, label, command, row, column, columnspan=1):
        """Create a button within the dialog."""
        button = ttk.Button(self, text=label, command=command)
        button.grid(row=row, column=column, padx=5, pady=10, sticky="ew", columnspan=columnspan)
        
        # Bind the button for focus announcement
        self.accessibility_manager.bind_focus_change(button)
        
        return button

    def create_buttons(self):
        """Create default Save and Cancel buttons for the dialog."""
        button_frame = tk.Frame(self.master, bg=self["bg"])
        button_frame.grid(row=len(self.fields), column=0, columnspan=2, pady=10)

        save_button = ttk.Button(button_frame, text="Save", command=self.save)
        save_button.grid(row=0, column=1, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.master.destroy)
        cancel_button.grid(row=0, column=0, padx=5)

        self.accessibility_manager.bind_focus_change(save_button)
        self.accessibility_manager.bind_focus_change(cancel_button)

    def bind_focus_events(self):
        """Bind focus events for accessibility."""
        for widget in self.fields.values():
            self.accessibility_manager.bind_focus_change(widget)

    def save(self):
        """Handle the save action, collecting all field values and publishing an event."""
        values = {name: field.get() for name, field in self.fields.items()}
        self.master.destroy()
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish("dialog_saved", values), asyncio.get_event_loop()
        )
