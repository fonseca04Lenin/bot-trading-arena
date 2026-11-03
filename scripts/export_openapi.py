import json

from arena_api.main import app

print(json.dumps(app.openapi(), indent=1))
