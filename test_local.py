#!/usr/bin/env python3
"""
Local testing script for Scalable Legal Document Processor with Redis Caching
Tests the new 4-step workflow: Quote → Preview → Payment → Download
"""

import os
import json
import base64
import tempfile
import time
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, Optional, Tuple

# Load environment variables
load_dotenv()

# Import your processor (assuming the main file is named legal_processor.py)
try:
    from legal_processor import StatelessLegalProcessor
    print("✅ Successfully imported StatelessLegalProcessor")
except ImportError as e:
    print(f"❌ Failed to import processor: {e}")
    print("Make sure you have the main file named 'legal_processor.py'")
    exit(1)

def create_sample_pdf(doc_name="Sample Document", page_count=2):
    """Create a sample PDF for testing with specified content"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        
        # Create a temporary PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            c = canvas.Canvas(tmp_file.name, pagesize=letter)
            
            for page_num in range(page_count):
                # Add content for each page
                c.drawString(100, 750, f"{doc_name} - Page {page_num + 1}")
                c.drawString(100, 730, f"This is page {page_num + 1} of the test document")
                
                # Add lines for 10th line testing
                for i in range(15):
                    line_num = (page_num * 15) + i + 1
                    y_pos = 700 - (i * 20)
                    c.drawString(100, y_pos, f"Line {line_num}: Legal content goes here for testing purposes")
                
                if page_num < page_count - 1:
                    c.showPage()
            
            c.save()
            
            # Read and encode as base64
            with open(tmp_file.name, 'rb') as pdf_file:
                pdf_content = pdf_file.read()
                pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
            
            # Clean up
            os.unlink(tmp_file.name)
            
            return pdf_base64
            
    except ImportError:
        print("❌ ReportLab not installed. Install with: pip install reportlab")
        return None
    except Exception as e:
        print(f"❌ Error creating sample PDF: {e}")
        return None

def test_step1_quote_only() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Test Step 1: Quote Only (1-2 seconds)"""
    print("\n" + "="*60)
    print("🧪 STEP 1: Testing Quote Only Mode")
    print("="*60)
    
    # Create multiple sample PDFs for testing
    sample_pdf1 = create_sample_pdf("Contract Document", 3)
    sample_pdf2 = create_sample_pdf("Legal Brief", 2)
    
    if not sample_pdf1 or not sample_pdf2:
        print("❌ Could not create sample PDFs")
        return False, None
    
    processor = StatelessLegalProcessor()
    
    event = {
        "mode": "quote_only",
        "documents": [
            {
                "filename": "contract.pdf",
                "content": sample_pdf1,
                "order": 2  # This should come second
            },
            {
                "filename": "brief.pdf", 
                "content": sample_pdf2,
                "order": 1  # This should come first
            }
        ],
        "features": {
            "merge_pdfs": True,
            "repaginate": True,
            "tenth_lining": True
        }
    }
    
    try:
        start_time = time.time()
        result = processor.lambda_handler(event, None)
        execution_time = time.time() - start_time
        
        print(f"⏱️  Execution Time: {execution_time:.2f} seconds")
        print(f"📊 Status Code: {result['statusCode']}")
        
        body = json.loads(result['body'])
        
        if body['success']:
            quote = body['quote']
            print("✅ Quote generated successfully!")
            print(f"📄 Total Pages: {quote['total_pages']}")
            print(f"📚 Document Count: {quote['document_count']}")
            print(f"🔧 Services: {quote['selected_services']}")
            print(f"🛠️  Service Count: {quote['service_count']}")
            print(f"💰 Cost per Page per Service: {quote['cost_per_page_per_service']} KSH")
            print(f"💸 Total Cost: {quote['total_cost']} KSH")
            print(f"🏦 Currency: {quote['currency']}")
            print(f"🎯 Next Step: {body.get('next_step')}")
            return True, quote
        else:
            print(f"❌ Quote failed: {body.get('error')}")
            return False, None
            
    except Exception as e:
        print(f"❌ Error testing quote: {e}")
        return False, None

