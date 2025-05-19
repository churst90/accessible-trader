// assets/js/modules/sonificationModal.js

export function openSonificationModal(onConfirm) {
  const dialog = document.getElementById('sonification-dialog');
  const form   = document.getElementById('sonifyForm');
  const cancel = document.getElementById('sonifyCancel');

  function cleanup() {
    form.removeEventListener('submit', onSubmit);
    cancel.removeEventListener('click', onCancel);
    dialog.hidden = true;
  }

  function onSubmit(e) {
    e.preventDefault();
    const duration   = Number(document.getElementById('sonification-duration').value);
    const instrument = document.getElementById('sonification-instrument').value;
    const grouping   = document.getElementById('sonification-grouping').checked;
    cleanup();
    onConfirm({ duration, instrument, grouping });
  }

  function onCancel() {
    cleanup();
  }

  form.addEventListener('submit', onSubmit);
  cancel.addEventListener('click', onCancel);
  dialog.hidden = false;
}
