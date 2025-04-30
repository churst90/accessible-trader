// assets/js/modules/speechManager.js

/**
 * Simple wrapper around Web Speech API so announcements
 * are spoken clearly and in full.
 */

const synth = window.speechSynthesis;

export function speak(text) {
  if (!synth) return;
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'en-US';
  // cancel any in-progress speak to avoid chopping
  synth.cancel();
  synth.speak(utter);
}
