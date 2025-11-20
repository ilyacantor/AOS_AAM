#!/bin/bash
# Quick Start Script for Salesforce OAuth Connector

echo "========================================="
echo " Salesforce OAuth Connector"
echo " Python/FastAPI POC"
echo "========================================="
echo ""

# Check if uvicorn is available
if ! command -v uvicorn &> /dev/null; then
    echo "❌ Error: uvicorn not found"
    echo "Please install Python dependencies first:"
    echo "  pip install fastapi uvicorn httpx python-dotenv pydantic"
    exit 1
fi

# Set PYTHONPATH to ensure app module is found
export PYTHONPATH=/home/runner/workspace:$PYTHONPATH

# Display information
echo "🚀 Starting Salesforce OAuth Connector..."
echo ""
echo "📍 Server will be available at:"
echo "   • Local: http://localhost:5000"
echo "   • API Docs (Swagger): http://localhost:5000/docs"
echo "   • ReDoc: http://localhost:5000/redoc"
echo ""
echo "⚙️  Configuration needed:"
echo "   • Set SALESFORCE_CALLBACK_URL in Replit Secrets"
echo "   • Format: https://<your-replit-url>/oauth/callback/salesforce"
echo ""
echo "✅ Starting uvicorn server..."
echo "========================================="
echo ""

# Run uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
