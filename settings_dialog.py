import tkinter as tk
from tkinter import ttk
from accessible_dialog import AccessibleDialog  # Import AccessibleDialog

class SettingsDialog(AccessibleDialog):
    def __init__(self, parent, indicator, speech_manager):
        super().__init__(parent, speech_manager)
        self.indicator = indicator
        self.title(f"{indicator.__class__.__name__} Settings Dialog")
        self.geometry("400x400")

        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True)

        self.create_general_tab(notebook)
        self.create_appearance_tab(notebook)
        self.create_speech_tab(notebook)

        button_frame = tk.Frame(self)
        button_frame.pack(fill='x', pady=10)

        save_button = tk.Button(button_frame, text="Save", command=self.save_settings)
        save_button.pack(side="right", padx=5)
        cancel_button = tk.Button(button_frame, text="Cancel", command=self.destroy)
        cancel_button.pack(side="right", padx=5)

        save_button.bind("<Return>", lambda event: self.save_settings())
        cancel_button.bind("<Return>", lambda event: self.destroy())

    def create_general_tab(self, notebook):
        self.general_frame = ttk.Frame(notebook)
        notebook.add(self.general_frame, text="General")

        for key, value in self.indicator.get_settings().items():
            label = ttk.Label(self.general_frame, text=key)
            label.pack(pady=5)
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                checkbox = ttk.Checkbutton(self.general_frame, variable=var)
                checkbox.pack(pady=5)
                setattr(self, f"{key}_var", var)  # Store reference to variable
            elif isinstance(value, list):
                combobox = ttk.Combobox(self.general_frame, values=value)
                combobox.pack(pady=5)
                setattr(self, f"{key}_var", combobox)  # Store reference to combobox
            elif isinstance(value, (int, float)):
                entry = ttk.Entry(self.general_frame)
                entry.insert(0, str(value))
                entry.pack(pady=5)
                setattr(self, f"{key}_var", entry)  # Store reference to entry
            else:
                entry = ttk.Entry(self.general_frame)
                entry.insert(0, value)
                entry.pack(pady=5)
                setattr(self, f"{key}_var", entry)  # Store reference to entry

    def create_appearance_tab(self, notebook):
        self.appearance_frame = ttk.Frame(notebook)
        notebook.add(self.appearance_frame, text="Appearance")

        for key, value in self.indicator.get_appearance_settings().items():
            label = ttk.Label(self.appearance_frame, text=key)
            label.pack(pady=5)
            entry = ttk.Entry(self.appearance_frame)
            entry.insert(0, value)
            entry.pack(pady=5)
            setattr(self, f"{key}_var", entry)  # Store reference to entry

    def create_speech_tab(self, notebook):
        self.speech_frame = ttk.Frame(notebook)
        notebook.add(self.speech_frame, text="Speech Settings")

        read_column_names_var = tk.BooleanVar(value=self.indicator.get_speech_settings().get('read_column_names', True))
        read_column_names_check = ttk.Checkbutton(self.speech_frame, text="Read Column Names", variable=read_column_names_var)
        read_column_names_check.pack(pady=5)

        read_order_label = ttk.Label(self.speech_frame, text="Read Order (comma-separated)")
        read_order_label.pack(pady=5)
        read_order_entry = ttk.Entry(self.speech_frame)
        read_order_entry.insert(0, ", ".join(self.indicator.get_speech_settings().get('read_order', [])))
        read_order_entry.pack(pady=5)

        self.read_column_names_var = read_column_names_var
        self.read_order_entry = read_order_entry

    def save_settings(self):
        new_general_settings = {}
        new_appearance_settings = {}
        new_speech_settings = {}

        # Gather values from general settings tab
        for key in self.indicator.get_settings().keys():
            widget = getattr(self, f"{key}_var")
            if isinstance(widget, tk.BooleanVar):
                new_general_settings[key] = widget.get()
            elif isinstance(widget, ttk.Combobox):
                new_general_settings[key] = widget.get()
            elif isinstance(widget, ttk.Entry):
                value = widget.get()
                try:
                    if '.' in value:
                        new_general_settings[key] = float(value)
                    else:
                        new_general_settings[key] = int(value)
                except ValueError:
                    self.speech_manager.speak(f"Invalid value for {key}. Please correct it.")
                    return

        # Gather values from appearance settings tab
        for key in self.indicator.get_appearance_settings().keys():
            widget = getattr(self, f"{key}_var")
            new_appearance_settings[key] = widget.get()

        # Gather values from speech settings tab
        new_speech_settings['read_column_names'] = self.read_column_names_var.get()
        new_speech_settings['read_order'] = [x.strip() for x in self.read_order_entry.get().split(',')]

        # Apply the new settings to the indicator
        self.indicator.update_settings(**new_general_settings)
        self.indicator.update_appearance_settings(**new_appearance_settings)
        self.indicator.update_speech_settings(**new_speech_settings)

        # Notify the chart manager to refresh the chart
        parent_chart_manager = self.master.chart_manager  # Access chart manager through parent
        parent_chart_manager.replot_chart()  # Replot the chart with updated settings

        self.destroy()  # Close the dialog
