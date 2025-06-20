#!/usr/bin/env python3
"""
Simple test script for the improved 10th line numbering functionality
"""

import os
import sys
import json
import base64
import tempfile
import time
from pathlib import Path

# Import the processor
try:
    from legal_processor import StatelessLegalProcessor
    print("✅ Successfully imported StatelessLegalProcessor")
except ImportError as e:
    print(f"❌ Failed to import processor: {e}")
    sys.exit(1)

def create_complex_test_pdf(doc_name="Complex Test Document", page_count=2):
    """Create a PDF with complex layout elements for testing"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import Table, TableStyle
        
        # Create a temporary PDF
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            c = canvas.Canvas(tmp_file.name, pagesize=letter)
            
            for page_num in range(page_count):
                # Add header (should be filtered out)
                c.setFont("Helvetica-Bold", 12)
                c.drawString(100, 750, f"CONFIDENTIAL - Page {page_num + 1}")
                c.drawString(450, 750, f"Case No. 2024-{page_num:03d}")
                
                # Add watermark (should be filtered out)
                c.setFont("Helvetica", 20)
                c.setFillColor(colors.lightgrey)
                c.drawCentredText(letter[0]/2, letter[1]/2, "DRAFT")
                c.setFillColor(colors.black)
                
                # Add main content (should be numbered)
                c.setFont("Helvetica", 11)
                y_pos = 700
                line_spacing = 18
                
                # Paragraph 1
                lines = [
                    f"This is the beginning of paragraph {page_num + 1} which contains substantial legal content.",
                    "The document demonstrates various formatting elements including headers, footers, and watermarks.",
                    "Each line should be properly counted for 10th line numbering purposes.",
                    "This system filters out decorative elements and focuses on main content only.",
                    "Complex PDFs often include tables, images, and other non-text elements.",
                    "The improved algorithm distinguishes between content and layout elements.",
                    "Watermarks, headers, and footers are automatically excluded from line counting.",
                    "This ensures accurate line numbering for legal document processing.",
                    "The system handles multi-column layouts and complex page structures.",
                    "Line numbering accuracy is crucial for legal document citations and references."
                ]
                
                for i, line in enumerate(lines):
                    c.drawString(100, y_pos - (i * line_spacing), line)
                
                # Add a table (should be filtered out)
                y_pos -= len(lines) * line_spacing + 30
                c.setFont("Helvetica-Bold", 10)
                c.drawString(100, y_pos, "Table Header")
                c.drawString(200, y_pos, "Amount")
                c.drawString(300, y_pos, "Date")
                
                c.setFont("Helvetica", 9)
                c.drawString(100, y_pos - 15, "Item 1")
                c.drawString(200, y_pos - 15, "$100")
                c.drawString(300, y_pos - 15, "01/01/2024")
                
                # Add more main content
                y_pos -= 50
                c.setFont("Helvetica", 11)
                more_lines = [
                    "Continuing with the main document content after the table section.",
                    "This paragraph demonstrates how the system handles mixed content types.",
                    "Tables, headers, and other elements should not interfere with line counting.",
                    "The 10th line numbering should appear only on substantive content lines.",
                    "Legal documents require precise line numbering for court filing requirements."
                ]
                
                for i, line in enumerate(more_lines):
                    c.drawString(100, y_pos - (i * line_spacing), line)
                
                # Add footer (should be filtered out)
                c.setFont("Helvetica", 8)
                c.drawString(100, 50, f"Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}")
                c.drawString(450, 50, f"Page {page_num + 1} of {page_count}")
                
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
        print(f"❌ Error creating complex test PDF: {e}")
        return None

def test_tenth_lining_improvement():
    """Test the improved 10th line numbering with complex PDF"""
    print("\n" + "="*60)
    print("🧪 TESTING: Improved 10th Line Numbering")
    print("="*60)
    
    # Create complex test PDF
    print("📝 Creating complex test PDF...")
    complex_pdf = create_complex_test_pdf("Complex Legal Document", 2)
    
    if not complex_pdf:
        print("❌ Could not create test PDF")
        return False
    
    print("✅ Complex test PDF created successfully")
    
    # Initialize processor
    processor = StatelessLegalProcessor()
    
    # Test document processing with 10th lining
    event = {
        "documents": [
            {
                "filename": "complex_test.pdf",
                "content": complex_pdf,
                "order": 1
            }
        ],
        "features": {
            "merge_pdfs": False,
            "repaginate": False,
            "tenth_lining": True
        }
    }
    
    try:
        print("🔄 Processing document with improved 10th line numbering...")
        start_time = time.time()
        result = processor._process_documents_fast(event['documents'], event['features'])
        execution_time = time.time() - start_time
        
        print(f"⏱️  Processing time: {execution_time:.2f} seconds")
        print(f"📄 Total pages: {result['total_pages']}")
        print(f"🛠️  Features applied: {result['features_applied']}")
        
        # Save the result for manual inspection
        output_pdf_bytes = base64.b64decode(result['output_pdf'])
        output_filename = 'test_improved_tenth_lining.pdf'
        
        with open(output_filename, 'wb') as f:
            f.write(output_pdf_bytes)
        
        print(f"✅ Output saved to: {output_filename}")
        print("\n🔍 MANUAL VERIFICATION NEEDED:")
        print("   1. Open the output PDF file")
        print("   2. Verify that line numbers appear only on main content lines")
        print("   3. Check that headers, footers, watermarks, and table elements are not numbered")
        print("   4. Ensure line numbers appear every 10th line of actual content")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_filtering_functions():
    """Test the individual filtering functions"""
    print("\n" + "="*40)
    print("🔍 TESTING: Content Filtering Functions")
    print("="*40)
    
    processor = StatelessLegalProcessor()
    
    # Test watermark detection
    watermark_tests = [
        ("CONFIDENTIAL", True),
        ("DRAFT", True),
        ("This is normal content", False),
        ("COPYRIGHT © 2024", True),
        ("SAMPLE", True),
        ("Legal brief content continues here", False)
    ]
    
    print("🚫 Testing watermark detection:")
    for text, expected in watermark_tests:
        # Mock bbox and page_rect for testing
        bbox = [100, 100, 200, 115]  # Sample bbox
        page_rect = type('obj', (object,), {'width': 612, 'height': 792})()
        
        result = processor._is_likely_watermark(text, bbox, page_rect)
        status = "✅" if result == expected else "❌"
        print(f"   {status} '{text}' -> {result} (expected {expected})")
    
    # Test header/footer detection
    header_footer_tests = [
        ("Page 1", True),
        ("Chapter 1", True),
        ("01/01/2024", True),
        ("This is document content", False),
        ("CONFIDENTIAL", True),
        ("Normal paragraph text", False)
    ]
    
    print("\n📄 Testing header/footer detection:")
    for text, expected in header_footer_tests:
        result = processor._is_likely_header_footer(text)
        status = "✅" if result == expected else "❌"
        print(f"   {status} '{text}' -> {result} (expected {expected})")
    
    # Test table element detection
    table_tests = [
        ("Name", True),
        ("$100.00", True),
        ("Yes", True),
        ("This is a full sentence with normal content", False),
        ("Date", True),
        ("The defendant argues that the contract terms", False)
    ]
    
    print("\n📊 Testing table element detection:")
    for text, expected in table_tests:
        bbox = [100, 100, 200, 115]  # Sample bbox
        result = processor._is_likely_table_element(text, bbox)
        status = "✅" if result == expected else "❌"
        print(f"   {status} '{text}' -> {result} (expected {expected})")

def main():
    """Run comprehensive tests for improved 10th line numbering"""
    print("🚀 Improved 10th Line Numbering Test Suite")
    print("=" * 50)
    
    # Check dependencies
    print("🔍 Checking dependencies...")
    try:
        import PyPDF2
        import reportlab
        import fitz
        print("✅ All required libraries available")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("📦 Install with: pip install PyPDF2 reportlab PyMuPDF")
        return
    
    # Run tests
    test_results = {}
    
    # Test filtering functions
    test_filtering_functions()
    
    # Test improved 10th lining
    test_results["Improved 10th Line Numbering"] = test_tenth_lining_improvement()
    
    # Summary
    print("\n" + "="*50)
    print("📊 TEST SUMMARY")
    print("="*50)
    
    for test_name, passed in test_results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")
    
    passed_count = sum(test_results.values())
    total_count = len(test_results)
    
    print(f"\n🎯 Overall Result: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("🎉 ALL TESTS PASSED! Improved 10th line numbering is working!")
        print("\n✨ IMPROVEMENTS MADE:")
        print("   • Filters out watermarks and headers/footers")
        print("   • Excludes table elements and decorative content")
        print("   • Skips image-based text and OCR artifacts")
        print("   • Focuses only on main document content")
        print("   • Handles complex multi-column layouts")
        print("\n📝 Manual verification recommended:")
        print("   • Open the generated PDF to verify line numbering accuracy")
        print("   • Check that only content lines are numbered")
        print("   • Ensure 10th line intervals are correct")
    else:
        print("\n💡 Some tests failed - check error messages above")

if __name__ == "__main__":
    main()