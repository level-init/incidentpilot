# gateway

Simulated API gateway. Orchestrates checkout across auth → inventory → payment →
checkout → notification.

- Health: `GET /healthz`
- Checkout: `POST /v1/checkout`
