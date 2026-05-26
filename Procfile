# Render / Railway / Heroku: PORT is injected. Locally: PORT=8000 uvicorn ...
# --proxy-headers: trust X-Forwarded-Proto/For from Render's load balancer so that
# request.url.scheme == "https" (fixes password-reset links and other base_url uses).
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
