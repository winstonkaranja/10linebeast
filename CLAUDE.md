# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a high-performance legal document processor that processes PDFs with features like merging, pagination, and 10th line numbering. The system uses Redis caching for ultra-fast repeated operations and focuses purely on document processing. Payment verification is handled by the frontend.

## Core Architecture

The main processor (`StatelessLegalProcessor`) implements a simplified workflow:

1. Accept documents and features
2. Process documents immediately with Redis caching (0.1-5 seconds)
3. Return processed PDF directly

**Key Components:**
- `StatelessLegalProcessor`: Main document processing engine with Redis caching
- Redis caching system for ultra-fast repeated operations
- Multi-threaded PDF processing with ThreadPoolExecutor

## Common Development Commands

**Setup environment:**
```bash
pip install -r requirements.txt
```

**Run local tests:**
```bash
python test_local.py
```

**Run main processor locally:**
```bash
python legal_processor.py
```

**Test specific functionality:**
```bash
# Test Redis connection and caching
python -c "from test_local import test_redis_connection; test_redis_connection()"
```

## Environment Configuration

Required environment variables (create `.env` file):
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password
```

## Key Features & Processing Pipeline

**Document Features:**
- `merge_pdfs`: Combines multiple PDFs into one
- `repaginate`: Adds page numbers to documents  
- `tenth_lining`: Adds line numbers every 10th line using PyMuPDF

**Processing Flow:**
1. Documents decoded in parallel using ThreadPoolExecutor
2. Features applied in optimal order (merge → repaginate → tenth_lining)
3. Results cached in Redis with 1-hour TTL
4. Base64 encoding for API responses

## Performance Optimizations

- **Redis Caching**: Sub-100ms responses for cached documents
- **Parallel Processing**: ThreadPoolExecutor for I/O operations
- **Deterministic Cache Keys**: Hash-based keys for documents + features

## Testing Strategy

The `test_local.py` file provides comprehensive testing:
- Redis connection and performance benchmarks
- Document processing pipeline validation
- Cache performance testing

**Test execution order:**
1. Dependencies check
2. Redis connection test
3. Document processing tests
4. Performance benchmarking

## Serverless Deployment

The processor supports multiple serverless platforms:
- AWS Lambda: `lambda_handler(event, context)`
- Azure Functions: `azure_function_handler(req)`
- Google Cloud: `gcp_cloud_function_handler(request)`

## Cache Management

Cache keys are generated from document content + features hash. Cache TTL is 1 hour. The system gracefully degrades when Redis is unavailable.