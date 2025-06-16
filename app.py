#!/usr/bin/env python3
"""
FastAPI wrapper for Railway deployment
Simplified legal document processor - direct processing only
Handles 1000+ concurrent users with async processing
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import asyncio
import uvicorn
import os
from legal_processor import StatelessLegalProcessor

# Initialize FastAPI app
app = FastAPI(
    title="Legal Document Processor API",
    description="High-performance PDF processing with Redis caching - Direct processing",
    version="2.0.0"
)

# CORS middleware for web apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize processor
processor = StatelessLegalProcessor()

# Pydantic models for request validation
class Document(BaseModel):
    filename: str
    content: str  # base64 encoded PDF
    order: int = 1

class Features(BaseModel):
    merge_pdfs: bool = False
    repaginate: bool = False
    tenth_lining: bool = False

class ProcessRequest(BaseModel):
    documents: List[Document]
    features: Features

# Convert Pydantic models to processor format
def convert_request_to_event(documents: List[Document], features: Features) -> Dict[str, Any]:
    return {
        "documents": [doc.dict() for doc in documents],
        "features": features.dict()
    }

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Legal Document Processor",
        "version": "2.0.0", 
        "description": "Direct PDF processing - merge, repaginate, tenth_lining",
        "features": ["merge_pdfs", "repaginate", "tenth_lining"],
        "max_concurrent": "1000+ users",
        "endpoints": {
            "process": "/api/process",
            "health": "/health"
        }
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    redis_status = "connected" if processor.redis_client else "disconnected"
    return {
        "status": "healthy",
        "redis": redis_status,
        "processor": "ready",
        "version": "2.0.0"
    }

@app.post("/api/process")
async def process_documents(request: ProcessRequest):
    """Process documents directly - merge, repaginate, tenth_lining"""
    try:
        event = convert_request_to_event(request.documents, request.features)
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, processor.lambda_handler, event, None)
        
        if result['statusCode'] == 200:
            return result['body']
        else:
            raise HTTPException(status_code=result['statusCode'], detail=result['body'])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

# Legacy endpoint for backward compatibility
@app.post("/process")
async def legacy_process(request: Dict[str, Any]):
    """Legacy endpoint - direct processing"""
    try:
        # Run in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, processor.lambda_handler, request, None)
        
        if result['statusCode'] == 200:
            return result['body']
        else:
            raise HTTPException(status_code=result['statusCode'], detail=result['body'])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

if __name__ == "__main__":
    # For Railway deployment
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        workers=4,  # Handle concurrent requests
        loop="asyncio",
        access_log=True
    )