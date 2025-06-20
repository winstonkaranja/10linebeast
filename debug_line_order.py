#!/usr/bin/env python3
"""
Debug the actual line ordering in PDF processing
"""

import sys
import os
import base64
import tempfile

# Mock the dependencies to avoid import errors
class MockRedis:
    def __init__(self, *args, **kwargs):
        pass
    def ping(self):
        return True
    def get(self, key):
        return None
    def setex(self, key, ttl, value):
        return True

# Patch redis import
sys.modules['redis'] = type('MockRedis', (), {'Redis': MockRedis, 'from_url': lambda *args, **kwargs: MockRedis()})()

# Now import the processor
try:
    from legal_processor import StatelessLegalProcessor
    print("✅ Successfully imported StatelessLegalProcessor")
except Exception as e:
    print(f"❌ Failed to import processor: {e}")
    sys.exit(1)

def create_test_pdf_with_numbered_lines():
    """Create a simple PDF with clearly numbered lines for testing"""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            c = canvas.Canvas(tmp_file.name, pagesize=letter)
            
            # Add 15 lines with clear numbering
            y_start = 750  # Start near top of page
            line_spacing = 25
            
            for i in range(1, 16):  # Lines 1-15
                y_pos = y_start - (i-1) * line_spacing
                text = f"This is content line number {i:02d} - should be processed in order"
                c.drawString(100, y_pos, text)
                print(f"PDF Line {i}: Y={y_pos} - {text}")
            
            c.save()
            
            # Read and encode as base64
            with open(tmp_file.name, 'rb') as pdf_file:
                pdf_content = pdf_file.read()
                pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
            
            # Clean up
            os.unlink(tmp_file.name)
            
            return pdf_base64
            
    except ImportError:
        print("❌ ReportLab not available - creating mock content")
        return None
    except Exception as e:
        print(f"❌ Error creating test PDF: {e}")
        return None

def debug_line_extraction():
    """Debug the line extraction process"""
    print("\n🔍 DEBUGGING LINE EXTRACTION PROCESS")
    print("=" * 50)
    
    # Create a mock processor to test just the line extraction
    processor = StatelessLegalProcessor()
    
    # Create mock text_dict that simulates PDF text extraction
    mock_text_dict = {
        "blocks": [
            {
                "type": 0,  # Text block
                "bbox": [100, 700, 500, 720],
                "lines": [
                    {
                        "bbox": [100, 700, 500, 720],
                        "spans": [{"text": "This is line 1 at the top of the page"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 675, 500, 695],
                "lines": [
                    {
                        "bbox": [100, 675, 500, 695],
                        "spans": [{"text": "This is line 2 below line 1"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 650, 500, 670],
                "lines": [
                    {
                        "bbox": [100, 650, 500, 670],
                        "spans": [{"text": "This is line 3 below line 2"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 625, 500, 645],
                "lines": [
                    {
                        "bbox": [100, 625, 500, 645],
                        "spans": [{"text": "This is line 4 below line 3"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 600, 500, 620],
                "lines": [
                    {
                        "bbox": [100, 600, 500, 620],
                        "spans": [{"text": "This is line 5 below line 4"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 575, 500, 595],
                "lines": [
                    {
                        "bbox": [100, 575, 500, 595],
                        "spans": [{"text": "This is line 6 below line 5"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 550, 500, 570],
                "lines": [
                    {
                        "bbox": [100, 550, 500, 570],
                        "spans": [{"text": "This is line 7 below line 6"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 525, 500, 545],
                "lines": [
                    {
                        "bbox": [100, 525, 500, 545],
                        "spans": [{"text": "This is line 8 below line 7"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 500, 500, 520],
                "lines": [
                    {
                        "bbox": [100, 500, 500, 520],
                        "spans": [{"text": "This is line 9 below line 8"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 475, 500, 495],
                "lines": [
                    {
                        "bbox": [100, 475, 500, 495],
                        "spans": [{"text": "This is line 10 - should get numbered!"}]
                    }
                ]
            },
            {
                "type": 0,  # Text block
                "bbox": [100, 450, 500, 470],
                "lines": [
                    {
                        "bbox": [100, 450, 500, 470],
                        "spans": [{"text": "This is line 11 below line 10"}]
                    }
                ]
            }
        ]
    }
    
    # Mock page_rect
    class MockPageRect:
        def __init__(self):
            self.width = 612
            self.height = 792
    
    page_rect = MockPageRect()
    
    print("📄 Mock PDF content (by Y coordinate):")
    for i, block in enumerate(mock_text_dict["blocks"]):
        bbox = block["bbox"]
        text = block["lines"][0]["spans"][0]["text"]
        y_center = (bbox[1] + bbox[3]) / 2
        print(f"   Y={y_center}: {text}")
    
    # Test the line extraction
    print("\n🔄 Running _extract_main_content_lines()...")
    extracted_lines = processor._extract_main_content_lines(mock_text_dict, page_rect)
    
    print(f"\n📊 Results: {len(extracted_lines)} lines extracted")
    print("📋 Extracted lines in processing order:")
    
    for i, line in enumerate(extracted_lines, 1):
        is_tenth = i % 10 == 0
        marker = " ← 10TH LINE NUMBER!" if is_tenth else ""
        print(f"   {i:2d}. Y={line['y']:3.0f}: {line['text'][:50]}...{marker}")
    
    # Check if order is correct
    y_values = [line['y'] for line in extracted_lines]
    is_descending = all(y_values[i] >= y_values[i+1] for i in range(len(y_values)-1))
    
    if is_descending:
        print("\n✅ Lines are correctly ordered TOP to BOTTOM")
        print("✅ 10th line numbering should appear on correct line")
    else:
        print("\n❌ Lines are NOT correctly ordered")
        print(f"Y values: {y_values}")
        print("❌ This explains why numbering appears wrong")
    
    return is_descending

def main():
    """Run debugging for line ordering"""
    print("🐛 DEBUGGING 10TH LINE NUMBERING ORDER")
    print("=" * 45)
    
    success = debug_line_extraction()
    
    if success:
        print("\n🎯 DIAGNOSIS: Line extraction logic is working correctly")
        print("💡 If you're still seeing wrong order, the issue might be:")
        print("   1. PDF cache - try clearing Redis cache")
        print("   2. Browser cache - try hard refresh")
        print("   3. Old processed file - try with new document")
        print("   4. Multiple processing steps interfering")
    else:
        print("\n🚨 DIAGNOSIS: Line extraction logic has issues")
        print("❌ The sorting is not working as expected")
        print("🔧 Need to investigate the sorting algorithm further")

if __name__ == "__main__":
    main()