web: gunicorn viewer_server:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300 --graceful-timeout 30 --keep-alive 65 --access-logfile - --error-logfile -
