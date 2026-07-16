"""Service layer.

Business logic lives here, not in route handlers. Routes stay thin:
parse request -> call a service -> render/serialize the result. This keeps
logic testable without a request context and reusable from the web routes,
CLI commands, or future API clients.
"""
