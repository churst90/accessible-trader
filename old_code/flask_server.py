from flask_cors import CORS
from flask import Flask, request, jsonify
import asyncio
from crypto_data_fetcher import CryptoDataFetcher  # Import the updated fetcher script
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

def parse_date_to_milliseconds(date_str):
    """Converts a date string to milliseconds since epoch."""
    if date_str is None:
        return None
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return int(time.mktime(dt.timetuple()) * 1000)
    except ValueError:
        return None

@app.route('/get_exchanges', methods=['GET'])
def get_exchanges():
    try:
        exchanges = CryptoDataFetcher.get_exchanges()
        return jsonify({'success': True, 'exchanges': exchanges})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_symbols', methods=['GET'])
def get_symbols():
    exchange_id = request.args.get('exchange')
    if not exchange_id:
        return jsonify({'success': False, 'error': 'Missing exchange parameter'}), 400

    try:
        data_fetcher = CryptoDataFetcher(exchange_id)
        symbols = data_fetcher.get_symbols()
        return jsonify({'success': True, 'symbols': symbols})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/fetch_aggregated_ohlcv', methods=['GET'])
def fetch_aggregated_ohlcv():
    exchange_id = request.args.get('exchange')
    symbol = request.args.get('symbol')
    target_timeframe = request.args.get('target_timeframe', '1h')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not exchange_id or not symbol:
        return jsonify({'success': False, 'error': 'Missing required parameters'}), 400

    since = parse_date_to_milliseconds(start_date_str)
    until = parse_date_to_milliseconds(end_date_str)

    if since is None or until is None:
        return jsonify({'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    try:
        data_fetcher = CryptoDataFetcher(exchange_id)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ohlcv_data = loop.run_until_complete(data_fetcher.fetch_ohlcv_in_batches(symbol, target_timeframe, since=since, until=until))
        
        # Convert the DataFrame to a list of dictionaries for JSON serialization
        formatted_data = ohlcv_data.to_dict(orient='records')
        
        return jsonify({'success': True, 'data': formatted_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', ssl_context=('/etc/letsencrypt/live/codyhurst.com/fullchain.pem', '/etc/letsencrypt/live/codyhurst.com/privkey.pem'), port=5000)
