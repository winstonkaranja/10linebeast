#!/usr/bin/env python3
"""
FastAPI server for background document processing
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import json
import logging

from legal_processor import StatelessLegalProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Legal Document Processor API",
    description="High-performance legal document processing with background jobs",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize processor
processor = StatelessLegalProcessor()

# Pydantic models
class DocumentRequest(BaseModel):
    documents: List[Dict[str, Any]]
    features: Dict[str, bool]
    force_background: Optional[bool] = False

class JobStatusRequest(BaseModel):
    job_id: str

class JobResultRequest(BaseModel):
    job_id: str

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Legal Document Processor",
        "version": "2.0.0",
        "background_jobs": "enabled",
        "redis_connected": processor.redis_client is not None
    }

@app.post("/process")
async def process_documents(request: DocumentRequest):
    """
    Process documents - automatically routes to background processing for large documents
    """
    try:
        event = {
            "documents": request.documents,
            "features": request.features,
            "force_background": request.force_background
        }
        
        result = processor.lambda_handler(event, None)
        
        # Convert Lambda response to FastAPI response
        if result['statusCode'] == 200:
            return json.loads(result['body'])
        elif result['statusCode'] == 202:  # Background job submitted
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Processing failed')
            )
            
    except Exception as e:
        logger.error(f"Processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/submit")
async def submit_background_job(request: DocumentRequest):
    """
    Explicitly submit a job for background processing
    """
    try:
        event = {
            "action": "submit_job",
            "documents": request.documents,
            "features": request.features
        }
        
        result = processor.lambda_handler(event, None)
        
        if result['statusCode'] == 202:
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Job submission failed')
            )
            
    except Exception as e:
        logger.error(f"Job submission error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/status")
async def check_job_status(request: JobStatusRequest):
    """
    Check the status of a background job
    """
    try:
        event = {
            "action": "check_job",
            "job_id": request.job_id
        }
        
        result = processor.lambda_handler(event, None)
        
        if result['statusCode'] == 200:
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Status check failed')
            )
            
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """
    Get job status via GET request (easier for frontend polling)
    """
    try:
        event = {
            "action": "check_job",
            "job_id": job_id
        }
        
        result = processor.lambda_handler(event, None)
        
        if result['statusCode'] == 200:
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Status check failed')
            )
            
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/result")
async def get_job_result(request: JobResultRequest):
    """
    Get the result of a completed background job
    """
    try:
        event = {
            "action": "get_result",
            "job_id": request.job_id
        }
        
        result = processor.lambda_handler(event, None)
        
        if result['statusCode'] == 200:
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Result retrieval failed')
            )
            
    except Exception as e:
        logger.error(f"Result retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}/result")
async def download_job_result(job_id: str):
    """
    Download job result via GET request
    """
    try:
        event = {
            "action": "get_result",
            "job_id": job_id
        }
        
        result = processor.lambda_handler(event, None)
        
        if result['statusCode'] == 200:
            return json.loads(result['body'])
        else:
            error_body = json.loads(result['body'])
            raise HTTPException(
                status_code=result['statusCode'],
                detail=error_body.get('error', 'Result retrieval failed')
            )
            
    except Exception as e:
        logger.error(f"Result retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)