import json
import io
import base64
from typing import List, Dict, Any, Union, Sequence
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import hashlib

# Redis for ultra-fast caching
import redis

# PDF processing imports
try:
    from PyPDF2 import PdfWriter, PdfReader
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    import fitz  # PyMuPDF for better text extraction and manipulation
except ImportError as e:
    logging.error(f"Missing required dependency: {e}")
    raise

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Type alias for PDF objects
PdfObject = Union[PdfReader, PdfWriter]

class StatelessLegalProcessor:
    """
    Ultra-fast stateless legal document processor with Redis caching
    Accepts documents, processes them (merge, paginate, tenth_line) and returns PDF immediately
    """
    
    def __init__(self):
        self.max_workers = min(32, (os.cpu_count() or 1) + 4)
        
        # Initialize Redis for ultra-fast caching
        try:
            # Check for Redis configuration in order of preference
            redis_url = os.getenv('REDIS_URL')
            redishost = os.getenv('REDISHOST')  # Railway's Redis host variable
            redis_host = os.getenv('REDIS_HOST')  # Manual configuration
            
            if redis_url:
                # REDIS_URL format (preferred)
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=10,
                    retry_on_timeout=True,
                    retry_on_error=[redis.ConnectionError, redis.TimeoutError]
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via REDIS_URL")
            elif redishost:
                # Railway's Redis environment variables
                self.redis_client = redis.Redis(
                    host=redishost,
                    port=int(os.getenv('REDISPORT', 6379)),
                    username=os.getenv('REDISUSER'),
                    password=os.getenv('REDISPASSWORD'),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=10,
                    retry_on_timeout=True,
                    retry_on_error=[redis.ConnectionError, redis.TimeoutError]
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via Railway Redis variables")
            elif redis_host and not self._is_railway_deployment():
                # Manual Redis configuration (local development)
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=int(os.getenv('REDIS_PORT', 6379)),
                    password=os.getenv('REDIS_PASSWORD'),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=10,
                    retry_on_timeout=True,
                    retry_on_error=[redis.ConnectionError, redis.TimeoutError]
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via manual configuration")
            else:
                # No Redis configuration found
                deployment_type = "Railway deployment" if self._is_railway_deployment() else "local environment"
                logger.info(f"No Redis service configured for {deployment_type} - running without cache")
                self.redis_client = None
        except Exception as e:
            logger.warning(f"Redis connection failed: {e} - Running without cache")
            self.redis_client = None
    
    def _is_railway_deployment(self) -> bool:
        """Detect if running in Railway deployment"""
        # Railway sets several environment variables we can check
        railway_indicators = [
            'RAILWAY_ENVIRONMENT',
            'RAILWAY_PROJECT_ID',
            'RAILWAY_SERVICE_ID',
            'RAILWAY_DEPLOYMENT_ID'
        ]
        return any(os.getenv(var) for var in railway_indicators)
    
    def _safe_redis_operation(self, operation_func, *args, **kwargs):
        """Perform Redis operation with retry logic and timeout handling"""
        if not self.redis_client:
            return None
            
        max_retries = 2
        retry_delay = 0.1
        
        for attempt in range(max_retries + 1):
            try:
                return operation_func(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError) as e:
                if attempt < max_retries:
                    logger.warning(f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    logger.warning(f"Redis operation failed after {max_retries + 1} attempts: {e}")
                    return None
            except Exception as e:
                logger.warning(f"Unexpected Redis error: {e}")
                return None
    
    def _generate_cache_key(self, documents: list, features: dict) -> str:
        """Generate deterministic cache key for document + features combo"""
        # Create hash of documents + features for cache key
        doc_hashes = []
        for doc in sorted(documents, key=lambda x: x.get('order', 0)):
            doc_content = f"{doc.get('filename', '')}{doc.get('content', '')}{doc.get('order', 0)}"
            doc_hashes.append(hashlib.md5(doc_content.encode()).hexdigest()[:16])
        
        features_str = json.dumps(features, sort_keys=True)
        features_hash = hashlib.md5(features_str.encode()).hexdigest()[:16]
        
        return f"doc_cache:{'_'.join(doc_hashes)}:{features_hash}"
    
    def _generate_output_filename(self, documents: list) -> str:
        """Generate output filename based on first document name with (compiled) suffix"""
        # Sort documents by order to get the first one
        sorted_docs = sorted(documents, key=lambda x: x.get('order', 0))
        first_doc_filename = sorted_docs[0].get('filename', 'document.pdf')
        
        # Remove .pdf extension and add (compiled)
        base_name = first_doc_filename.replace('.pdf', '').replace('.PDF', '')
        return f"{base_name} (compiled).pdf"
        
    def lambda_handler(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Simplified handler: processes documents and returns PDF immediately
        """
        try:
            return self._handle_process_documents(event)
                
        except Exception as e:
            logger.error(f"Error in processing: {str(e)}")
            return self._error_response(f"Processing failed: {str(e)}", 500)
    
    def _handle_process_documents(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process documents and return PDF immediately"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        
        if not documents:
            return self._error_response("No documents provided", 400)
        
        if not any(features.values()):
            return self._error_response("No features selected", 400)
        
        logger.info("Processing documents")
        
        # Generate cache key
        cache_key = self._generate_cache_key(documents, features)
        
        # Try Redis cache first for instant response
        cached_result = self._safe_redis_operation(self.redis_client.get, cache_key) if self.redis_client else None
        
        if cached_result:
            # CACHE HIT - Ultra fast response (< 10ms)
            logger.info(f"Cache HIT for {cache_key} - returning instant result")
            try:
                if isinstance(cached_result, bytes):
                    cached_result_str = cached_result.decode('utf-8')
                else:
                    cached_result_str = cached_result
                cached_data = json.loads(cached_result_str)
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': True,
                        'processed_document': {
                            'filename': self._generate_output_filename(documents),
                            'content': cached_data['output_pdf'],
                            'pages': cached_data['total_pages'],
                            'features_applied': cached_data['features_applied'],
                            'processing_time_seconds': 0.01,
                            'from_cache': True
                        }
                    }),
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
                }
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Cache data corrupted, proceeding with fresh processing: {e}")
        
        # CACHE MISS or No Redis - Process documents
        logger.info(f"Cache MISS for {cache_key} - processing documents")
        
        # Sort documents by order
        documents.sort(key=lambda x: x.get('order', 0))
        
        # Process documents with all features applied
        result = self._process_documents_fast(documents, features)
        
        # Cache the result in Redis with 1-hour expiration
        if self.redis_client:
            cache_data = {
                'output_pdf': result['output_pdf'],
                'total_pages': result['total_pages'],
                'features_applied': result['features_applied'],
                'processed_at': time.time()
            }
            
            # Store in Redis with 1-hour TTL (3600 seconds) using safe operation
            cache_success = self._safe_redis_operation(
                self.redis_client.setex,
                cache_key,
                3600,  # 1 hour expiration
                json.dumps(cache_data)
            )
            
            if cache_success:
                logger.info(f"Cached result for {cache_key} - expires in 1 hour")
            else:
                logger.warning(f"Failed to cache result for {cache_key} - proceeding without cache")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'processed_document': {
                    'filename': self._generate_output_filename(documents),
                    'content': result['output_pdf'],
                    'pages': result['total_pages'],
                    'features_applied': result['features_applied'],
                    'processing_time_seconds': result.get('processing_time', 0),
                    'from_cache': False
                }
            }),
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
        }

    
    
    
    
    def _process_documents_fast(self, documents: List[Dict], features: Dict) -> Dict[str, Any]:
        """Process documents with maximum parallelization and speed optimization"""
        
        start_time = time.time()
        
        # Decode PDFs in parallel (fastest bottleneck)
        pdf_readers: List[PdfReader] = self._parallel_decode_pdfs_optimized(documents)
        
        result = {
            'total_pages': sum(len(pdf.pages) for pdf in pdf_readers),
            'document_count': len(pdf_readers),
            'features_applied': []
        }
        
        current_pdfs: List[PdfObject] = list(pdf_readers)
        
        # Apply features in optimal order (merge first for efficiency)
        if features.get('merge_pdfs', False):
            merged_pdf = self._merge_pdfs_fast(current_pdfs)
            current_pdfs = [merged_pdf]
            result['features_applied'].append('merge_pdfs')
            logger.info("PDFs merged successfully")
        
        if features.get('repaginate', False):
            repaginated_pdfs = self._repaginate_pdfs_fast(current_pdfs)
            current_pdfs = list(repaginated_pdfs)
            result['features_applied'].append('repaginate')
            logger.info("Re-pagination completed")
        
        if features.get('tenth_lining', False):
            tenth_lined_pdfs = self._apply_tenth_lining_fast(current_pdfs)
            current_pdfs = list(tenth_lined_pdfs)
            result['features_applied'].append('tenth_lining')
            logger.info("10th lining applied")
        
        # Convert final result to base64
        final_pdf = current_pdfs[0] if len(current_pdfs) == 1 else self._merge_pdfs_fast(current_pdfs)
        result['output_pdf'] = self._pdf_to_base64(final_pdf)
        result['processing_time'] = round(time.time() - start_time, 2)
        
        return result
    
    def _parallel_decode_pdfs_optimized(self, documents: List[Dict]) -> List[PdfReader]:
        """Optimized parallel PDF decoding with error handling"""
        
        def decode_single_pdf_fast(doc_data):
            try:
                content = base64.b64decode(doc_data['content'])
                return PdfReader(io.BytesIO(content))
            except Exception as e:
                logger.error(f"Failed to decode PDF {doc_data.get('filename', 'unknown')}: {e}")
                raise ValueError(f"Invalid PDF: {doc_data.get('filename', 'unknown')}")
        
        # Use optimal thread count for I/O bound operations
        with ThreadPoolExecutor(max_workers=min(len(documents) * 2, self.max_workers)) as executor:
            pdf_readers = list(executor.map(decode_single_pdf_fast, documents))
        
        return pdf_readers
    
    def _merge_pdfs_fast(self, pdf_objects: Sequence[PdfObject]) -> PdfWriter:
        """Optimized PDF merging"""
        writer = PdfWriter()
        
        for pdf_obj in pdf_objects:
            if isinstance(pdf_obj, PdfWriter):
                temp_buffer = io.BytesIO()
                pdf_obj.write(temp_buffer)
                temp_buffer.seek(0)
                reader = PdfReader(temp_buffer)
                for page in reader.pages:
                    writer.add_page(page)
            elif isinstance(pdf_obj, PdfReader):
                for page in pdf_obj.pages:
                    writer.add_page(page)
        
        return writer
    
    def _repaginate_pdfs_fast(self, pdf_objects: Sequence[PdfObject]) -> List[PdfWriter]:
        """Optimized re-pagination with parallel processing"""
        
        def add_page_numbers_fast(pdf_obj: PdfObject) -> PdfWriter:
            if isinstance(pdf_obj, PdfWriter):
                temp_buffer = io.BytesIO()
                pdf_obj.write(temp_buffer)
                temp_buffer.seek(0)
                reader = PdfReader(temp_buffer)
            else:
                reader = pdf_obj
            
            writer = PdfWriter()
            
            for page_num, page in enumerate(reader.pages, 1):
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                can.setFont("Helvetica", 15)
                can.drawString(letter[0] - 50, letter[1] - 30, str(page_num))
                can.save()
                
                packet.seek(0)
                overlay = PdfReader(packet)
                page.merge_page(overlay.pages[0])
                writer.add_page(page)
            
            return writer
        
        # Process in parallel if multiple PDFs
        if len(pdf_objects) > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                return list(executor.map(add_page_numbers_fast, pdf_objects))
        else:
            return [add_page_numbers_fast(pdf_objects[0])]
    
    def _apply_tenth_lining_fast(self, pdf_objects: Sequence[PdfObject]) -> List[PdfReader]:
        """Optimized 10th line numbering with improved complex PDF handling"""
        
        def add_tenth_lines_fast(pdf_obj: PdfObject) -> PdfReader:
            if isinstance(pdf_obj, PdfWriter):
                temp_buffer = io.BytesIO()
                pdf_obj.write(temp_buffer)
                temp_buffer.seek(0)
                doc = fitz.Document(stream=temp_buffer.read(), filetype="pdf")
            else:
                temp_buffer = io.BytesIO()
                writer = PdfWriter()
                for page in pdf_obj.pages:
                    writer.add_page(page)
                writer.write(temp_buffer)
                temp_buffer.seek(0)
                doc = fitz.Document(stream=temp_buffer.read(), filetype="pdf")
            
            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_rect = page.rect
                
                # Get text blocks and filter for main content
                text_dict = page.get_text("dict")
                main_content_lines = self._extract_main_content_lines(text_dict, page_rect)
                
                line_count = 0
                for line_info in main_content_lines:
                    line_count += 1
                    
                    if line_count % 10 == 0:
                        y = line_info['y']
                        
                        # Right-align the line numbers at the page margin
                        x = page_rect.width - 50  # 50 points from right edge
                        
                        page.insert_text(
                            (x, y),
                            str(line_count),
                            fontsize=9.6,
                            color=(0.5, 0.5, 0.5)
                        )
            
            output_buffer = io.BytesIO()
            doc.save(output_buffer)
            doc.close()
            output_buffer.seek(0)
            
            return PdfReader(output_buffer)
        
        # Process in parallel if multiple PDFs
        if len(pdf_objects) > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                return list(executor.map(add_tenth_lines_fast, pdf_objects))
        else:
            return [add_tenth_lines_fast(pdf_objects[0])]
    
    def _extract_main_content_lines(self, text_dict: dict, page_rect) -> list:
        """Extract only main content lines, filtering out watermarks, headers, footers, and decorative elements"""
        lines = []
        page_width = page_rect.width
        page_height = page_rect.height
        
        # Define margins to exclude headers/footers (top 10% and bottom 10% of page)
        header_threshold = page_height * 0.9  # Top 10%
        footer_threshold = page_height * 0.1  # Bottom 10%
        
        # Define side margins (left/right 5% of page) to exclude margin notes
        left_margin = page_width * 0.05
        right_margin = page_width * 0.95
        
        for block in text_dict.get("blocks", []):
            if not block.get("lines"):
                continue
                
            # Skip image blocks (they contain OCR'd text we don't want)
            if block.get("type") == 1:  # Image block
                continue
                
            block_bbox = block.get("bbox", [0, 0, 0, 0])
            block_height = block_bbox[3] - block_bbox[1]
            block_width = block_bbox[2] - block_bbox[0]
            
            # Skip very small blocks (likely decorative elements)
            if block_height < 10 or block_width < 50:
                continue
                
            # Skip blocks in header/footer areas
            block_center_y = (block_bbox[1] + block_bbox[3]) / 2
            if block_center_y > header_threshold or block_center_y < footer_threshold:
                continue
                
            # Skip blocks in side margins (margin notes, line numbers, etc.)
            block_center_x = (block_bbox[0] + block_bbox[2]) / 2
            if block_center_x < left_margin or block_center_x > right_margin:
                continue
            
            for line in block["lines"]:
                line_bbox = line.get("bbox", [0, 0, 0, 0])
                line_text = ""
                
                # Extract text from spans
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        line_text += text + " "
                
                line_text = line_text.strip()
                
                # Skip empty lines or lines with just whitespace
                if not line_text or len(line_text) < 3:
                    continue
                
                # Skip lines that look like watermarks (typically short, centered, or repeated)
                if self._is_likely_watermark(line_text, line_bbox, page_rect):
                    continue
                    
                # Skip lines that are likely headers/footers based on content
                if self._is_likely_header_footer(line_text):
                    continue
                
                # Skip table headers and single-cell content
                if self._is_likely_table_element(line_text, line_bbox):
                    continue
                
                y = (line_bbox[1] + line_bbox[3]) / 2
                lines.append({
                    'y': y,
                    'text': line_text,
                    'bbox': line_bbox
                })
        
        # Sort lines by vertical position (top to bottom)
        # In PyMuPDF coordinates, Y=0 is at top, Y increases downward
        lines.sort(key=lambda x: x['y'])  # Ascending order: smallest Y (top) first
        
        return lines
    
    def _is_likely_watermark(self, text: str, line_bbox: list, page_rect) -> bool:
        """Detect if a line is likely a watermark"""
        # Check for common watermark keywords
        watermark_keywords = [
            'draft', 'confidential', 'copy', 'sample', 'watermark', 
            'preview', 'trial', 'demo', 'copyright', '©', 'trademark'
        ]
        
        text_lower = text.lower()
        if any(keyword in text_lower for keyword in watermark_keywords):
            return True
        
        # Check if text is centered (likely watermark)
        line_center_x = (line_bbox[0] + line_bbox[2]) / 2
        page_center_x = page_rect.width / 2
        if abs(line_center_x - page_center_x) < 50:  # Within 50 points of center
            # Short centered text is likely a watermark
            if len(text) < 30:
                return True
        
        # Check for repeated single words (common in watermarks)
        words = text.split()
        if len(words) == 1 and len(words[0]) < 15:
            return True
            
        return False
    
    def _is_likely_header_footer(self, text: str) -> bool:
        """Detect if a line is likely a header or footer"""
        text_lower = text.lower()
        
        # Common header/footer patterns
        header_footer_patterns = [
            'page', 'chapter', 'section', 'exhibit', 'appendix',
            'confidential', 'attorney-client', 'privileged',
            'copyright', 'all rights reserved', '©'
        ]
        
        # Check for page numbers (standalone numbers)
        if text.strip().isdigit() and len(text.strip()) < 4:
            return True
            
        # Check for common header/footer text
        if any(pattern in text_lower for pattern in header_footer_patterns):
            return True
            
        # Check for date patterns
        import re
        date_patterns = [
            r'\d{1,2}/\d{1,2}/\d{2,4}',
            r'\d{1,2}-\d{1,2}-\d{2,4}',
            r'\w+ \d{1,2}, \d{4}'
        ]
        
        if any(re.search(pattern, text) for pattern in date_patterns):
            return True
            
        return False
    
    def _is_likely_table_element(self, text: str, line_bbox: list) -> bool:
        """Detect if a line is likely part of a table header or single cell"""
        # Very short text is likely a table cell
        if len(text.strip()) < 3:
            return True
            
        # Single words that are likely column headers
        single_word_headers = [
            'name', 'date', 'amount', 'total', 'item', 'description',
            'quantity', 'price', 'cost', 'number', 'id', 'type',
            'status', 'yes', 'no', 'n/a', 'tbd', 'pending'
        ]
        
        words = text.lower().split()
        if len(words) == 1 and words[0] in single_word_headers:
            return True
            
        # Lines with mostly numbers/symbols (table data)
        non_alpha = sum(1 for c in text if not c.isalpha() and not c.isspace())
        alpha = sum(1 for c in text if c.isalpha())
        
        if non_alpha > alpha and len(text) < 20:
            return True
            
        return False
    
    def _pdf_to_base64(self, pdf_obj: PdfObject) -> str:
        """Convert PDF object to base64 string"""
        buffer = io.BytesIO()
        
        if isinstance(pdf_obj, PdfWriter):
            pdf_obj.write(buffer)
        else:
            writer = PdfWriter()
            for page in pdf_obj.pages:
                writer.add_page(page)
            writer.write(buffer)
        
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    def _error_response(self, message: str, status_code: int) -> Dict[str, Any]:
        """Generate standardized error response"""
        return {
            'statusCode': status_code,
            'body': json.dumps({
                'success': False,
                'error': message
            }),
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
        }

# Serverless function entry points
processor = StatelessLegalProcessor()

def lambda_handler(event, context):
    """AWS Lambda handler"""
    return processor.lambda_handler(event, context)

def azure_function_handler(req):
    """Azure Functions handler"""
    try:
        event = req.get_json()
        return processor.lambda_handler(event, None)
    except Exception as e:
        return processor._error_response(str(e), 500)

def gcp_cloud_function_handler(request):
    """Google Cloud Functions handler"""
    try:
        event = request.get_json()
        response = processor.lambda_handler(event, None)
        return response['body'], response['statusCode']
    except Exception as e:
        return json.dumps({'error': str(e)}), 500

# Local testing example for simplified workflow
if __name__ == "__main__":
    # Direct document processing - no payment required
    process_event = {
        "documents": [
            {
                "filename": "brief.pdf",
                "content": "base64_encoded_content_here",
                "order": 1
            }
        ],
        "features": {
            "merge_pdfs": True,
            "repaginate": True,
            "tenth_lining": False
        }
    }
    
    print("=== Document Processing (0.1-5 seconds) ===")
    result = lambda_handler(process_event, None)
    print(json.dumps(result, indent=2))
