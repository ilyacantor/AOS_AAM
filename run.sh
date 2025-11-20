#!/bin/bash
# Salesforce OAuth Connector - Startup Script

echo "🚀 Starting Salesforce OAuth Connector..."
echo ""
echo "📍 Server will be available at:"
echo "   http://localhost:5000"
echo "   https://$(echo $REPL_SLUG).$(echo $REPL_OWNER).repl.co (if on Replit)"
echo ""
echo "📚 API Documentation:"
echo "   http://localhost:5000/docs (Swagger UI)"
echo "   http://localhost:5000/redoc (ReDoc)"
echo ""
echo "✅ Starting server..."
echo ""

# Run uvicorn with auto-reload
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
