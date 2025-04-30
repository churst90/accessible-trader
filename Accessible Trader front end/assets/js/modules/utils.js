// assets/js/modules/utils.js

/** Utility functions for your modules. */

/**
 * Debounce a function, delaying its execution until after `delay` ms
 * have elapsed since the last call.
 */
export function debounce(fn, delay = 200) {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}
