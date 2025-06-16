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
            self.redis_client = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                password=os.getenv('REDIS_PASSWORD'),
                decode_responses=True,  # Automatically decode responses to strings
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e} - Running without cache")
            self.redis_client = None
    
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
        if self.redis_client:
            try:
                cached_result = self.redis_client.get(cache_key)
                
                if cached_result:
                    # CACHE HIT - Ultra fast response (< 10ms)
                    logger.info(f"Cache HIT for {cache_key} - returning instant result")
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
                
            except redis.RedisError as e:
                logger.warning(f"Redis error: {e}")
        
        # CACHE MISS or No Redis - Process documents
        logger.info(f"Cache MISS for {cache_key} - processing documents")
        
        # Sort documents by order
        documents.sort(key=lambda x: x.get('order', 0))
        
        # Process documents with all features applied
        result = self._process_documents_fast(documents, features)
        
        # Cache the result in Redis with 1-hour expiration
        if self.redis_client:
            try:
                cache_data = {
                    'output_pdf': result['output_pdf'],
                    'total_pages': result['total_pages'],
                    'features_applied': result['features_applied'],
                    'processed_at': time.time()
                }
                
                # Store in Redis with 1-hour TTL (3600 seconds)
                self.redis_client.setex(
                    cache_key, 
                    3600,  # 1 hour expiration
                    json.dumps(cache_data)
                )
                
                logger.info(f"Cached result for {cache_key} - expires in 1 hour")
                
            except redis.RedisError as e:
                logger.warning(f"Failed to cache result: {e}")
        
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
                can.setFont("Helvetica", 10)
                can.drawString(letter[0]/2 - 10, 30, str(page_num))
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
        """Optimized 10th line numbering"""
        
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
                text_dict = page.get_text("dict")
                
                line_count = 0
                for block in text_dict["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            line_count += 1
                            
                            if line_count % 10 == 0:
                                line_bbox = line["bbox"]
                                y = (line_bbox[1] + line_bbox[3]) / 2
                                
                                # Right-align the line numbers at the page margin
                                page_rect = page.rect
                                x = page_rect.width - 50  # 50 points from right edge
                                
                                page.insert_text(
                                    (x, y),
                                    str(line_count),
                                    fontsize=8,
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
