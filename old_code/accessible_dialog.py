import tkinter as tk

class AccessibleDialog(tk.Toplevel):
    """A base dialog class that supports accessibility features."""
    def __init__(self, parent, speech_manager):
        super().__init__(parent)
        self.speech_manager = speech_manager
        self.focused_widget_index = 0

        # Bindings for navigation
        self.bind("<Tab>", self.on_tab_navigation)
        self.bind("<Shift-Tab>", self.on_shift_tab_navigation)
        self.bind("<Up>", self.on_arrow_navigation)
        self.bind("<Down>", self.on_arrow_navigation)
        self.bind("<Return>", self.on_enter_key)

    def on_tab_navigation(self, event):
        """Handle tab key navigation to move forward through widgets."""
        widgets = self.focusable_widgets()
        if widgets:
            self.focused_widget_index = (self.focused_widget_index + 1) % len(widgets)
            widgets[self.focused_widget_index].focus_set()
            self.speak_widget_label(widgets[self.focused_widget_index])
        return "break"  # Prevent default tab behavior

    def on_shift_tab_navigation(self, event):
        """Handle shift-tab key navigation to move backward through widgets."""
        widgets = self.focusable_widgets()
        if widgets:
            self.focused_widget_index = (self.focused_widget_index - 1) % len(widgets)
            widgets[self.focused_widget_index].focus_set()
            self.speak_widget_label(widgets[self.focused_widget_index])
        return "break"  # Prevent default shift-tab behavior

    def on_arrow_navigation(self, event):
        """Handle up and down arrow keys to navigate through widgets."""
        widgets = self.focusable_widgets()
        if widgets:
            if event.keysym == 'Up':
                self.focused_widget_index = (self.focused_widget_index - 1) % len(widgets)
            elif event.keysym == 'Down':
                self.focused_widget_index = (self.focused_widget_index + 1) % len(widgets)
            widgets[self.focused_widget_index].focus_set()
            self.speak_widget_label(widgets[self.focused_widget_index])
        return "break"  # Prevent default arrow key behavior

    def on_enter_key(self, event):
        """Handle the enter key to activate the focused widget."""
        focused_widget = self.focusable_widgets()[self.focused_widget_index]
        if isinstance(focused_widget, tk.Button):
            focused_widget.invoke()
        elif isinstance(focused_widget, tk.Entry):
            focused_widget.icursor(tk.END)
        return "break"  # Prevent default enter key behavior

    def focusable_widgets(self):
        """Return a list of focusable widgets in the dialog."""
        return [widget for widget in self.winfo_children() if widget.winfo_viewable() and widget.cget('state') != 'disabled']

    def speak_widget_label(self, widget):
        """Speak the label or type of the currently focused widget."""
        label = ""
        if isinstance(widget, tk.Entry):
            label = f"Entry field, current value: {widget.get()}"
        elif isinstance(widget, tk.Button):
            label = f"Button, label: {widget.cget('text')}"
        elif isinstance(widget, tk.Checkbutton):
            label = f"Checkbox, selected: {widget.var.get()}"
        elif isinstance(widget, tk.Combobox):
            label = f"Combobox, current selection: {widget.get()}"
        elif isinstance(widget, tk.Label):
            label = f"Label, text: {widget.cget('text')}"
        elif isinstance(widget, tk.Text):
            label = "Text area"
        self.speech_manager.speak(label)
