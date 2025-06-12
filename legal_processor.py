import json
import io
import base64
from typing import List, Dict, Any, Union, Sequence
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import requests
import time
from datetime import datetime
import uuid
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

class PaystackMpesaProcessor:
    """
    Paystack M-Pesa processor optimized for high-scale instant payments.
    Uses async payment initiation + immediate verification for speed.
    """
    
    def __init__(self):
        self.secret_key = os.getenv('PAYSTACK_SECRET_KEY')
        self.callback_url = os.getenv('PAYSTACK_CALLBACK_URL', 'https://dummy-url.com/webhook')
        
        # Paystack API endpoints
        self.base_url = "https://api.paystack.co"
        self.initialize_url = f"{self.base_url}/transaction/initialize"
        self.verify_url = f"{self.base_url}/transaction/verify"
        
        # Connection pooling for better performance
        self.session = requests.Session()
        self.session.headers.update(self.get_headers())
    
    def get_headers(self) -> Dict[str, str]:
        """Get authorization headers for Paystack API"""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json'
        }
    
    def initiate_payment_fast(self, phone_number: str, amount: int, reference: str) -> Dict[str, Any]:
        """
        Initialize Paystack transaction for M-Pesa payment - RETURNS IMMEDIATELY
        Customer will complete payment via Paystack checkout (includes M-Pesa option)
        """
        try:
            phone_number = self._format_phone_number(phone_number)
            amount_cents = amount * 100
            
            payload = {
                "email": f"customer_{reference}@temp.com",
                "amount": amount_cents,
                "currency": "KES",
                "reference": reference,
                "callback_url": self.callback_url,
                "metadata": {
                    "description": f"Legal Document Processing - {reference}",
                    "phone_number": phone_number,
                    "custom_fields": [
                        {
                            "display_name": "Service",
                            "variable_name": "service",
                            "value": "Legal Document Processing"
                        }
                    ]
                }
            }
            
            response = self.session.post(self.initialize_url, json=payload, timeout=15)
            response.raise_for_status()
            
            init_response = response.json()
            
            if not init_response.get('status'):
                return {
                    'success': False, 
                    'error': init_response.get('message', 'Payment initialization failed')
                }
            
            data = init_response.get('data', {})
            
            # Return checkout URL for customer to complete payment
            return {
                'success': True,
                'reference': reference,
                'payment_url': data.get('authorization_url'),
                'access_code': data.get('access_code'),
                'message': 'Visit payment URL to complete M-Pesa payment.',
                'phone_hint': phone_number[-4:],  # Last 4 digits for confirmation
                'amount': amount
            }
                
        except Exception as e:
            logger.error(f"Payment initialization failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def verify_payment_instant(self, reference: str) -> Dict[str, Any]:
        """
        Single verification call - no polling, returns current status
        """
        try:
            response = self.session.get(f"{self.verify_url}/{reference}", timeout=10)
            response.raise_for_status()
            
            verification_response = response.json()
            
            if not verification_response.get('status'):
                return {
                    'success': False,
                    'error': verification_response.get('message', 'Verification failed'),
                    'payment_status': 'failed'
                }
            
            data = verification_response.get('data', {})
            status = data.get('status')
            
            if status == 'success':
                return {
                    'success': True,
                    'payment_status': 'completed',
                    'transaction_id': data.get('id'),
                    'reference': data.get('reference'),
                    'amount': data.get('amount') / 100,
                    'currency': data.get('currency'),
                    'paid_at': data.get('paid_at'),
                    'channel': data.get('channel')
                }
            elif status in ['failed', 'abandoned', 'cancelled']:
                return {
                    'success': False,
                    'payment_status': 'failed',
                    'error': f"Payment {status}: {data.get('gateway_response', 'Payment not completed')}"
                }
            else:  # pending, ongoing, etc.
                return {
                    'success': False,
                    'payment_status': 'pending',
                    'error': 'Payment still processing'
                }
                
        except Exception as e:
            logger.error(f"Payment verification failed: {e}")
            return {
                'success': False, 
                'error': str(e),
                'payment_status': 'error'
            }
    
    def _format_phone_number(self, phone: str) -> str:
        """Format phone number to 254XXXXXXXXX (Kenyan format for M-Pesa)"""
        phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
        
        if phone.startswith('0'):
            return '254' + phone[1:]
        elif phone.startswith('254'):
            return phone
        else:
            return '254' + phone

class StatelessLegalProcessor:
    """
    Ultra-fast stateless legal document processor with Redis caching
    Four modes: Quote → Preview → Pay → Download (optimized for instant responses)
    """
    
    def __init__(self):
        self.max_workers = min(32, (os.cpu_count() or 1) + 4)
        self.mpesa = PaystackMpesaProcessor()
        self.price_per_page_per_service = 1  # 1 KSH per page per service
        
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
        
    def lambda_handler(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Ultra-fast handler with 4 distinct modes:
        1. quote_only: Calculate pricing (1-2 seconds)
        2. process_preview: Process docs + return preview (0.1-5 seconds) 
        3. initiate_payment: Start payment process (2-3 seconds)
        4. process_with_verification: Verify payment + return full document (0.1-8 seconds)
        """
        try:
            mode = event.get('mode', 'quote_only')
            
            if mode == 'quote_only':
                return self._handle_quote_only(event)
            elif mode == 'process_preview':
                return self._handle_process_preview(event)
            elif mode == 'initiate_payment':
                return self._handle_initiate_payment(event)
            elif mode == 'process_with_verification':
                return self._handle_process_with_verification(event)
            else:
                return self._error_response("Invalid mode. Use: quote_only, process_preview, initiate_payment, or process_with_verification", 400)
                
        except Exception as e:
            logger.error(f"Error in processing: {str(e)}")
            return self._error_response(f"Processing failed: {str(e)}", 500)
    
    def _handle_quote_only(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mode 1: Get pricing quote only (1-2 seconds)"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        
        if not documents:
            return self._error_response("No documents provided", 400)
        
        if not any(features.values()):
            return self._error_response("No features selected", 400)
        
        quote = self._calculate_quote_fast(documents, features)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'mode': 'quote_only',
                'quote': quote,
                'next_step': 'Use mode: process_preview to see preview before payment'
            }),
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
        }

    def _handle_process_preview(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mode 2: Process documents with Redis caching for instant preview (0.1-5 seconds)"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        
        if not documents:
            return self._error_response("No documents provided", 400)
        
        if not any(features.values()):
            return self._error_response("No features selected", 400)
        
        logger.info("Processing documents for preview")
        
        # Generate cache key and preview reference
        cache_key = self._generate_cache_key(documents, features)
        preview_reference = f"PREVIEW_{int(time.time())}_{cache_key[-8:]}"
        
        # Try Redis cache first for instant preview
        if self.redis_client:
            try:
                cached_result = self.redis_client.get(cache_key)
                
                if cached_result:
                    # CACHE HIT - Ultra fast preview response (< 10ms)
                    logger.info(f"Cache HIT for {cache_key} - returning instant preview")
                    # Decode bytes to string if needed
                    if isinstance(cached_result, bytes):
                        cached_result_str = cached_result if isinstance(cached_result, str) else cached_result.decode('utf-8') 
                    cached_data = json.loads(cached_result_str)
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps({
                            'success': True,
                            'mode': 'preview_ready',
                            'preview_reference': preview_reference,
                            'cache_key': cache_key,
                            'processed_document': {
                                'filename': f'preview_{preview_reference}.pdf',
                                'content': cached_data['output_pdf'],
                                'pages': cached_data['total_pages'],
                                'features_applied': cached_data['features_applied'],
                                'processing_time_seconds': 0.01,  # Cache hit time
                                'is_preview': True,
                                'from_cache': True
                            },
                            'next_step': f'Ready for download! Use mode: initiate_payment with preview_reference: {preview_reference}'
                        }),
                        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
                    }
                
            except redis.RedisError as e:
                logger.warning(f"Redis error during preview: {e}")
        
        # CACHE MISS or No Redis - Process documents (3-5 seconds)
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
                'mode': 'preview_ready',
                'preview_reference': preview_reference,
                'cache_key': cache_key,
                'processed_document': {
                    'filename': f'preview_{preview_reference}.pdf',
                    'content': result['output_pdf'],  # Full processed document as preview
                    'pages': result['total_pages'],
                    'features_applied': result['features_applied'],
                    'processing_time_seconds': result.get('processing_time', 0),
                    'is_preview': True,
                    'from_cache': False
                },
                'next_step': f'Ready for download! Use mode: initiate_payment with preview_reference: {preview_reference}'
            }),
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
        }
    
    def _handle_initiate_payment(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mode 3: Initiate payment process (2-3 seconds) - MODIFIED to accept preview_reference"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        phone_number = event.get('phone_number')
        preview_reference = event.get('preview_reference')  # NEW: Link to existing preview
        
        if not phone_number:
            return self._error_response("Phone number required", 400)
        
        # Quick quote calculation (can reuse from preview or recalculate)
        quote = self._calculate_quote_fast(documents, features)
        
        # Generate unique payment reference
        if preview_reference:
            # Link payment to existing preview
            reference = f"PAY_{preview_reference.replace('PREVIEW_', '')}"
        else:
            # Create new reference if no preview was made
            reference = f"LEGAL_{int(time.time())}_{str(uuid.uuid4())[:8]}"
        
        # Initiate payment (returns immediately)
        payment_result = self.mpesa.initiate_payment_fast(
            phone_number, 
            quote['total_cost'], 
            reference
        )
        
        if not payment_result['success']:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'Payment initiation failed',
                    'details': payment_result.get('error'),
                    'quote': quote
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'mode': 'payment_initiated',
                'payment_reference': reference,
                'preview_reference': preview_reference,  # NEW: Maintain preview link
                'payment_url': payment_result.get('payment_url'),
                'access_code': payment_result.get('access_code'),
                'message': payment_result.get('message'),
                'phone_hint': f"***{payment_result.get('phone_hint')}",
                'amount': payment_result.get('amount'),
                'quote': quote,
                'next_step': f'Customer completes payment at URL, then use mode: process_with_verification with reference: {reference}'
            }),
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
        }
    
    def _handle_process_with_verification(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mode 4: Verify payment and return cached document for download (0.1-8 seconds)"""
        documents = event.get('documents', [])
        features = event.get('features', {})
        payment_reference = event.get('payment_reference')
        
        if not payment_reference:
            return self._error_response("Payment reference required", 400)
        
        # Verify payment status instantly
        verification = self.mpesa.verify_payment_instant(payment_reference)
        
        if verification.get('payment_status') == 'pending':
            return {
                'statusCode': 202,  # Accepted but not complete
                'body': json.dumps({
                    'success': False,
                    'payment_status': 'pending',
                    'message': 'Payment still processing. Please try again in a few moments.',
                    'retry_in_seconds': 10
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
        
        if not verification['success']:
            return {
                'statusCode': 402,  # Payment Required
                'body': json.dumps({
                    'success': False,
                    'payment_status': verification.get('payment_status'),
                    'error': 'Payment verification failed - download not authorized',
                    'details': verification.get('error')
                }),
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
            }
        
        # Payment verified - try to get from cache first for instant download
        logger.info(f"Payment verified: {verification.get('transaction_id')} - Preparing download")
        
        cache_key = self._generate_cache_key(documents, features)
        
        # Try Redis cache first for instant download
        if self.redis_client:
            try:
                cached_result = self.redis_client.get(cache_key)
                
                if cached_result:
                    # CACHE HIT - Ultra fast download (< 100ms total)
                    logger.info(f"Payment verified + Cache HIT - instant download ready")
                    # Decode bytes to string if needed
                    if isinstance(cached_result, bytes):
                        cached_result_str = cached_result if isinstance(cached_result, str) else cached_result.decode('utf-8') 
                    cached_data = json.loads(cached_result_str)
                    
                    return {
                        'statusCode': 200,
                        'body': json.dumps({
                            'success': True,
                            'mode': 'download_authorized',
                            'payment_confirmed': True,
                            'transaction_id': verification.get('transaction_id'),
                            'payment_amount': verification.get('amount'),
                            'processed_document': {
                                'filename': f'legal_document_{payment_reference}.pdf',
                                'content': cached_data['output_pdf'],  # Full document for download
                                'pages': cached_data['total_pages'],
                                'features_applied': cached_data['features_applied'],
                                'processing_time_seconds': 0.05,  # Cache retrieval time
                                'is_preview': False,  # This is the final downloadable version
                                'download_authorized': True,
                                'from_cache': True
                            }
                        }),
                        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
                    }
                
            except redis.RedisError as e:
                logger.warning(f"Redis error during download: {e}")
        
        # Cache miss or Redis error - process documents for download (3-8 seconds)
        logger.info(f"Payment verified but cache miss - processing documents for download")
        
        # Sort documents by order
        documents.sort(key=lambda x: x.get('order', 0))
        
        # Process documents (same as preview, but marked as final)
        result = self._process_documents_fast(documents, features)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'mode': 'download_authorized',
                'payment_confirmed': True,
                'transaction_id': verification.get('transaction_id'),
                'payment_amount': verification.get('amount'),
                'processed_document': {
                    'filename': f'legal_document_{payment_reference}.pdf',
                    'content': result['output_pdf'],  # Full document for download
                    'pages': result['total_pages'],
                    'features_applied': result['features_applied'],
                    'processing_time_seconds': result.get('processing_time', 0),
                    'is_preview': False,  # This is the final downloadable version
                    'download_authorized': True,
                    'from_cache': False
                }
            }),
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
        }
    
    def _calculate_quote_fast(self, documents: List[Dict], features: Dict[str, bool]) -> Dict[str, Any]:
        """Ultra-fast quote calculation using parallel processing"""
        
        def count_pages_single(doc):
            try:
                content = base64.b64decode(doc['content'])
                reader = PdfReader(io.BytesIO(content))
                return len(reader.pages)
            except Exception as e:
                logger.error(f"Error reading PDF {doc.get('filename')}: {e}")
                raise ValueError(f"Invalid PDF: {doc.get('filename')}")
        
        # Count pages in parallel for speed
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            page_counts = list(executor.map(count_pages_single, documents))
        
        total_pages = sum(page_counts)
        selected_services = [service for service, enabled in features.items() if enabled]
        service_count = len(selected_services)
        total_cost = total_pages * service_count * self.price_per_page_per_service
        
        return {
            'total_pages': total_pages,
            'document_count': len(documents),
            'selected_services': selected_services,
            'service_count': service_count,
            'cost_per_page_per_service': self.price_per_page_per_service,
            'total_cost': total_cost,
            'currency': 'KSH'
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
                                x = line_bbox[0] - 30
                                y = (line_bbox[1] + line_bbox[3]) / 2
                                
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

# Updated local testing examples for new 4-step flow
if __name__ == "__main__":
    # Step 1: Get quote
    quote_event = {
        "mode": "quote_only",
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
    
    # Step 2: Process for preview (NEW)
    preview_event = {
        "mode": "process_preview",
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
    
    # Step 3: Initiate payment (MODIFIED to include preview_reference)
    payment_event = {
        "mode": "initiate_payment",
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
        },
        "phone_number": "0712345678",
        "preview_reference": "PREVIEW_1234567890_abcd1234"  # NEW: Link to preview
    }
    
    # Step 4: Process with verification for download
    download_event = {
        "mode": "process_with_verification",
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
        },
        "payment_reference": "PAY_1234567890_abcd1234"
    }
    
    print("=== Step 1: Quote Request (1-2 seconds) ===")
    quote_result = lambda_handler(quote_event, None)
    print(json.dumps(quote_result, indent=2))
    
    print("\n=== Step 2: Process for Preview (0.1-5 seconds) ===")
    preview_result = lambda_handler(preview_event, None)
    print(json.dumps(preview_result, indent=2))
    
    print("\n=== Step 3: Payment Initiation (2-3 seconds) ===")
    payment_result = lambda_handler(payment_event, None)
    print(json.dumps(payment_result, indent=2))
    
    print("\n=== Step 4: Process for Download after Payment (0.1-8 seconds) ===")
    download_result = lambda_handler(download_event, None)
    print(json.dumps(download_result, indent=2))
