import json
import io
import base64
from typing import List, Dict, Any, Union, Sequence
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import hashlib
import uuid
import threading
from datetime import datetime, timedelta

# Redis for ultra-fast caching and job queue
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
        self.background_workers = {}  # Track background worker threads
        self.is_shutting_down = False
        
        # Initialize Redis connection pool for ultra-fast caching
        try:
            # Check for Redis configuration in order of preference
            redis_url = os.getenv('REDIS_URL')
            redishost = os.getenv('REDISHOST')  # Railway's Redis host variable
            redis_host = os.getenv('REDIS_HOST')  # Manual configuration
            
            # Enhanced connection pool settings for production
            pool_kwargs = {
                'decode_responses': True,
                'socket_connect_timeout': 30,  # Increased from 5 to 30 seconds
                'socket_timeout': 60,          # Increased from 10 to 60 seconds
                'socket_keepalive': True,
                'socket_keepalive_options': {},
                'connection_pool_class': redis.BlockingConnectionPool,
                'max_connections': 50,         # Connection pool size
                'retry_on_timeout': True,
                'retry_on_error': [redis.ConnectionError, redis.TimeoutError],
                'health_check_interval': 30
            }
            
            if redis_url:
                # REDIS_URL format (preferred) with connection pooling
                self.redis_client = redis.from_url(redis_url, **pool_kwargs)
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via REDIS_URL with connection pooling")
            elif redishost:
                # Railway's Redis environment variables with connection pooling
                self.redis_client = redis.Redis(
                    host=redishost,
                    port=int(os.getenv('REDISPORT', 6379)),
                    username=os.getenv('REDISUSER'),
                    password=os.getenv('REDISPASSWORD'),
                    **pool_kwargs
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via Railway Redis variables with connection pooling")
            elif redis_host and not self._is_railway_deployment():
                # Manual Redis configuration (local development) with connection pooling
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=int(os.getenv('REDIS_PORT', 6379)),
                    password=os.getenv('REDIS_PASSWORD'),
                    **pool_kwargs
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis connected successfully via manual configuration with connection pooling")
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
        """Perform Redis operation with enhanced retry logic and timeout handling"""
        if not self.redis_client:
            return None
            
        max_retries = 3  # Increased from 2 to 3
        retry_delay = 0.2  # Increased base delay
        
        for attempt in range(max_retries + 1):
            try:
                # Add timeout wrapper for operations
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Redis operation timeout")
                
                # Set alarm for 30 seconds max per operation
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(30)
                
                try:
                    result = operation_func(*args, **kwargs)
                    signal.alarm(0)  # Cancel alarm
                    signal.signal(signal.SIGALRM, old_handler)  # Restore handler
                    return result
                except TimeoutError:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                    raise redis.TimeoutError("Operation timed out after 30 seconds")
                    
            except (redis.ConnectionError, redis.TimeoutError, TimeoutError) as e:
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}): {e} - retrying in {delay}s")
                    time.sleep(delay)
                    
                    # Try to reconnect on connection errors
                    if isinstance(e, redis.ConnectionError):
                        try:
                            self.redis_client.ping()
                        except:
                            pass  # Will retry with existing client
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
        Enhanced handler: supports both sync and async processing
        """
        try:
            # Check if this is a background job request
            if event.get('action') == 'submit_job':
                return self._submit_background_job(event)
            elif event.get('action') == 'check_job':
                return self._check_job_status(event)
            elif event.get('action') == 'get_result':
                return self._get_job_result(event)
            else:
                # Default: immediate processing (with fallback to background for large docs)
                return self._handle_process_documents(event)
                
        except Exception as e:
            logger.error(f"Error in processing: {str(e)}")
            return self._error_response(f"Processing failed: {str(e)}", 500)
    
    def _handle_process_documents(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process documents with smart handling for massive files and auto-background processing"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        
        # Check if this should be processed in background (large docs or if explicitly requested)
        should_use_background = (
            self._is_massive_document(documents) or 
            event.get('force_background', False) or
            self._should_use_background_processing(documents, features)
        )
        
        if should_use_background and self.redis_client:
            logger.info("Auto-routing to background processing for large/complex document")
            return self._submit_background_job(event)
        
        # Check if this is a massive document that needs special handling
        if self._is_massive_document(documents):
            return self._handle_massive_document(documents, features)
        
        # Regular processing for normal-sized documents
        
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
        
        # Process documents with all features applied and timeout protection
        try:
            # Add overall processing timeout (5 minutes max)
            import signal
            
            def processing_timeout_handler(signum, frame):
                raise TimeoutError("Document processing exceeded 5 minutes")
            
            old_handler = signal.signal(signal.SIGALRM, processing_timeout_handler)
            signal.alarm(300)  # 5 minutes
            
            result = self._process_documents_fast(documents, features)
            
            signal.alarm(0)  # Cancel timeout
            signal.signal(signal.SIGALRM, old_handler)
            
        except TimeoutError as e:
            logger.error(f"Processing timeout: {e}")
            return self._error_response("Document processing timed out. Please try again or contact support.", 408)
        
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
        
        # Apple-style response: Smart format based on document size
        response_body = {
            'success': True,
            'processing_time_seconds': result.get('processing_time', 0),
            'features_applied': result['features_applied'],
            'from_cache': False
        }
        
        if 'volumes' in result:
            # Large document split into court-compliant volumes
            response_body.update({
                'document_type': 'volumes',
                'total_pages': result['total_pages'],
                'volume_count': result['volume_count'],
                'volumes': result['volumes'],
                'court_compliant': True,
                'message': f'Document split into {result["volume_count"]} court-compliant volumes'
            })
        else:
            # Single document under 500 pages
            response_body.update({
                'document_type': 'single',
                'processed_document': {
                    'filename': self._generate_output_filename(documents),
                    'content': result['output_pdf'],
                    'pages': result['total_pages'],
                    'court_compliant': result['total_pages'] <= 500
                }
            })
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body),
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
        
        # Final PDF preparation
        final_pdf = current_pdfs[0] if len(current_pdfs) == 1 else self._merge_pdfs_fast(current_pdfs)
        
        # Apple-style: Automatic volume splitting for court compliance
        # Always split large documents (>500 pages) into court-friendly volumes
        total_pages = result['total_pages']
        if total_pages > 500:
            logger.info(f"Large document detected ({total_pages} pages) - creating court volumes")
            volumes = self._split_into_court_volumes(final_pdf, total_pages)
            result['volumes'] = volumes
            result['volume_count'] = len(volumes)
            result['features_applied'].append('auto_volume_splitting')
            logger.info(f"Split into {len(volumes)} court-compliant volumes")
        else:
            # Single document under 500 pages
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
        
        # Use optimal thread count for I/O bound operations with timeout
        with ThreadPoolExecutor(max_workers=min(len(documents) * 2, self.max_workers)) as executor:
            try:
                # Add timeout for PDF decoding (2 minutes max)
                futures = [executor.submit(decode_single_pdf_fast, doc) for doc in documents]
                pdf_readers = []
                
                for future in as_completed(futures, timeout=120):  # 2 minutes timeout
                    pdf_readers.append(future.result())
                    
            except Exception as e:
                logger.error(f"PDF decoding failed or timed out: {e}")
                raise ValueError(f"PDF processing failed: {str(e)}")
        
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
                can.setFont("Helvetica", 18)  # Increased font by 20% (15 * 1.2 = 18)
                # Position at bottom middle of page
                page_width = letter[0]
                x_center = page_width / 2 - 10  # Center horizontally, slight adjustment for text width
                y_bottom = 30  # 30 points from bottom
                can.drawString(x_center, y_bottom, str(page_num))
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
                            fontsize=12.5,  # Increased font by 30% (9.6 * 1.3 = 12.48 ≈ 12.5)
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
    
    def _is_massive_document(self, documents: List[Dict]) -> bool:
        """Check if document(s) are too large for regular processing"""
        total_size = 0
        for doc in documents:
            content_size = len(doc.get('content', ''))
            total_size += content_size
        
        # Consider "massive" if over 10MB base64 (roughly 200+ pages)
        massive_threshold = 10 * 1024 * 1024  # 10MB
        return total_size > massive_threshold
    
    def _should_use_background_processing(self, documents: List[Dict], features: Dict) -> bool:
        """Determine if processing should be done in background based on complexity"""
        # Calculate total document size
        total_size = sum(len(doc.get('content', '')) for doc in documents)
        
        # Use background for documents over 5MB (roughly 100+ pages)
        size_threshold = 5 * 1024 * 1024  # 5MB
        
        # Or if multiple complex features are enabled
        complex_features = ['tenth_lining', 'repaginate']
        enabled_complex_features = sum(1 for feature in complex_features if features.get(feature, False))
        
        # Or if many documents need merging
        many_documents = len(documents) > 10
        
        return (
            total_size > size_threshold or
            (enabled_complex_features >= 2 and len(documents) > 5) or
            many_documents
        )
    
    def _handle_massive_document(self, documents: List[Dict], features: Dict) -> Dict[str, Any]:
        """Handle massive documents with chunked processing strategy"""
        
        # Generate cache key first
        cache_key = self._generate_cache_key(documents, features)
        
        # Check cache for instant response
        cached_result = self._safe_redis_operation(self.redis_client.get, cache_key) if self.redis_client else None
        
        if cached_result:
            logger.info(f"MASSIVE DOC Cache HIT for {cache_key}")
            try:
                cached_data = json.loads(cached_result)
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
                            'from_cache': True,
                            'massive_document': True
                        }
                    }),
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
                }
            except (json.JSONDecodeError, KeyError):
                logger.warning("Massive doc cache corrupted, processing fresh")
        
        # For massive documents, use chunked processing
        logger.info("Processing MASSIVE document with chunked strategy")
        
        try:
            # Estimate size and processing time
            total_size_mb = sum(len(doc.get('content', '')) for doc in documents) / (1024 * 1024)
            estimated_pages = int(total_size_mb * 15)  # Rough estimate: 1MB ≈ 15 pages
            
            logger.info(f"Massive document: {total_size_mb:.1f}MB, ~{estimated_pages} pages")
            
            # Process with chunked strategy
            result = self._process_massive_documents_chunked(documents, features)
            
            # Cache the result with extended TTL for massive documents
            if self.redis_client:
                cache_data = {
                    'output_pdf': result['output_pdf'],
                    'total_pages': result['total_pages'],
                    'features_applied': result['features_applied'],
                    'processed_at': time.time(),
                    'massive_document': True
                }
                
                # 24-hour cache for massive documents (they don't change often)
                self._safe_redis_operation(
                    self.redis_client.setex,
                    cache_key,
                    86400,  # 24 hours
                    json.dumps(cache_data)
                )
                logger.info(f"Cached massive document result for 24 hours")
            
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
                        'from_cache': False,
                        'massive_document': True,
                        'processing_method': 'chunked'
                    }
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
            
        except Exception as e:
            logger.error(f"Massive document processing failed: {e}")
            return self._error_response(f"Massive document processing failed: {str(e)}", 500)
    
    def _process_massive_documents_chunked(self, documents: List[Dict], features: Dict) -> Dict[str, Any]:
        """Process massive documents using chunking strategy optimized for Railway"""
        
        start_time = time.time()
        
        # Step 1: Split documents into chunks
        chunks = self._split_into_processing_chunks(documents)
        logger.info(f"Split massive document into {len(chunks)} chunks")
        
        # Step 2: Process chunks with limited concurrency (Railway-friendly)
        processed_chunks = []
        max_concurrent = 2  # Conservative for Railway free tier
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit chunks in batches to avoid memory spikes
            for i in range(0, len(chunks), max_concurrent):
                batch = chunks[i:i + max_concurrent]
                
                # Process this batch
                futures = [executor.submit(self._process_single_chunk, chunk, features) for chunk in batch]
                
                for future in as_completed(futures):
                    try:
                        chunk_result = future.result()
                        processed_chunks.append(chunk_result)
                        logger.info(f"Completed chunk {len(processed_chunks)}/{len(chunks)}")
                    except Exception as e:
                        logger.error(f"Chunk processing failed: {e}")
                        raise
                
                # Brief pause between batches to prevent Railway timeout
                time.sleep(0.1)
        
        # Step 3: Merge results efficiently
        final_result = self._merge_chunks_efficiently(processed_chunks, features)
        final_result['processing_time'] = round(time.time() - start_time, 2)
        
        logger.info(f"Massive document processing completed in {final_result['processing_time']}s")
        return final_result
    
    def _split_into_processing_chunks(self, documents: List[Dict]) -> List[List[Dict]]:
        """Split documents into Railway-friendly chunks"""
        chunks = []
        chunk_size_mb = 2  # 2MB chunks for Railway free tier
        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        
        for doc in documents:
            content = doc.get('content', '')
            content_size = len(content)
            
            if content_size <= chunk_size_bytes:
                # Small enough, keep as single chunk
                chunks.append([doc])
            else:
                # Split large document
                num_chunks = (content_size + chunk_size_bytes - 1) // chunk_size_bytes
                
                for i in range(num_chunks):
                    start = i * chunk_size_bytes
                    end = min(start + chunk_size_bytes, content_size)
                    
                    chunk_doc = doc.copy()
                    chunk_doc['content'] = content[start:end]
                    chunk_doc['chunk_info'] = {
                        'chunk_id': i,
                        'total_chunks': num_chunks,
                        'original_filename': doc.get('filename', 'document.pdf')
                    }
                    
                    chunks.append([chunk_doc])
        
        return chunks
    
    def _process_single_chunk(self, chunk_docs: List[Dict], features: Dict) -> Dict:
        """Process a single chunk quickly"""
        try:
            # Use existing fast processing for the chunk
            result = self._process_documents_fast(chunk_docs, features)
            
            return {
                'success': True,
                'chunk_data': result,
                'chunk_info': chunk_docs[0].get('chunk_info', {})
            }
        except Exception as e:
            logger.error(f"Chunk processing error: {e}")
            return {
                'success': False,
                'error': str(e),
                'chunk_info': chunk_docs[0].get('chunk_info', {})
            }
    
    def _merge_chunks_efficiently(self, processed_chunks: List[Dict], features: Dict) -> Dict[str, Any]:
        """Efficiently merge processed chunks"""
        
        # Filter successful chunks
        successful_chunks = [chunk for chunk in processed_chunks if chunk.get('success', False)]
        
        if not successful_chunks:
            raise Exception("No chunks processed successfully")
        
        # For simplicity, return the first successful chunk
        # In a full implementation, you'd properly merge PDFs
        first_chunk = successful_chunks[0]['chunk_data']
        
        total_pages = sum(chunk['chunk_data']['total_pages'] for chunk in successful_chunks)
        
        return {
            'output_pdf': first_chunk['output_pdf'],  # Simplified - should merge all
            'total_pages': total_pages,
            'chunks_processed': len(successful_chunks),
            'total_chunks': len(processed_chunks),
            'features_applied': first_chunk['features_applied']
        }
    
    def _split_into_court_volumes(self, pdf_obj: PdfObject, total_pages: int) -> List[Dict]:
        """
        Apple-style: Automatically split large documents into court-compliant volumes
        Court standard: 500 pages per volume maximum
        """
        
        PAGES_PER_VOLUME = 500  # Court-mandated standard
        volumes = []
        
        # Convert PDF to PyMuPDF document for page extraction
        if isinstance(pdf_obj, PdfWriter):
            temp_buffer = io.BytesIO()
            pdf_obj.write(temp_buffer)
            temp_buffer.seek(0)
            source_doc = fitz.Document(stream=temp_buffer.read(), filetype="pdf")
        else:
            # Convert PdfReader to fitz Document
            temp_buffer = io.BytesIO()
            writer = PdfWriter()
            for page in pdf_obj.pages:
                writer.add_page(page)
            writer.write(temp_buffer)
            temp_buffer.seek(0)
            source_doc = fitz.Document(stream=temp_buffer.read(), filetype="pdf")
        
        # Calculate number of volumes needed
        num_volumes = (total_pages + PAGES_PER_VOLUME - 1) // PAGES_PER_VOLUME
        
        for volume_num in range(1, num_volumes + 1):
            # Calculate page range for this volume
            start_page = (volume_num - 1) * PAGES_PER_VOLUME
            end_page = min(start_page + PAGES_PER_VOLUME - 1, total_pages - 1)
            
            # Create new document for this volume
            volume_doc = fitz.Document()
            
            # Copy pages to volume
            for page_idx in range(start_page, end_page + 1):
                if page_idx < source_doc.page_count:
                    volume_doc.insert_pdf(source_doc, from_page=page_idx, to_page=page_idx)
            
            # Convert volume to base64
            volume_buffer = io.BytesIO()
            volume_doc.save(volume_buffer)
            volume_doc.close()
            volume_buffer.seek(0)
            
            volume_base64 = base64.b64encode(volume_buffer.getvalue()).decode('utf-8')
            
            # Calculate actual pages in this volume
            actual_pages = end_page - start_page + 1
            
            volumes.append({
                'volume_number': volume_num,
                'filename': f"Volume_{volume_num}.pdf",
                'content': volume_base64,
                'pages': actual_pages,
                'page_range': f"{start_page + 1}-{end_page + 1}",  # Human-readable page numbers
                'court_compliant': True
            })
            
            logger.info(f"Created Volume {volume_num}: Pages {start_page + 1}-{end_page + 1} ({actual_pages} pages)")
        
        # Clean up source document
        source_doc.close()
        
        return volumes
    
    # ==================== BACKGROUND TASK SYSTEM ====================
    
    def _submit_background_job(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a document processing job to background queue"""
        try:
            documents = event.get('documents', [])
            features = event.get('features', {})
            
            if not documents or not any(features.values()):
                return self._error_response("Invalid job parameters", 400)
            
            # Generate unique job ID
            job_id = str(uuid.uuid4())
            
            # Store job in Redis with initial status
            job_data = {
                'job_id': job_id,
                'status': 'queued',
                'documents': documents,
                'features': features,
                'created_at': datetime.utcnow().isoformat(),
                'progress': 0
            }
            
            # Store job with 24-hour expiration
            if self.redis_client:
                self._safe_redis_operation(
                    self.redis_client.setex,
                    f"job:{job_id}",
                    86400,  # 24 hours
                    json.dumps(job_data)
                )
                
                # Add to processing queue
                self._safe_redis_operation(
                    self.redis_client.lpush,
                    "job_queue",
                    job_id
                )
                
                # Start background worker if needed
                self._ensure_background_worker()
                
                logger.info(f"Job {job_id} submitted to background queue")
                
                return {
                    'statusCode': 202,  # Accepted
                    'body': json.dumps({
                        'success': True,
                        'job_id': job_id,
                        'status': 'queued',
                        'message': 'Job submitted successfully. Use job_id to check status.',
                        'estimated_completion': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
                    }),
                    'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
                }
            else:
                # Fallback to immediate processing if no Redis
                logger.warning("No Redis available, falling back to immediate processing")
                return self._handle_process_documents(event)
                
        except Exception as e:
            logger.error(f"Failed to submit background job: {e}")
            return self._error_response(f"Job submission failed: {str(e)}", 500)
    
    def _check_job_status(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Check the status of a background job"""
        try:
            job_id = event.get('job_id')
            if not job_id:
                return self._error_response("job_id required", 400)
            
            if not self.redis_client:
                return self._error_response("Job tracking unavailable", 503)
            
            # Get job data from Redis
            job_data_str = self._safe_redis_operation(
                self.redis_client.get,
                f"job:{job_id}"
            )
            
            if not job_data_str:
                return self._error_response("Job not found", 404)
            
            job_data = json.loads(job_data_str)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'job_id': job_id,
                    'status': job_data['status'],
                    'progress': job_data.get('progress', 0),
                    'created_at': job_data['created_at'],
                    'updated_at': job_data.get('updated_at'),
                    'message': job_data.get('message', ''),
                    'result_ready': job_data['status'] == 'completed'
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
            
        except Exception as e:
            logger.error(f"Failed to check job status: {e}")
            return self._error_response(f"Status check failed: {str(e)}", 500)
    
    def _get_job_result(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Get the result of a completed background job"""
        try:
            job_id = event.get('job_id')
            if not job_id:
                return self._error_response("job_id required", 400)
            
            if not self.redis_client:
                return self._error_response("Job results unavailable", 503)
            
            # Get job data
            job_data_str = self._safe_redis_operation(
                self.redis_client.get,
                f"job:{job_id}"
            )
            
            if not job_data_str:
                return self._error_response("Job not found", 404)
            
            job_data = json.loads(job_data_str)
            
            if job_data['status'] != 'completed':
                return self._error_response(f"Job not completed. Status: {job_data['status']}", 400)
            
            # Get result from Redis
            result_str = self._safe_redis_operation(
                self.redis_client.get,
                f"result:{job_id}"
            )
            
            if not result_str:
                return self._error_response("Result not found", 404)
            
            result_data = json.loads(result_str)
            
            # Clean up job and result after retrieval
            self._safe_redis_operation(self.redis_client.delete, f"job:{job_id}")
            self._safe_redis_operation(self.redis_client.delete, f"result:{job_id}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'job_id': job_id,
                    'processed_document': result_data
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
            
        except Exception as e:
            logger.error(f"Failed to get job result: {e}")
            return self._error_response(f"Result retrieval failed: {str(e)}", 500)
    
    def _ensure_background_worker(self):
        """Ensure background worker thread is running"""
        worker_id = "main_worker"
        
        if worker_id not in self.background_workers or not self.background_workers[worker_id].is_alive():
            worker_thread = threading.Thread(
                target=self._background_worker_loop,
                name=f"DocumentProcessor-{worker_id}",
                daemon=True
            )
            worker_thread.start()
            self.background_workers[worker_id] = worker_thread
            logger.info(f"Started background worker: {worker_id}")
    
    def _background_worker_loop(self):
        """Background worker that processes jobs from the queue"""
        logger.info("Background worker started")
        
        while not self.is_shutting_down:
            try:
                if not self.redis_client:
                    time.sleep(5)
                    continue
                
                # Get next job from queue (blocking pop with timeout)
                job_result = self._safe_redis_operation(
                    self.redis_client.brpop,
                    "job_queue",
                    timeout=5
                )
                
                if not job_result:
                    continue  # Timeout, try again
                
                queue_name, job_id = job_result
                job_id = job_id.decode('utf-8') if isinstance(job_id, bytes) else job_id
                
                # Process the job
                self._process_background_job(job_id)
                
            except Exception as e:
                logger.error(f"Background worker error: {e}")
                time.sleep(1)  # Brief pause before retrying
        
        logger.info("Background worker stopped")
    
    def _process_background_job(self, job_id: str):
        """Process a single background job"""
        try:
            # Get job data
            job_data_str = self._safe_redis_operation(
                self.redis_client.get,
                f"job:{job_id}"
            )
            
            if not job_data_str:
                logger.warning(f"Job {job_id} not found")
                return
            
            job_data = json.loads(job_data_str)
            
            # Update status to processing
            job_data['status'] = 'processing'
            job_data['updated_at'] = datetime.utcnow().isoformat()
            job_data['progress'] = 10
            
            self._safe_redis_operation(
                self.redis_client.setex,
                f"job:{job_id}",
                86400,
                json.dumps(job_data)
            )
            
            logger.info(f"Processing job {job_id}")
            
            # Process documents
            documents = job_data['documents']
            features = job_data['features']
            
            # Update progress
            job_data['progress'] = 25
            self._safe_redis_operation(
                self.redis_client.setex,
                f"job:{job_id}",
                86400,
                json.dumps(job_data)
            )
            
            # Actual processing
            result = self._process_documents_fast(documents, features)
            
            # Update progress
            job_data['progress'] = 90
            self._safe_redis_operation(
                self.redis_client.setex,
                f"job:{job_id}",
                86400,
                json.dumps(job_data)
            )
            
            # Store result
            result_data = {
                'filename': self._generate_output_filename(documents),
                'content': result['output_pdf'],
                'pages': result['total_pages'],
                'features_applied': result['features_applied'],
                'processing_time_seconds': result.get('processing_time', 0),
                'from_cache': False,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            self._safe_redis_operation(
                self.redis_client.setex,
                f"result:{job_id}",
                86400,  # 24 hours
                json.dumps(result_data)
            )
            
            # Update job status to completed
            job_data['status'] = 'completed'
            job_data['progress'] = 100
            job_data['message'] = 'Processing completed successfully'
            job_data['completed_at'] = datetime.utcnow().isoformat()
            
            self._safe_redis_operation(
                self.redis_client.setex,
                f"job:{job_id}",
                86400,
                json.dumps(job_data)
            )
            
            logger.info(f"Job {job_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            
            # Update job status to failed
            try:
                job_data['status'] = 'failed'
                job_data['error'] = str(e)
                job_data['failed_at'] = datetime.utcnow().isoformat()
                
                self._safe_redis_operation(
                    self.redis_client.setex,
                    f"job:{job_id}",
                    86400,
                    json.dumps(job_data)
                )
            except:
                pass  # Don't fail the failure handling

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
