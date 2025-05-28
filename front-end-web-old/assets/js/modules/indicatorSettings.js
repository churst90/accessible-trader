// assets/js/modules/indicatorSettings.js
export default class IndicatorSettings {
    constructor(indicator, onSave, onCancel) {
        this.indicator = indicator; // { id, type, params, yAxis }
        this.onSave = onSave; // Callback to save updated settings
        this.onCancel = onCancel; // Callback to close dialog
        this.modal = document.getElementById('indicator-settings-modal');
        this.paramsEl = document.getElementById('indicator-settings-params');
        this.visualEl = document.getElementById('indicator-settings-visual');
        this.sonifyEl = document.getElementById('indicator-settings-sonify');
        this.saveBtn = document.getElementById('indicator-settings-save');
        this.cancelBtn = document.getElementById('indicator-settings-cancel');

        this._init();
    }

    _init() {
        // Populate the form with current settings
        this._populateParams();
        this._populateVisualSettings();
        this._populateSonificationSettings();

        // Show the dialog
        this.modal.hidden = false;
        this.paramsEl.focus();

        // Bind buttons
        this.saveBtn.onclick = () => this._save();
        this.cancelBtn.onclick = () => this._cancel();

        // Trap focus in dialog
        this._trapFocus();
    }

    _populateParams() {
        this.paramsEl.innerHTML = '';
        Object.entries(this.indicator.params || {}).forEach(([name, value]) => {
            const row = document.createElement('div');
            row.className = 'param-row';
            row.innerHTML = `
                <label for="edit-${name}">
                    ${name.charAt(0).toUpperCase() + name.slice(1)}:
                    <input id="edit-${name}" type="number" value="${value || ''}" />
                </label>`;
            this.paramsEl.append(row);
        });
    }

    _populateVisualSettings() {
        this.visualEl.innerHTML = `
            <div class="param-row">
                <label for="edit-color">Color:
                    <input id="edit-color" type="color" value="#0000FF" />
                </label>
            </div>
            <div class="param-row">
                <label for="edit-line-width">Line Width:
                    <input id="edit-line-width" type="number" value="1" min="1" step="1" />
                </label>
            </div>
        `;
    }

    _populateSonificationSettings() {
        this.sonifyEl.innerHTML = `
            <div class="param-row">
                <label for="edit-sonify-instrument">Instrument:
                    <select id="edit-sonify-instrument">
                        <option value="sine">Sine</option>
                        <option value="triangle">Triangle</option>
                        <option value="square">Square</option>
                        <option value="sawtooth">Sawtooth</option>
                    </select>
                </label>
            </div>
            <div class="param-row">
                <label for="edit-sonify-volume">Volume (0-1):
                    <input id="edit-sonify-volume" type="number" value="0.7" min="0" max="1" step="0.1" />
                </label>
            </div>
        `;
    }

    _save() {
        // Collect updated settings
        const updatedParams = {};
        Object.keys(this.indicator.params || {}).forEach(name => {
            const el = document.getElementById(`edit-${name}`);
            if (el && el.value !== '') updatedParams[name] = Number(el.value);
        });

        const visualSettings = {
            color: document.getElementById('edit-color').value,
            lineWidth: Number(document.getElementById('edit-line-width').value)
        };

        const sonifySettings = {
            instrument: document.getElementById('edit-sonify-instrument').value,
            volume: Number(document.getElementById('edit-sonify-volume').value)
        };

        // Pass updated settings to the callback
        this.onSave({
            params: updatedParams,
            visual: visualSettings,
            sonify: sonifySettings
        });

        // Close dialog
        this.modal.hidden = true;
    }

    _cancel() {
        this.onCancel();
        this.modal.hidden = true;
    }

    _trapFocus() {
        const focusable = this.modal.querySelectorAll('button, input, select, [tabindex="0"]');
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        this.modal.addEventListener('keydown', e => {
            if (e.key === 'Tab') {
                if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            } else if (e.key === 'Escape') {
                this._cancel();
            }
        });
    }
}