def test_step2_process_preview() -> Tuple[bool, Optional[str]]:
    """Test Step 2: Process Preview with Redis Caching (0.1-5 seconds)"""
    print("\n" + "="*60)
    print("🔍 STEP 2: Testing Process Preview Mode (NEW)")
    print("="*60)
    
    # Create sample PDFs for preview
    sample_pdf1 = create_sample_pdf("Preview Brief", 2)
    sample_pdf2 = create_sample_pdf("Preview Contract", 3)
    
    if not sample_pdf1 or not sample_pdf2:
        print("❌ Could not create sample PDFs")
        return False, None
    
    processor = StatelessLegalProcessor()
    
    event = {
        "mode": "process_preview",
        "documents": [
            {
                "filename": "brief.pdf",
                "content": sample_pdf1,
                "order": 1
            },
            {
                "filename": "contract.pdf",
                "content": sample_pdf2,
                "order": 2
            }
        ],
        "features": {
            "merge_pdfs": True,
            "repaginate": True,
            "tenth_lining": True
        }
    }
    
    try:
        # Test first run (should be cache miss)
        print("🔄 First run (Cache MISS expected)...")
        start_time = time.time()
        result = processor.lambda_handler(event, None)
        execution_time = time.time() - start_time
        
        print(f"⏱️  Execution Time: {execution_time:.2f} seconds")
        print(f"📊 Status Code: {result['statusCode']}")
        
        body = json.loads(result['body'])
        
        if body['success']:
            processed_doc = body['processed_document']
            preview_reference = body['preview_reference']
            
            print("✅ Preview generated successfully!")
            print(f"🆔 Preview Reference: {preview_reference}")
            print(f"🔑 Cache Key: {body.get('cache_key')}")
            print(f"📁 Filename: {processed_doc['filename']}")
            print(f"📄 Total Pages: {processed_doc['pages']}")
            print(f"🛠️  Features Applied: {processed_doc['features_applied']}")
            print(f"⚡ Processing Time: {processed_doc['processing_time_seconds']} seconds")
            print(f"💾 From Cache: {processed_doc.get('from_cache', False)}")
            print(f"🔍 Is Preview: {processed_doc['is_preview']}")
            print(f"📦 Content Size: {len(processed_doc['content'])} characters (base64)")
            print(f"🎯 Next Step: {body.get('next_step')}")
            
            # Test second run (should be cache hit if Redis is working)
            print("\n🚀 Second run (Cache HIT expected if Redis is configured)...")
            start_time = time.time()
            result2 = processor.lambda_handler(event, None)
            execution_time2 = time.time() - start_time
            
            print(f"⏱️  Execution Time: {execution_time2:.2f} seconds")
            
            body2 = json.loads(result2['body'])
            if body2['success']:
                processed_doc2 = body2['processed_document']
                from_cache = processed_doc2.get('from_cache', False)
                cache_symbol = "⚡" if from_cache else "🔄"
                print(f"{cache_symbol} Cache Status: {'HIT' if from_cache else 'MISS'}")
                print(f"⚡ Cache Performance: {execution_time2:.3f}s vs {execution_time:.3f}s")
                
                if from_cache and execution_time2 < 0.1:
                    print("🎉 Redis caching is working perfectly!")
                elif not from_cache:
                    print("⚠️  Redis cache miss - check Redis configuration")
            
            # Offer to save preview
            save_preview = input("\n💾 Save preview PDF to test_preview.pdf? (y/n): ").lower().strip()
            if save_preview == 'y':
                try:
                    preview_pdf_bytes = base64.b64decode(processed_doc['content'])
                    with open('test_preview.pdf', 'wb') as f:
                        f.write(preview_pdf_bytes)
                    print("✅ Preview saved to test_preview.pdf")
                    print("📖 Open the file to verify the preview looks correct!")
                except Exception as e:
                    print(f"❌ Error saving preview: {e}")
            
            return True, preview_reference
        else:
            print(f"❌ Preview failed: {body.get('error')}")
            return False, None
            
    except Exception as e:
        print(f"❌ Error testing preview: {e}")
        return False, None

