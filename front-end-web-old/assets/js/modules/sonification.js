/**
 * Sonification controller (Highcharts accessibility module)
 */
let defaultSettings = {
  series: [
    { id: 'ohlc', instrument: 'sine' },
    { id: 'vol',  instrument: 'triangle' }
  ],
  duration: 8000
};

export function getUserSonificationSettings() {
  return defaultSettings;
}

export function playSonification(chart) {
  if (typeof chart.sonify !== 'function') {
    console.error('Sonification module missing');
    return;
  }
  return chart.sonify(defaultSettings);
}

window.playSonification = playSonification;
