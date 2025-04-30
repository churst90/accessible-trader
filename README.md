# AccessibleTrader

AccessibleTrader is a powerful backend for a fully accessible technical analysis and charting platform. Designed for both web and desktop applications, it empowers visually impaired traders and analysts with real-time market data, advanced charting tools, and seamless technical analysis capabilities. Leveraging cutting-edge technologies such as Quart, TimescaleDB, Redis, and Highcharts, AccessibleTrader ensures an inclusive, efficient, and robust trading experience.

## Features

### Core Backend
- High Performance API: Built with Quart for asynchronous, scalable, and fast API services.
- Advanced Data Management:
  - TimescaleDB for high-performance time-series data storage and analysis.
  - Continuous aggregates for efficient query performance across multiple timeframes.
- Real-Time Data:
  - Integration with ccxt for fetching live market data and historical OHLCV (Open, High, Low, Close, Volume) data.
  - Redis for caching frequently accessed data to reduce latency.

### Accessibility-Focused Design
- Highcharts Integration: Uses Highcharts' robust accessibility features to provide visually impaired users with full access to data visualizations.
- Keyboard Navigation and Speech Feedback: The upcoming frontend and desktop client will include features such as speech output and keyboard navigation for seamless interaction.

### WebSocket Support
- Live Market Data: WebSocket endpoints for real-time updates on market prices and trades.

### Secure User Management
- Role-based access control (e.g., `user`, `admin`, `premium`) for tailored feature access.
- Secure authentication using JWT and password hashing (bcrypt).

### Modular Architecture
- Easily extendable plugins for new markets and exchanges.
- Flexible caching and database layers for future scalability.

## Technologies Used

### Backend Framework
- Quart: Async web framework providing speed and flexibility.
  
### Data Storage
- TimescaleDB: PostgreSQL-based database optimized for time-series data.
- Redis: High-performance in-memory caching layer.

### Data Visualization
- Highcharts: A rich, accessible charting library for both web and desktop visualizations.

### Authentication
- JWT: Secure and efficient user authentication.
- Bcrypt: Password hashing for secure storage.

### Additional Tools
- ccxt: Asynchronous support for multiple cryptocurrency exchanges.
- Logging: Comprehensive logging for debugging and monitoring.

## Installation and Setup

### Prerequisites
- Python 3.10+
- PostgreSQL with TimescaleDB Extension
- Redis
- Node.js (optional for frontend development)

### Setup Instructions

1. Clone the Repository
   git clone https://github.com/churst90/accessible-trader.git
   cd accessible-trader
   ```

2. Set Up Virtual Environment
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Database Setup
   - Create a PostgreSQL database and enable TimescaleDB extension.
   - Import the SQL script to initialize tables:
     psql -d accessibletrader_db -f accessibletrader_db.sql
     ```

4. Environment Variables
   Create a `.env` file based on the provided `.env.example`:
   ```env
   SECRET_KEY=your-secret-key
   DB_CONNECTION_STRING=postgresql://username:password@localhost/accessibletrader_db
   REDIS_URL=redis://localhost
   TRUSTED_ORIGINS=http://localhost:3000,http://yourdomain.com
   ENV=development
   ```

5. Run the Application
   ```bash
   hypercorn "app:create_app()" --bind 0.0.0.0:5000
   ```

## API Endpoints

### Authentication
- `POST /auth/login`: Login and receive a JWT token.
- `POST /auth/refresh`: Refresh an expired JWT token.

### Market Data
- `GET /market/get_exchanges`: Fetch available exchanges for a market.
- `GET /market/get_symbols`: Fetch symbols for a given exchange.
- `GET /market/fetch_ohlcv`: Retrieve OHLCV data.

### WebSocket
- `ws://yourdomain.com/ws/subscribe`: Subscribe to live market updates.

### Health Check
- `GET /health`: Verify service status for database and Redis.

## Frontend and Desktop Clients

AccessibleTrader will support both a web and desktop client to provide an integrated experience. Both interfaces will:
- Use Highcharts for accessible data visualizations.
- Support screen readers and keyboard navigation.
- Integrate with the backend for live and historical data analysis.

Planned frameworks include:
- Javascript for the web client.
- Tkinter for the desktop client.

## Contribution

We welcome contributions to improve AccessibleTrader! To contribute:
1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Submit a pull request with a detailed description.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Roadmap

### Backend
- Enhanced API support for trading features (e.g., placing orders).
- Custom indicators and alert mechanisms.

### Frontend/Desktop
- Fully accessible trading interface.
- Advanced charting tools with interactive features.

### Accessibility
- Expanded support for haptic feedback and audio chart descriptions.

## Contact

For questions or feedback, contact the project maintainer at [your-email@example.com].  