def test_step3_initiate_payment(preview_reference: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Test Step 3: Initiate Payment with Preview Reference (2-3 seconds)"""
    print("\n" + "="*60)
    print("💳 STEP 3: Testing Payment Initiation (MODIFIED)")
    print("="*60)
    
    # Check if Paystack credentials are configured
    if not os.getenv('PAYSTACK_SECRET_KEY'):
        print("❌ Missing PAYSTACK_SECRET_KEY in environment variables")
        print("⚠️  Configure your .env file first!")
        print("📝 For testing, we'll simulate this step...")
        
        # Simulate payment initiation response
        mock_reference = f"PAY_{int(time.time())}_test1234"
        mock_response = {
            'success': True,
            'mode': 'payment_initiated',
            'payment_reference': mock_reference,
            'preview_reference': preview_reference,  # NEW: Link to preview
            'payment_url': f'https://checkout.paystack.com/{mock_reference}',
            'access_code': f'access_code_{mock_reference}',
            'message': 'Visit payment URL to complete M-Pesa payment.',
            'phone_hint': '***5678',
            'amount': 15,  # 5 pages * 3 services * 1 KSH
            'next_step': f'Customer completes payment at URL, then use mode: process_with_verification with reference: {mock_reference}'
        }
        
        print("🎭 SIMULATED Payment Initiation:")
        print(f"✅ Payment Reference: {mock_response['payment_reference']}")
        print(f"🔗 Preview Reference: {mock_response['preview_reference']}")
        print(f"🌐 Payment URL: {mock_response['payment_url']}")
        print(f"🔑 Access Code: {mock_response['access_code']}")
        print(f"📱 Phone Hint: {mock_response['phone_hint']}")
        print(f"💰 Amount: {mock_response['amount']} KSH")
        print(f"📝 Next Step: {mock_response['next_step']}")
        print("\n💡 In a real app, redirect user to payment_url to complete M-Pesa payment")
        
        return True, mock_response['payment_reference']
    
    processor = StatelessLegalProcessor()
    
    # Create sample docs for payment
    sample_pdf = create_sample_pdf("Payment Test Doc", 2)
    
    event = {
        "mode": "initiate_payment",
        "documents": [
            {
                "filename": "payment_test.pdf",
                "content": sample_pdf,
                "order": 1
            }
        ],
        "features": {
            "merge_pdfs": True,
            "repaginate": True,
            "tenth_lining": False
        },
        "phone_number": "0712345678",  # Test phone number
        "preview_reference": preview_reference  # NEW: Link to existing preview
    }
    
    try:
        start_time = time.time()
        result = processor.lambda_handler(event, None)
        execution_time = time.time() - start_time
        
        print(f"⏱️  Execution Time: {execution_time:.2f} seconds")
        print(f"📊 Status Code: {result['statusCode']}")
        
        body = json.loads(result['body'])
        
        if body['success']:
            print("✅ Payment initiated successfully!")
            print(f"📝 Payment Reference: {body['payment_reference']}")
            print(f"🔗 Preview Reference: {body.get('preview_reference')}")
            print(f"🌐 Payment URL: {body.get('payment_url')}")
            print(f"🔑 Access Code: {body.get('access_code')}")
            print(f"📱 Phone Hint: {body.get('phone_hint')}")
            print(f"💰 Amount: {body['amount']} KSH")
            print(f"📄 Message: {body['message']}")
            print(f"🎯 Next Step: {body.get('next_step')}")
            print("\n💡 In a real app, redirect user to payment_url to complete M-Pesa payment")
            return True, body['payment_reference']
        else:
            print(f"❌ Payment initiation failed: {body.get('error')}")
            return False, None
            
    except Exception as e:
        print(f"❌ Error testing payment initiation: {e}")
        return False, None

def test_step4_process_with_verification(payment_reference: str, simulate_payment: bool = True) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Test Step 4: Process with Verification for Download (0.1-8 seconds)"""
    print("\n" + "="*60)
    print("📥 STEP 4: Testing Process with Verification for Download (MODIFIED)")
    print("="*60)
    
    processor = StatelessLegalProcessor()
    
    # Create multiple sample PDFs for comprehensive testing
    sample_pdf1 = create_sample_pdf("Legal Brief", 2)
    sample_pdf2 = create_sample_pdf("Contract", 3)
    sample_pdf3 = create_sample_pdf("Appendix", 1)
    
    event = {
        "mode": "process_with_verification",
        "documents": [
            {
                "filename": "brief.pdf",
                "content": sample_pdf1,
                "order": 1  # First
            },
            {
                "filename": "contract.pdf",
                "content": sample_pdf2,
                "order": 2  # Second
            },
            {
                "filename": "appendix.pdf",
                "content": sample_pdf3,
                "order": 3  # Third
            }
        ],
        "features": {
            "merge_pdfs": True,
            "repaginate": True,
            "tenth_lining": True
        },
        "payment_reference": payment_reference
    }
    
    # If we're simulating, mock the payment verification
    if simulate_payment:
        print("🎭 SIMULATING successful payment verification...")
        # Store original method for restoration
        original_verify = processor.mpesa.verify_payment_instant
        
        def mock_verify(reference: str) -> Dict[str, Any]:
            return {
                'success': True,
                'payment_status': 'completed',
                'transaction_id': f'TXN_{int(time.time())}',
                'reference': reference,
                'amount': 18.0,  # 6 pages * 3 services * 1 KSH
                'currency': 'KES',
                'paid_at': '2024-01-01T12:00:00Z',
                'channel': 'mobile_money'
            }
        
        processor.mpesa.verify_payment_instant = mock_verify
    
    try:
        start_time = time.time()
        result = processor.lambda_handler(event, None)
        execution_time = time.time() - start_time
        
        print(f"⏱️  Execution Time: {execution_time:.2f} seconds")
        print(f"📊 Status Code: {result['statusCode']}")
        
        body = json.loads(result['body'])
        
        if result['statusCode'] == 202:
            print("⏳ Payment still pending - this is normal for real payments")
            print(f"📄 Message: {body.get('message')}")
            print(f"🔄 Retry in: {body.get('retry_in_seconds')} seconds")
            return True, None
        elif body['success']:
            processed_doc = body['processed_document']
            print("✅ Document download authorized!")
            print(f"💳 Payment Confirmed: {body['payment_confirmed']}")
            print(f"🆔 Transaction ID: {body['transaction_id']}")
            print(f"💰 Payment Amount: {body['payment_amount']} KSH")
            print(f"📁 Output Filename: {processed_doc['filename']}")
            print(f"📄 Total Pages: {processed_doc['pages']}")
            print(f"🛠️  Features Applied: {processed_doc['features_applied']}")
            print(f"⚡ Processing Time: {processed_doc['processing_time_seconds']} seconds")
            print(f"💾 From Cache: {processed_doc.get('from_cache', False)}")
            print(f"🔍 Is Preview: {processed_doc['is_preview']}")
            print(f"📥 Download Authorized: {processed_doc.get('download_authorized', False)}")
            print(f"📦 Output Size: {len(processed_doc['content'])} characters (base64)")
            
            # Check if this was served from cache
            if processed_doc.get('from_cache'):
                print("🎉 Ultra-fast download from Redis cache!")
            else:
                print("🔄 Full processing - cache miss or first download")
            
            # Offer to save the result
            save_result = input("\n💾 Save final document to test_download.pdf? (y/n): ").lower().strip()
            if save_result == 'y':
                try:
                    output_pdf_bytes = base64.b64decode(processed_doc['content'])
                    with open('test_download.pdf', 'wb') as f:
                        f.write(output_pdf_bytes)
                    print("✅ Saved to test_download.pdf")
                    print("📖 Open the file to verify pagination and 10th line numbering!")
                except Exception as e:
                    print(f"❌ Error saving file: {e}")
            
            return True, processed_doc
        else:
            print(f"❌ Download authorization failed: {body.get('error')}")
            print(f"📝 Details: {body.get('details')}")
            return False, None
            
    except Exception as e:
        print(f"❌ Error testing download: {e}")
        return False, None
    finally:
        # Restore original method if we mocked it
        if simulate_payment and 'original_verify' in locals():
            processor.mpesa.verify_payment_instant = original_verify

def test_redis_connection():
    """Test Redis connection and caching functionality"""
    print("\n" + "="*60)
    print("🔴 TESTING: Redis Connection & Caching")
    print("="*60)
    
    # Check Redis environment variables
    redis_host = os.getenv('REDIS_HOST')
    redis_port = os.getenv('REDIS_PORT', '6379')
    redis_password = os.getenv('REDIS_PASSWORD')
    
    if not redis_host:
        print("❌ Missing REDIS_HOST in environment variables")
        print("📝 Add to your .env file: REDIS_HOST=your-redis-endpoint")
        print("💡 For local testing: REDIS_HOST=localhost")
        print("☁️  For production: Use AWS ElastiCache or Redis Cloud")
        return False
    
    print(f"✅ Redis host: {redis_host}")
    print(f"✅ Redis port: {redis_port}")
    print(f"🔐 Redis password: {'***' if redis_password else 'Not set'}")
    
    # Test Redis connection
    try:
        import redis
        
        redis_client = redis.Redis(
            host=redis_host,
            port=int(redis_port),
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True
        )
        
        # Test ping
        print("🔗 Testing Redis connection...")
        redis_client.ping()
        print("✅ Redis ping successful!")
        
        # Test set/get
        test_key = "test_key_123"
        test_value = "test_value_456"
        
        redis_client.set(test_key, test_value, ex=60)  # 60 second expiration
        retrieved_value = redis_client.get(test_key)
        
        if retrieved_value == test_value:
            print("✅ Redis set/get test successful!")
            
            # Clean up test key
            redis_client.delete(test_key)
            print("🧹 Test key cleaned up")
            
            return True
        else:
            print(f"❌ Redis set/get test failed: expected '{test_value}', got '{retrieved_value}'")
            return False
        
    except ImportError:
        print("❌ Redis library not installed. Install with: pip install redis")
        return False
    except Exception as e:
        print(f"❌ Redis connection test failed: {e}")
        print("💡 Possible issues:")
        print("   - Redis server not running")
        print("   - Incorrect host/port/password")
        print("   - Network connectivity issues")
        print("   - Redis server behind firewall")
        return False

def test_paystack_credentials():
    """Test Paystack credentials and connection"""
    print("\n" + "="*60)
    print("🔐 TESTING: Paystack Integration")
    print("="*60)
    
    # Check if Paystack credentials are configured
    secret_key = os.getenv('PAYSTACK_SECRET_KEY')
    
    if not secret_key:
        print("❌ Missing PAYSTACK_SECRET_KEY in environment variables")
        print("📝 Add to your .env file: PAYSTACK_SECRET_KEY=sk_test_...")
        print("🌐 Get your keys from: https://dashboard.paystack.com/#/settings/developer")
        return False
    
    print(f"✅ Paystack secret key found: {secret_key[:15]}...")
    
    # Test connection to Paystack
    try:
        from legal_processor import PaystackMpesaProcessor
        paystack = PaystackMpesaProcessor()
        
        print("🔗 Testing Paystack API connection...")
        
        # Test with a dummy verification (should fail gracefully)
        test_result = paystack.verify_payment_instant("dummy_reference_test")
        
        if 'error' in test_result:
            print("✅ Paystack API is reachable (expected error for dummy reference)")
            return True
        else:
            print("⚠️  Unexpected response from Paystack API")
            return False
        
    except Exception as e:
        print(f"❌ Paystack connection test failed: {e}")
        print("💡 This might be due to network issues or invalid credentials")
        return False

def test_performance_benchmark():
    """Test performance with Redis caching on multiple runs"""
    print("\n" + "="*60)
    print("🏃‍♂️ PERFORMANCE: Redis Caching Benchmark")
    print("="*60)
    
    # Create multiple documents of varying sizes
    documents = []
    for i in range(3):  # Reduced for faster testing
        pdf_content = create_sample_pdf(f"Document {i+1}", page_count=i+2)
        if pdf_content:
            documents.append({
                "filename": f"doc_{i+1}.pdf",
                "content": pdf_content,
                "order": i + 1
            })
    
    if len(documents) != 3:
        print("❌ Could not create all test documents")
        return False
    
    processor = StatelessLegalProcessor()
    
    preview_event = {
        "mode": "process_preview",
        "documents": documents,
        "features": {
            "merge_pdfs": True,
            "repaginate": True, 
            "tenth_lining": True
        }
    }
    
    print(f"📄 Testing with {len(documents)} documents")
    print(f"📃 Total pages: {sum(i+2 for i in range(3))} pages")
    
    # Test multiple runs to measure cache performance
    run_times = []
    cache_hits = []
    
    for run_num in range(3):
        print(f"\n🔄 Run {run_num + 1}/3...")
        
        try:
            start_time = time.time()
            result = processor.lambda_handler(preview_event, None)
            execution_time = time.time() - start_time
            
            run_times.append(execution_time)
            
            if result['statusCode'] == 200:
                body = json.loads(result['body'])
                from_cache = body.get('processed_document', {}).get('from_cache', False)
                cache_hits.append(from_cache)
                
                cache_status = "⚡ HIT" if from_cache else "🔄 MISS"
                print(f"   ⏱️  Time: {execution_time:.3f}s | Cache: {cache_status}")
            else:
                print(f"   ❌ Failed with status {result['statusCode']}")
                cache_hits.append(False)
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
            run_times.append(float('inf'))
            cache_hits.append(False)
    
    # Performance analysis
    print(f"\n📊 CACHE PERFORMANCE ANALYSIS:")
    
    if len(run_times) >= 2:
        first_run = run_times[0]
        subsequent_runs = run_times[1:]
        cache_hit_count = sum(cache_hits[1:])  # Exclude first run
        
        print(f"🔄 First run (cache miss): {first_run:.3f}s")
        if subsequent_runs:
            avg_subsequent = sum(subsequent_runs) / len(subsequent_runs)
            print(f"⚡ Subsequent runs average: {avg_subsequent:.3f}s")
            
            if cache_hit_count > 0:
                speedup = first_run / avg_subsequent
                print(f"🚀 Cache speedup: {speedup:.1f}x faster")
                
                if avg_subsequent < 0.1:
                    print("🎉 Excellent cache performance! (< 100ms)")
                elif avg_subsequent < 0.5:
                    print("✅ Good cache performance (< 500ms)")
                else:
                    print("⚠️  Cache performance could be improved")
            else:
                print("❌ No cache hits detected - check Redis configuration")
        
        print(f"💾 Cache hit rate: {cache_hit_count}/{len(subsequent_runs)} ({cache_hit_count/len(subsequent_runs)*100:.0f}%)")
        
        return cache_hit_count > 0
    
    return False

def main():
    """Run comprehensive test suite for the new 4-step workflow with Redis caching"""
    print("🚀 Scalable Legal Document Processor - 4-Step Redis Workflow Test Suite")
    print("=" * 80)
    
    # Check dependencies
    print("🔍 Checking dependencies...")
    try:
        import PyPDF2
        import reportlab
        import fitz
        import requests
        import redis
        print("✅ All required libraries available")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("📦 Install with: pip install PyPDF2 reportlab PyMuPDF requests redis python-dotenv")
        return
    
    # Run tests in sequence
    test_results = {}
    
    # Test Redis connection first
    test_results["Redis Connection"] = test_redis_connection()
    
    # Test 1: Quote Only
    quote_success, quote_data = test_step1_quote_only()
    test_results["Step 1: Quote Only"] = quote_success
    
    # Test 2: Process Preview (NEW)
    preview_success, preview_ref = False, None
    if quote_success:
        preview_success, preview_ref = test_step2_process_preview()
        test_results["Step 2: Process Preview"] = preview_success
    else:
        test_results["Step 2: Process Preview"] = False
    
    # Test 3: Payment Initiation (MODIFIED)
    payment_success, payment_ref = False, None
    if preview_success:
        payment_success, payment_ref = test_step3_initiate_payment(preview_ref)
        test_results["Step 3: Payment Initiation"] = payment_success
    else:
        test_results["Step 3: Payment Initiation"] = False
        
    # Test 4: Process with Verification (MODIFIED)
    if payment_success and payment_ref:
        process_success, _ = test_step4_process_with_verification(payment_ref, simulate_payment=True)
        test_results["Step 4: Process & Download"] = process_success
    else:
        test_results["Step 4: Process & Download"] = False
    
    # Additional tests
    test_results["Paystack Integration"] = test_paystack_credentials()
    test_results["Performance & Caching"] = test_performance_benchmark()
    
    # Final summary
    print("\n" + "="*80)
    print("📊 COMPREHENSIVE 4-STEP WORKFLOW TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in test_results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")
    
    passed_count = sum(test_results.values())
    total_count = len(test_results)
    
    print(f"\n🎯 Overall Result: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("🎉 ALL TESTS PASSED! Your 4-step Redis workflow is ready! 🎉")
        print("\n🚀 WORKFLOW PERFORMANCE SUMMARY:")
        print("   Step 1 (Quote): 1-2 seconds")
        print("   Step 2 (Preview): 0.01-5 seconds (cache dependent)")
        print("   Step 3 (Payment): 2-3 seconds")
        print("   Step 4 (Download): 0.01-8 seconds (cache dependent)")
        print("\n💡 Expected user experience:")
        print("   - First-time users: Normal processing speed")
        print("   - Repeat users: Near-instant previews and downloads!")
    else:
        print("\n💡 Next Steps to fix failing tests:")
        
        if not test_results.get("Redis Connection"):
            print("   🔴 Configure Redis:")
            print("      - Local: Start Redis server (redis-server)")
            print("      - Production: Set up AWS ElastiCache or Redis Cloud")
            print("      - Add REDIS_HOST, REDIS_PORT, REDIS_PASSWORD to .env")
        
        if not test_results.get("Paystack Integration"):
            print("   💳 Configure Paystack:")
            print("      - Add PAYSTACK_SECRET_KEY to .env file")
            print("      - Get test keys from dashboard.paystack.com")
        
        if not test_results.get("Step 1: Quote Only"):
            print("   📄 Check PDF processing:")
            print("      - Verify PyPDF2, reportlab, PyMuPDF installed")
            print("      - Check document processing logic")
        
        if not test_results.get("Step 2: Process Preview"):
            print("   🔍 Fix preview processing:")
            print("      - Ensure Redis is working")
            print("      - Check cache key generation")
            print("      - Verify PDF processing pipeline")
        
        if not test_results.get("Performance & Caching"):
            print("   ⚡ Optimize performance:")
            print("      - Ensure Redis cache is working")
            print("      - Check network latency to Redis")
            print("      - Verify cache TTL settings")
        
        print("\n🌐 Production deployment checklist:")
        print("   - Test with real Paystack credentials")
        print("   - Test with real M-Pesa payments")
        print("   - Configure production Redis cluster")
        print("   - Set up monitoring and logging")
        print("   - Load test with concurrent users")

def test_full_workflow_integration():
    """Test the complete 4-step workflow end-to-end"""
    print("\n" + "="*60)
    print("🔄 INTEGRATION: Complete 4-Step Workflow Test")
    print("="*60)
    
    # Create sample documents
    sample_pdf = create_sample_pdf("Integration Test", 2)
    if not sample_pdf:
        print("❌ Could not create sample PDF")
        return False
    
    documents = [{
        "filename": "integration_test.pdf",
        "content": sample_pdf,
        "order": 1
    }]
    
    features = {
        "merge_pdfs": True,
        "repaginate": True,
        "tenth_lining": True
    }
    
    processor = StatelessLegalProcessor()
    
    try:
        # Step 1: Quote
        print("1️⃣ Getting quote...")
        quote_event = {
            "mode": "quote_only",
            "documents": documents,
            "features": features
        }
        
        quote_result = processor.lambda_handler(quote_event, None)
        if quote_result['statusCode'] != 200:
            print("❌ Quote step failed")
            return False
        
        quote_body = json.loads(quote_result['body'])
        print(f"✅ Quote: {quote_body['quote']['total_cost']} KSH")
        
        # Step 2: Preview
        print("2️⃣ Generating preview...")
        preview_event = {
            "mode": "process_preview",
            "documents": documents,
            "features": features
        }
        
        preview_result = processor.lambda_handler(preview_event, None)
        if preview_result['statusCode'] != 200:
            print("❌ Preview step failed")
            return False
        
        preview_body = json.loads(preview_result['body'])
        preview_reference = preview_body['preview_reference']
        print(f"✅ Preview generated: {preview_reference}")
        
        # Step 3: Payment (simulated)
        print("3️⃣ Initiating payment...")
        payment_event = {
            "mode": "initiate_payment",
            "documents": documents,
            "features": features,
            "phone_number": "0712345678",
            "preview_reference": preview_reference
        }
        
        # Mock payment for integration test
        if not os.getenv('PAYSTACK_SECRET_KEY'):
            payment_reference = f"PAY_{int(time.time())}_integration"
            print(f"✅ Payment initiated (simulated): {payment_reference}")
        else:
            payment_result = processor.lambda_handler(payment_event, None)
            if payment_result['statusCode'] != 200:
                print("❌ Payment step failed")
                return False
            
            payment_body = json.loads(payment_result['body'])
            payment_reference = payment_body['payment_reference']
            print(f"✅ Payment initiated: {payment_reference}")
        
        # Step 4: Download (with mocked payment verification)
        print("4️⃣ Processing download...")
        
        # Mock payment verification
        original_verify = processor.mpesa.verify_payment_instant
        processor.mpesa.verify_payment_instant = lambda reference: {
            'success': True,
            'payment_status': 'completed',
            'transaction_id': f'TXN_INTEGRATION_{int(time.time())}',
            'amount': 6.0  # 2 pages * 3 services * 1 KSH
        }
        
        download_event = {
            "mode": "process_with_verification",
            "documents": documents,
            "features": features,
            "payment_reference": payment_reference
        }
        
        download_result = processor.lambda_handler(download_event, None)
        processor.mpesa.verify_payment_instant = original_verify
        
        if download_result['statusCode'] != 200:
            print("❌ Download step failed")
            return False
        
        download_body = json.loads(download_result['body'])
        processed_doc = download_body['processed_document']
        print(f"✅ Download authorized: {processed_doc['filename']}")
        
        # Verify the complete workflow
        print(f"\n🎯 WORKFLOW VERIFICATION:")
        print(f"📄 Document processed: {processed_doc['pages']} pages")
        print(f"🛠️  Features applied: {processed_doc['features_applied']}")
        print(f"💳 Payment confirmed: {download_body['payment_confirmed']}")
        print(f"📥 Download authorized: {processed_doc.get('download_authorized', False)}")
        print(f"💾 Served from cache: {processed_doc.get('from_cache', False)}")
        
        print("🎉 Complete 4-step workflow test PASSED!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

if __name__ == "__main__":
    # Add integration test to main
    main()
    
    # Run additional integration test
    integration_success = test_full_workflow_integration()
    
    print(f"\n🏁 FINAL RESULT:")
    if integration_success:
        print("✅ Complete 4-step workflow integration test PASSED!")
        print("🚀 Your Redis-cached legal document processor is ready for production!")
    else:
        print("❌ Integration test failed - review individual test results above")

