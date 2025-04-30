hypercorn "app:create_app()" \
  --bind 0.0.0.0:5000 \
  --certfile /etc/letsencrypt/live/accessibletrader.com/fullchain.pem \
  --keyfile /etc/letsencrypt/live/accessibletrader.com/privkey.pem